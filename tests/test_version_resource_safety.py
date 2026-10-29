"""Failures keep ownership; business mutations are not native maintenance."""
from pathlib import Path
import threading
import pytest
from test_application_runtime import runtime_job, native_query, safe_ambient, offline


def test_business_stamp_excludes_windows_native_paths(monkeypatch):
    from pathlib import PureWindowsPath
    import naiyue_rag.storage.query_cache as module
    root = PureWindowsPath('C:/kb/vectors/version')
    stamp = ((str(root / 'chroma' / 'chroma.sqlite3'), 1),
             (str(root / 'ready.json'), 2), (str(root / 'chroma-other'), 3))
    monkeypatch.setattr(module, 'Path', PureWindowsPath)
    assert module.business_stamp(stamp, root) == stamp[1:]


def test_failed_native_close_retains_ownership_for_retry():
    from naiyue_rag.storage.query_cache import QueryResourceCache
    from naiyue_rag.core.errors import StorageError
    class Client:
        calls = 0
        def close(self):
            self.calls += 1
            if self.calls == 1:raise OSError('synthetic')
    cache = QueryResourceCache();client = Client();cache.clients['test'] = client
    with pytest.raises(StorageError, match='chroma_close_failed'):cache.clear()
    assert cache.clients == {'test': client}
    cache.clear()
    assert not cache.clients and client.calls == 2


@pytest.mark.parametrize('shared', [False, True])
def test_cold_business_mutation_is_rejected(runtime_job, monkeypatch, shared):
    runtime, _, _ = runtime_job
    runtime.ingest(expected_revision=0)
    from naiyue_rag.storage.query_cache import QueryResourceCache
    from naiyue_rag.serving.resources import VersionResources
    from naiyue_rag.core.errors import StorageError
    from naiyue_rag.serving import RetrievalError
    resources = VersionResources() if shared else QueryResourceCache()
    original = runtime.manager._audit
    active = runtime.manager.catalog.read()
    path = runtime.manager.bundles._path(active.version.bundle_id) / 'documents.json'
    def changed(*args):
        value = original(*args)
        path.write_bytes(path.read_bytes() + b' ')
        return value
    monkeypatch.setattr(runtime.manager, '_audit', changed)
    context = resources.lease(runtime.manager) if shared else resources.use(runtime.manager)
    try:
        with pytest.raises((StorageError, RetrievalError)):
            with context:
                if not shared:runtime.manager._audit(active.version.bundle_id, runtime.manager.chroma_settings, runtime.manager.bm25_settings)
    finally:
        if shared:resources.close()
        else:resources.clear()


def test_failed_update_preserves_current_query_version(runtime_job, monkeypatch):
    from naiyue_rag.serving import RetrievalService
    runtime, _, cfg = runtime_job
    with RetrievalService(cfg) as service:
        service.ingest(expected_revision=0)
        original = service.query('feature_x')
        from naiyue_rag.encoding import OpenAICompatibleEmbedding
        def fail(*args, **kwargs):raise OSError('synthetic provider unavailable')
        source = next(Path(cfg.knowledge_base_root).rglob('*.md'))
        source.write_text(source.read_text() + '\nChanged content.\n')
        with monkeypatch.context() as patch:
            patch.setattr(OpenAICompatibleEmbedding, 'embed', fail)
            from naiyue_rag.core.errors import IngestionJobError
            with pytest.raises(IngestionJobError):service.ingest(expected_revision=1)
        result = service.query('feature_x')
        assert result['active'] == original['active'] and result['evidence'] == original['evidence']
