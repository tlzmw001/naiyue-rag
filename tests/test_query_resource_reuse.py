"""Warm service queries must reuse the same validated immutable version."""
from test_application_runtime import runtime_job, native_query, safe_ambient, offline
import pytest


def test_warm_query_does_not_reparse_the_corpus(runtime_job, monkeypatch):
    import naiyue_rag.storage.artifact_bundle as v1
    import naiyue_rag.storage.artifact_bundle_v2 as v2
    from naiyue_rag.storage.bundle_store import BundleStore
    from naiyue_rag.storage.chroma_index import ChromaStore
    from naiyue_rag.storage.bm25_store import BM25Store

    runtime, _, _ = runtime_job
    runtime.ingest(expected_revision=0)
    first = runtime.query('feature_x threshold TC-01', expected_revision=1)
    counts = dict(parse=0, load=0, vector_audit=0, sparse_audit=0)

    def track(owner, name, key):
        original = getattr(owner, name)
        def wrapped(*args, **kwargs):
            counts[key] += 1
            return original(*args, **kwargs)
        monkeypatch.setattr(owner, name, wrapped)

    track(v1, 'prepare_knowledge_base', 'parse')
    track(v2, 'prepare_knowledge_base', 'parse')
    # Count actual reconstruction/native work, rather than calls hitting the cache facade.
    track(BundleStore, '_materialize', 'load')
    track(ChromaStore, '_audit_native', 'vector_audit')
    import naiyue_rag.storage.bm25_backend as bm25_backend
    track(bm25_backend, 'load_native', 'sparse_audit')
    second = runtime.query('feature_x threshold TC-01', expected_revision=1)
    assert first['evidence'] == second['evidence']
    assert second['active']['revision'] == 1
    assert counts == dict(parse=0, load=0, vector_audit=0, sparse_audit=0), counts


@pytest.mark.parametrize('target', ['bundle', 'vector', 'sparse'])
def test_modified_files_are_not_hidden_by_warm_cache(runtime_job, target):
    runtime, _, _ = runtime_job
    runtime.ingest(expected_revision=0)
    runtime.query('feature_x')
    version = runtime.manager.catalog.read().version
    if target == 'bundle':
        path = runtime.manager.bundles._path(version.bundle_id) / 'documents.json'
    elif target == 'vector':
        path = runtime.manager.bundles._path(version.vector_index_id, namespace='vectors') / 'ready.json'
    else:
        path = runtime.manager.bundles._path(version.bm25_index_id, namespace='bm25') / 'ready.json'
    original = path.read_bytes()
    path.write_bytes(b'X' + original[1:])  # same length; timestamp/inode checks must still invalidate
    from naiyue_rag.core.errors import QueryJobError
    with pytest.raises(QueryJobError):
        runtime.query('feature_x')
    assert runtime._resources.values == {}
    path.write_bytes(original)
    assert runtime.query('feature_x')['evidence']


def test_new_revision_replaces_cache_and_close_releases_it(runtime_job):
    runtime, seen, cfg = runtime_job
    runtime.ingest(expected_revision=0)
    runtime.query('feature_x')
    old = runtime._resources.version
    from pathlib import Path
    root = Path(cfg.knowledge_base_root)
    source = next(root.rglob('*.md'))
    source.write_text(source.read_text() + '\nNew acceptance material.\n')
    assert runtime.ingest(expected_revision=1)['active']['revision'] == 2
    assert runtime._resources.values == {}
    assert runtime.query('feature_x')['active']['revision'] == 2
    assert runtime._resources.version != old
    before = len(seen)
    assert runtime.query('feature_x')['evidence']
    assert len(seen) > before  # never cache per-query model calls
    runtime.close()
    assert runtime._resources.values == {}


def test_symlink_and_deleted_files_fail_instead_of_serving_cached_data(runtime_job):
    runtime, _, _ = runtime_job
    runtime.ingest(expected_revision=0)
    runtime.query('feature_x')
    version = runtime.manager.catalog.read().version
    path = runtime.manager.bundles._path(version.bundle_id) / 'chunks.json'
    original = path.read_bytes()
    path.unlink()
    from naiyue_rag.core.errors import QueryJobError, StorageError
    with pytest.raises(QueryJobError):
        runtime.query('feature_x')
    path.write_bytes(original)
    runtime.query('feature_x')
    backup = path.with_name('backup.json')
    path.rename(backup)
    path.symlink_to(backup)
    with pytest.raises(StorageError, match='bundle_path_invalid'):
        runtime.query('feature_x')
    assert runtime._resources.values == {}


def test_failed_request_drops_resources(runtime_job):
    runtime, _, _ = runtime_job
    runtime.ingest(expected_revision=0)
    runtime.query('feature_x')
    assert runtime._resources.values
    from naiyue_rag.core.errors import QueryJobError
    with pytest.raises(QueryJobError):
        runtime.query('feature_x', expected_revision=0)
    assert runtime._resources.values == {}


def test_native_close_failure_still_closes_provider(runtime_job, monkeypatch):
    runtime, _, _ = runtime_job
    runtime.ingest(expected_revision=0)
    runtime.query('feature_x')
    from naiyue_rag.core.errors import SettingsError
    client = next(iter(runtime._resources.clients.values()))
    def fail():
        raise OSError('synthetic close failure')
    monkeypatch.setattr(client, 'close', fail)
    with pytest.raises(SettingsError, match='application_close_failed'):
        runtime.close()
    assert runtime._provider.closed
