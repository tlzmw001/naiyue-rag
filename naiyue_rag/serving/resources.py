"""Reference-counted version resources, shared by independent request contexts."""
from contextlib import contextmanager
from dataclasses import dataclass
import logging
import threading
import sys

from ..core.errors import StorageError
from ..storage.query_cache import QueryResourceCache, bind_query_resources, business_stamp
from ..storage import ChromaSettings, BM25Settings
from .control import checkpoint, RetrievalError

LOGGER = logging.getLogger(__name__)


@dataclass
class _Entry:
    active: object
    cache: QueryResourceCache
    roots: list
    refs: int = 0
    invalid: bool = False


class VersionResources:
    def __init__(self):
        self._lock = threading.RLock()
        self._entries = {}
        self._current = None
        self._closed = False

    def _dispose(self, key):
        entry = self._entries[key]
        try:
            entry.cache.clear()
        except Exception:
            entry.invalid = True
            LOGGER.error('retrieval_resources_cleanup_failed code=chroma_close_failed')
            raise
        del self._entries[key]

    def _create(self, manager, active):
        version = active.version
        roots = [manager.bundles._path(version.bundle_id),
                 manager.bundles._path(version.vector_index_id, namespace='vectors'),
                 manager.bundles._path(version.bm25_index_id, namespace='bm25')]
        cache = QueryResourceCache()
        cache.version = active
        cache.identities = {version.bundle_id, *(str(root) for root in roots)}
        entry = _Entry(active, cache, roots)
        before = cache._stamp(roots)
        try:
            with bind_query_resources(cache, manager, active):
                checkpoint()
                manager._document_bundle(active.revision)
                actual = manager._audit(version.bundle_id,
                    ChromaSettings(version.chroma_collection_name, manager.chroma_settings.batch_size),
                    BM25Settings(version.bm25_k1, version.bm25_b))
                if actual != version:
                    raise StorageError('catalog_identity_mismatch')
                checkpoint()
            after = cache._stamp(roots)
            if business_stamp(before, roots[1]) != business_stamp(after, roots[1]):
                raise RetrievalError('retrieval_resources_changed')
            cache.stamp = after
            return entry
        except BaseException:
            try:
                cache.clear()
            except Exception:
                # Preserve ownership of clients which failed to close for service.close().
                entry.invalid = True
                self._entries[active] = entry
                LOGGER.error('retrieval_resources_cleanup_failed code=chroma_close_failed')
            raise

    @contextmanager
    def lease(self, manager):
        checkpoint()
        with self._lock:
            if self._closed:
                raise RetrievalError('retrieval_closed')
            active = manager.catalog.read()
            self._current = active
            for old in list(self._entries):
                if old != active and self._entries[old].refs == 0:
                    self._dispose(old)
            if active is None:
                entry = None
            else:
                entry = self._entries.get(active)
                if entry is not None:
                    changed = entry.cache._stamp(entry.roots) != entry.cache.stamp
                    if changed:
                        entry.invalid = True
                    if entry.invalid:
                        if entry.refs:
                            raise RetrievalError('retrieval_resources_changed')
                        self._dispose(active)
                        entry = None
                if entry is None:
                    entry = self._create(manager, active)
                    self._entries[active] = entry
                entry.refs += 1
        try:
            with bind_query_resources(None if entry is None else entry.cache, manager, active):
                checkpoint()
                yield
                checkpoint()
        except Exception as error:
            if entry is not None and getattr(error, 'code', '').startswith(('bundle_', 'chroma_', 'bm25_', 'catalog_')):
                with self._lock:
                    entry.invalid = True
            raise
        finally:
            primary_failure = sys.exc_info()[0] is not None
            if entry is not None:
                with self._lock:
                    entry.refs -= 1
                    try:
                        if entry.cache._stamp(entry.roots) != entry.cache.stamp:
                            entry.invalid = True
                    except Exception:
                        entry.invalid = True
                        LOGGER.error('retrieval_resources_changed code=artifact_stat_failed')
                    if not entry.refs and (entry.invalid or entry.active != self._current):
                        try:
                            self._dispose(entry.active)
                        except Exception:
                            if not primary_failure:
                                raise
                            LOGGER.error('retrieval_resources_cleanup_failed code=chroma_close_failed')

    def close(self):
        with self._lock:
            self._closed = True
            failed = False
            for key in list(self._entries):
                entry = self._entries[key]
                if entry.refs:
                    failed = True
                    continue
                try:
                    self._dispose(key)
                except Exception:
                    failed = True
            if failed:
                raise RetrievalError('retrieval_cleanup_failed')
