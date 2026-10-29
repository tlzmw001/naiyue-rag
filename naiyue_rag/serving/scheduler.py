"""A bounded FIFO queue with execution ownership retained after caller timeout."""
from collections import deque
import asyncio
from concurrent.futures import Future
import logging
import math
import threading
import time
import uuid

from ..core.retrieval_settings import RetrievalSettings
from .control import RequestControl, RetrievalError

LOGGER = logging.getLogger(__name__)


class QueryHandle:
    def __init__(self, scheduler, args, kwargs, deadline):
        self.request_id = uuid.uuid4().hex
        self._scheduler = scheduler
        self._args, self._kwargs = args, kwargs
        self._future = Future()
        self.control = RequestControl(deadline)
        self._state = 'queued'
        self._started = False
        self._finished = threading.Event()
        self._submitted_at = time.monotonic()
        self._started_at = self._terminal_at = None

    def result(self, timeout=None):
        return self._future.result(timeout)

    async def async_result(self):
        future = asyncio.wrap_future(self._future)
        # A detached waiter must still retrieve its eventual exception.
        future.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            self.cancel()
            raise

    def cancel(self):
        return self._scheduler._cancel(self)

    def wait_backend(self, timeout=None):
        return self._finished.wait(timeout)

    def status(self):
        with self._scheduler._condition:
            end = self._terminal_at if self._terminal_at is not None else time.monotonic()
            return dict(request_id=self.request_id, state=self._state,
                        backend_finished=self._finished.is_set(), elapsed_seconds=max(0, end-self._submitted_at),
                        queue_seconds=max(0, (self._started_at or end)-self._submitted_at),
                        execution_seconds=0 if self._started_at is None else max(0, end-self._started_at))


class Scheduler:
    def __init__(self, execute, settings, *, on_worker_exit=None):
        if type(settings) is not RetrievalSettings:
            raise ValueError('invalid_retrieval_settings')
        self.settings = RetrievalSettings.from_dict(settings.to_dict())
        self._execute, self._on_worker_exit = execute, on_worker_exit
        self._condition = threading.Condition()
        self._slots = [None] * settings.max_concurrent_queries
        self._queue = deque()
        self._closed = False
        self._cleanup_failed = set()
        self._workers = [threading.Thread(target=self._worker, args=(i,), daemon=True,
                        name=f'nyr-query-{i}') for i in range(len(self._slots))]
        self._monitor = threading.Thread(target=self._watch, daemon=True, name='nyr-query-deadlines')
        for worker in self._workers:
            worker.start()
        self._monitor.start()

    def submit(self, *args, timeout_seconds=None, **kwargs):
        seconds = self.settings.request_timeout_seconds if timeout_seconds is None else timeout_seconds
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise RetrievalError('retrieval_invalid_request')
        with self._condition:
            if self._closed:
                raise RetrievalError('retrieval_closed')
            self._expire()
            handle = QueryHandle(self, args, kwargs, time.monotonic() + seconds)
            if None in self._slots:
                index = self._slots.index(None)
                self._assign(index, handle)
            elif len(self._queue) < self.settings.max_queued_queries:
                self._queue.append(handle)
            else:
                raise RetrievalError('retrieval_overloaded')
            self._condition.notify_all()
            return handle

    def _assign(self, index, handle):
        self._slots[index] = handle
        handle._state = 'running'

    def _finish_caller(self, handle, code):
        if handle._future.done():
            return False
        handle._state = 'timed_out' if code == 'retrieval_timeout' else 'cancelled'
        handle._terminal_at = time.monotonic()
        handle.control.cancelled.set()
        handle._future.set_exception(RetrievalError(code))
        return True

    def _cancel(self, handle):
        with self._condition:
            changed = self._finish_caller(handle, 'retrieval_cancelled')
            self._prune()
            self._condition.notify_all()
            return changed

    def _prune(self):
        pending = deque()
        for handle in self._queue:
            if handle._future.done():
                handle._finished.set()
            else:
                pending.append(handle)
        self._queue = pending
        for index, handle in enumerate(self._slots):
            if handle is not None and not handle._started and handle._future.done():
                handle._finished.set()
                self._slots[index] = None
            if self._slots[index] is None and self._queue and not self._closed:
                self._assign(index, self._queue.popleft())

    def _expire(self):
        now = time.monotonic()
        for handle in [*self._queue, *(h for h in self._slots if h is not None)]:
            if now >= handle.control.deadline:
                self._finish_caller(handle, 'retrieval_timeout')
        self._prune()

    def _watch(self):
        with self._condition:
            while not self._closed:
                self._expire()
                deadlines = [h.control.deadline for h in [*self._queue, *self._slots]
                             if h is not None and not h._future.done()]
                self._condition.wait(None if not deadlines else max(0, min(deadlines) - time.monotonic()))

    def _worker(self, index):
        try:
            while True:
                with self._condition:
                    while self._slots[index] is None and not self._closed:
                        self._condition.wait()
                    handle = self._slots[index]
                    if handle is None:
                        return
                    handle._started = True
                    handle._started_at = time.monotonic()
                value = error = None
                try:
                    with handle.control.use():
                        value = self._execute(index, handle.control, *handle._args, **handle._kwargs)
                        handle.control.check()
                except BaseException as failure:
                    error = failure if isinstance(failure, Exception) else RetrievalError('retrieval_worker_failed')
                    LOGGER.warning('retrieval_request_failed request_id=%s', handle.request_id)
                finally:
                    with self._condition:
                        self._expire()
                        if not handle._future.done():
                            handle._terminal_at = time.monotonic()
                            if error is None:
                                handle._state = 'succeeded';handle._future.set_result(value)
                            else:
                                handle._state = 'failed';handle._future.set_exception(error)
                        handle._finished.set()
                        self._slots[index] = None
                        self._prune()
                        self._condition.notify_all()
        finally:
            if self._on_worker_exit is not None:
                try:
                    self._on_worker_exit(index)
                except Exception:
                    LOGGER.error('retrieval_worker_cleanup_failed slot=%s', index)
                    with self._condition:
                        self._cleanup_failed.add(index)

    def status(self):
        with self._condition:
            self._expire()
            return dict(closed=self._closed, executing=sum(h is not None for h in self._slots),
                        queued=len(self._queue), draining=sum(h is not None and h._future.done() for h in self._slots))

    def close(self):
        if threading.current_thread() in self._workers:
            raise RetrievalError('retrieval_shutdown_timeout')
        with self._condition:
            retry_cleanup = set(self._cleanup_failed)
            self._closed = True
            for handle in [*self._queue, *(h for h in self._slots if h is not None)]:
                self._finish_caller(handle, 'retrieval_cancelled')
            self._prune()
            self._condition.notify_all()
        deadline = time.monotonic() + self.settings.shutdown_timeout_seconds
        for worker in [*self._workers, self._monitor]:
            worker.join(max(0, deadline - time.monotonic()))
        if any(worker.is_alive() for worker in self._workers):
            raise RetrievalError('retrieval_shutdown_timeout')
        for index in retry_cleanup:
            try:
                self._on_worker_exit(index)
            except Exception:
                LOGGER.error('retrieval_worker_cleanup_failed slot=%s', index)
            else:
                self._cleanup_failed.discard(index)
        if self._cleanup_failed:
            raise RetrievalError('retrieval_cleanup_failed')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
