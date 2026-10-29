"""Cancellation reaches existing SDK and stream boundaries without global state."""
import time
import httpx
import pytest
from test_application_runtime import runtime_job, native_query, safe_ambient, offline
from test_openai_embedding import payload
from naiyue_rag.serving.control import RequestControl, checkpoint, remaining_timeout, RetrievalError


def test_cancelled_context_restores_the_next_call():
    control = RequestControl(time.monotonic() + 10)
    with control.use():
        control.cancelled.set()
        with pytest.raises(RetrievalError, match='retrieval_cancelled'):checkpoint()
    checkpoint()
    assert remaining_timeout(5) == 5


def test_remaining_request_budget_limits_existing_provider_timeout(runtime_job, monkeypatch):
    runtime, _, _ = runtime_job
    timeouts = []
    def respond(request):
        timeouts.append(request.extensions['timeout'])
        return httpx.Response(200, json=payload(1))
    monkeypatch.setattr(httpx, 'HTTPTransport', lambda **kwargs: httpx.MockTransport(respond))
    dense, _ = runtime._encoding()
    control = RequestControl(time.monotonic() + 3)
    with control.use():
        runtime._provider.embed(['synthetic'], timeout_seconds=100)
    assert len(timeouts) == 1
    assert all(0 < value <= 3 for value in timeouts[0].values())
    with control.use():
        control.cancelled.set()
        with pytest.raises(RetrievalError):runtime._provider.embed(['synthetic'], timeout_seconds=100)
    assert len(timeouts) == 1


def test_shutdown_stops_writer_admission(runtime_job):
    from naiyue_rag.serving import RetrievalService
    _, _, cfg = runtime_job
    service = RetrievalService(cfg)
    service.close()
    with pytest.raises(RetrievalError, match='retrieval_closed'):service.ingest(expected_revision=0)
    with pytest.raises(RetrievalError, match='retrieval_closed'):service.submit('feature_x')


def test_slot_close_failure_can_be_retried(runtime_job, monkeypatch):
    from naiyue_rag.serving import RetrievalService
    _, _, cfg = runtime_job
    service = RetrievalService(cfg)
    service.ingest(expected_revision=0)
    handle = service.submit('feature_x');assert handle.result(10)['evidence'];assert handle.wait_backend(5)
    runtime = next(runtime for runtime in service._engine._slots if runtime._provider is not None)
    original = runtime._provider.close
    calls = []
    def close():
        calls.append(1)
        if len(calls) == 1:raise OSError('synthetic transient close failure')
        original()
    monkeypatch.setattr(runtime._provider, 'close', close)
    with pytest.raises(RetrievalError, match='retrieval_cleanup_failed'):service.close()
    service.close()
    assert calls == [1, 1] and runtime._provider.closed


@pytest.mark.parametrize('kind', ['embedding', 'rerank'])
def test_sdk_close_failure_retries_the_underlying_client(runtime_job, monkeypatch, kind):
    from naiyue_rag.core.errors import SettingsError
    runtime, _, _ = runtime_job
    pipeline = runtime._query_pipeline()
    provider = runtime._provider if kind == 'embedding' else pipeline.reranker.backend
    original = provider._client.close
    calls = []
    def close():
        calls.append(1)
        if len(calls) == 1:raise OSError('synthetic SDK close failure')
        original()
    monkeypatch.setattr(provider._client, 'close', close)
    with pytest.raises(SettingsError, match='application_close_failed'):runtime.close()
    assert runtime._failed_closers == [provider]
    runtime._retry_close()
    assert calls == [1, 1] and runtime._failed_closers == []
