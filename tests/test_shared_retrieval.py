"""The bounded service consumes the real retrieval chain with synthetic providers."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import pytest
from test_application_runtime import runtime_job, native_query, safe_ambient, offline
from naiyue_rag.serving import RetrievalService


def test_two_queries_use_distinct_clients_and_share_validated_resources(runtime_job, monkeypatch):
    _, _, cfg = runtime_job
    from naiyue_rag.encoding import OpenAICompatibleEmbedding
    original = OpenAICompatibleEmbedding.embed
    barrier, release = threading.Barrier(3), threading.Event()
    clients = set()
    def blocked(self, texts, **kwargs):
        clients.add(id(self));barrier.wait(5);assert release.wait(5)
        return original(self, texts, **kwargs)
    with RetrievalService(cfg) as service:
        service.ingest(expected_revision=0)
        monkeypatch.setattr(OpenAICompatibleEmbedding, 'embed', blocked)
        handles = [service.submit('feature_x TC-01', expected_revision=1) for _ in range(2)]
        try:
            barrier.wait(5)
            assert len(clients) == 2
        finally:release.set()
        results = [handle.result(10) for handle in handles]
        assert all(h.wait_backend(5) for h in handles)
        assert results[0]['evidence'] == results[1]['evidence'] and results[0]['evidence']
        monkeypatch.setattr(OpenAICompatibleEmbedding, 'embed', original)
        import naiyue_rag.storage.artifact_bundle_v2 as bundle
        def forbid(*args, **kwargs):raise AssertionError('warm corpus replay')
        monkeypatch.setattr(bundle, 'prepare_knowledge_base', forbid)
        assert service.query('feature_x')['evidence']


def test_update_does_not_block_old_query_and_new_queries_select_new_version(runtime_job, monkeypatch):
    _, _, cfg = runtime_job
    from naiyue_rag.encoding import OpenAICompatibleEmbedding
    original = OpenAICompatibleEmbedding.embed
    entered, release = threading.Event(), threading.Event()
    def blocked(self, texts, **kwargs):
        if any('hold_query' in text for text in texts):
            entered.set();assert release.wait(10)
        return original(self, texts, **kwargs)
    with RetrievalService(cfg) as service:
        service.ingest(expected_revision=0)
        monkeypatch.setattr(OpenAICompatibleEmbedding, 'embed', blocked)
        old = service.submit('hold_query feature_x')
        try:
            assert entered.wait(5)
            source = next(Path(cfg.knowledge_base_root).rglob('*.md'))
            source.write_text(source.read_text() + '\nNew version acceptance material.\n')
            updated = service.ingest(expected_revision=1)
            assert updated['active']['revision'] == 2
            new = service.query('feature_x')
            assert new['active']['revision'] == 2
        finally:release.set()
        assert old.result(10)['active']['revision'] == 1
        assert old.wait_backend(5)


def test_cancel_does_not_cancel_other_query_or_clear_its_resources(runtime_job, monkeypatch):
    _, _, cfg = runtime_job
    from naiyue_rag.encoding import OpenAICompatibleEmbedding
    from naiyue_rag.serving import RetrievalError
    original = OpenAICompatibleEmbedding.embed
    entered, release = threading.Event(), threading.Event()
    def blocked(self, texts, **kwargs):
        if any('hold_query' in text for text in texts):
            entered.set();assert release.wait(10)
        return original(self, texts, **kwargs)
    with RetrievalService(cfg) as service:
        service.ingest(expected_revision=0)
        monkeypatch.setattr(OpenAICompatibleEmbedding, 'embed', blocked)
        old = service.submit('hold_query')
        try:
            assert entered.wait(5)
            old.cancel()
            with pytest.raises(RetrievalError, match='retrieval_cancelled'):old.result(1)
            assert service.query('feature_x')['evidence']
        finally:release.set()
        assert old.wait_backend(5)
        assert service.query('feature_x')['evidence']
