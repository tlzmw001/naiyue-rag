"""Slot-owned model clients, shared version leases and one independent writer."""
import threading
import time

from ..runtime import ApplicationRuntime
from ..core.errors import SettingsError
from .resources import VersionResources
from .control import checkpoint, RetrievalError


class RetrievalEngine:
    def __init__(self, settings):
        self.settings = settings
        self._writer = ApplicationRuntime(settings)
        self._slots = []
        try:
            for _ in range(settings.retrieval.max_concurrent_queries):
                runtime = ApplicationRuntime(settings)
                self._slots.append(runtime)
                if runtime.registry.identity != self._writer.registry.identity:
                    raise SettingsError('invalid_models_settings')
        except Exception:
            for runtime in self._slots:
                runtime.close()
            self._writer.close()
            raise
        self._resources = VersionResources()
        self._condition = threading.Condition()
        self._writer_lock = threading.Lock()
        self._updating = False
        self._closing = False

    def execute(self, slot, control, query, **kwargs):
        checkpoint()
        runtime = self._slots[slot]
        with runtime._operation(), self._resources.lease(runtime.manager):
            checkpoint()
            return runtime._query_pipeline().query(query, **kwargs)

    def close_slot(self, slot):
        runtime = self._slots[slot]
        if runtime is not None:
            self._close_runtime(runtime)

    def _close_runtime(self, runtime):
        if runtime._closed and (runtime._failed_closers or runtime._resources.clients):
            runtime._retry_close()
        else:
            runtime.close()

    def ingest(self, *, expected_revision, force=False):
        return self._update('ingest', expected_revision=expected_revision, force=force)

    def remove(self, document_id, *, expected_revision):
        return self._update('remove', document_id=document_id, expected_revision=expected_revision)

    def _update(self, operation, **kwargs):
        if not self._writer_lock.acquire(blocking=False):
            raise RetrievalError('retrieval_update_busy')
        try:
            with self._condition:
                if self._closing:
                    raise RetrievalError('retrieval_closed')
                self._updating = True
            try:
                return getattr(self._writer, operation)(**kwargs)
            finally:
                with self._condition:
                    self._updating = False
                    self._condition.notify_all()
        finally:
            self._writer_lock.release()

    def documents(self, *, expected_revision=None):
        with self._condition:
            if self._closing:
                raise RetrievalError('retrieval_closed')
        return self._writer.manager.list_documents(expected_revision=expected_revision).to_dict()

    def document(self, document_id, *, expected_revision=None):
        with self._condition:
            if self._closing:
                raise RetrievalError('retrieval_closed')
        return self._writer.manager.get_document_detail(document_id, expected_revision=expected_revision).to_dict()

    def close(self):
        deadline = time.monotonic() + self.settings.retrieval.shutdown_timeout_seconds
        with self._condition:
            self._closing = True
            while self._updating:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RetrievalError('retrieval_shutdown_timeout')
                self._condition.wait(remaining)
        try:
            self._resources.close()
        finally:
            self._close_runtime(self._writer)

    def stop_admission(self):
        with self._condition:
            self._closing = True
