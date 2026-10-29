"""Deterministic admission, cancellation and execution ownership contracts."""
import threading
import pytest
from naiyue_rag.serving.scheduler import Scheduler
from naiyue_rag.serving.control import RetrievalError
from naiyue_rag.core.retrieval_settings import RetrievalSettings


def test_ten_requests_overlap_and_fifo_queue_is_bounded():
    entered = threading.Barrier(3)
    release = threading.Event()
    seen = []
    lock = threading.Lock()
    def execute(slot, control, number):
        with lock:seen.append(number)
        if number < 2:
            entered.wait(5)
            assert release.wait(5)
        control.check()
        return number
    scheduler = Scheduler(execute, RetrievalSettings())
    try:
        handles = [scheduler.submit(i) for i in range(22)]
        entered.wait(5)
        assert scheduler.status()['executing'] == 2
        assert scheduler.status()['queued'] == 20
        with pytest.raises(RetrievalError, match='retrieval_overloaded'):scheduler.submit(22)
        release.set()
        assert [h.result(5) for h in handles] == list(range(22))
        assert all(h.wait_backend(5) for h in handles)
        assert seen[:2] in ([0, 1], [1, 0])
    finally:
        release.set();scheduler.close()


def test_cancelled_running_request_keeps_its_slot_until_exit():
    entered, release = threading.Event(), threading.Event()
    def execute(slot, control, value):
        if value == 1:
            entered.set();assert release.wait(5)
        return value
    scheduler = Scheduler(execute, RetrievalSettings(1, 1, 10, 1))
    try:
        first = scheduler.submit(1);assert entered.wait(5)
        assert first.cancel()
        with pytest.raises(RetrievalError, match='retrieval_cancelled'):first.result(1)
        assert first.status()['backend_finished'] is False
        second = scheduler.submit(2)
        assert second.status()['state'] == 'queued'
        with pytest.raises(RetrievalError, match='retrieval_overloaded'):scheduler.submit(3)
        assert second.cancel() and second.wait_backend(1)
        third = scheduler.submit(3)
        release.set()
        assert first.wait_backend(5)
        assert third.result(5) == 3
    finally:
        release.set();scheduler.close()


def test_queued_timeout_does_not_execute_and_running_timeout_does_not_free_slot():
    entered, release = threading.Event(), threading.Event()
    seen = []
    def execute(slot, control, value):
        seen.append(value);entered.set();assert release.wait(5)
        return value
    scheduler = Scheduler(execute, RetrievalSettings(1, 1, 10, 1))
    try:
        first = scheduler.submit(1, timeout_seconds=.1);assert entered.wait(5)
        second = scheduler.submit(2, timeout_seconds=.1)
        for handle in (first, second):
            with pytest.raises(RetrievalError, match='retrieval_timeout'):handle.result(3)
        assert scheduler.status()['executing'] == 1
        assert scheduler.status()['queued'] == 0
        assert seen == [1] and second.wait_backend(1)
        release.set();assert first.wait_backend(5)
    finally:
        release.set();scheduler.close()


def test_failure_does_not_kill_worker_or_retry():
    seen = []
    def execute(slot, control, value):
        seen.append(value)
        if value == 1:raise ValueError('synthetic private error')
        return value
    with Scheduler(execute, RetrievalSettings(1, 1, 10, 1)) as scheduler:
        first = scheduler.submit(1)
        with pytest.raises(ValueError, match='synthetic private error'):first.result(3)
        assert first.wait_backend(3)
        assert scheduler.submit(2).result(3) == 2
    assert seen == [1, 2]


def test_close_timeout_is_explicit_and_can_be_waited_again():
    entered, release = threading.Event(), threading.Event()
    def execute(slot, control):
        entered.set();release.wait(5)
    scheduler = Scheduler(execute, RetrievalSettings(1, 1, 10, .05))
    handle = scheduler.submit();assert entered.wait(5)
    try:
        with pytest.raises(RetrievalError, match='retrieval_shutdown_timeout'):scheduler.close()
        with pytest.raises(RetrievalError, match='retrieval_closed'):scheduler.submit()
    finally:
        release.set();assert handle.wait_backend(5);scheduler.close()


def test_failed_worker_cleanup_is_retried_by_next_close():
    calls = []
    def cleanup(slot):
        calls.append(slot)
        if len(calls) == 1:raise OSError('synthetic transient close failure')
    scheduler = Scheduler(lambda *args: None, RetrievalSettings(1, 1, 10, 1), on_worker_exit=cleanup)
    with pytest.raises(RetrievalError, match='retrieval_cleanup_failed'):scheduler.close()
    scheduler.close()
    assert calls == [0, 0]


@pytest.mark.parametrize('values', [(0,20,180,10),(2,-1,180,10),(True,20,180,10),
    (2,20,0,10),(2,20,float('inf'),10),(2,20,180,False)])
def test_invalid_settings(values):
    with pytest.raises(ValueError):RetrievalSettings(*values)
