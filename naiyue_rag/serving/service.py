"""One long-lived retrieval service for Python, future Agent and MCP adapters."""
from ..core.application_settings import ApplicationSettings, _assemble
from ..core.errors import SettingsError
from ..query.query_processor import QueryProcessor
from pathlib import Path
import math
import time
import threading
from .engine import RetrievalEngine
from .scheduler import Scheduler
from .control import RetrievalError


class RetrievalService:
    def __init__(self, settings):
        if type(settings) is not ApplicationSettings:
            raise SettingsError('invalid_application_settings')
        self.settings = _assemble(Path(settings.config_path), settings.to_dict())
        self._engine = RetrievalEngine(self.settings)
        self._close_lock = threading.Lock()
        self._processor = QueryProcessor(self._engine._writer.registry.encoding_settings(),
                                        max_scope_documents=self.settings.storage.max_documents)
        self._scheduler = Scheduler(self._engine.execute, self.settings.retrieval,
                                    on_worker_exit=self._engine.close_slot)

    @property
    def registry(self):
        return self._engine._writer.registry

    def submit(self, query, *, scope_document_ids=None, exclude_document_ids=None,
               expected_revision=None, timeout_seconds=None):
        received = time.monotonic()
        seconds = self.settings.retrieval.request_timeout_seconds if timeout_seconds is None else timeout_seconds
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<=0:
            raise RetrievalError('retrieval_invalid_request')
        processed = self._processor.process(query, scope_document_ids=scope_document_ids,
            exclude_document_ids=exclude_document_ids, expected_revision=expected_revision)
        scope=None if processed.scope_document_ids is None else list(processed.scope_document_ids)
        remaining=seconds-(time.monotonic()-received)
        if remaining<=0:raise RetrievalError('retrieval_timeout')
        return self._scheduler.submit(processed.raw_query, scope_document_ids=scope,
            exclude_document_ids=list(processed.exclude_document_ids), expected_revision=processed.expected_revision,
            timeout_seconds=remaining)

    def query(self, query, *, scope_document_ids=None, exclude_document_ids=None,
              expected_revision=None, timeout_seconds=None):
        return self.submit(query, scope_document_ids=scope_document_ids, exclude_document_ids=exclude_document_ids,
                           expected_revision=expected_revision, timeout_seconds=timeout_seconds).result()

    def ingest(self, *, expected_revision, force=False):
        return self._engine.ingest(expected_revision=expected_revision, force=force)

    def documents(self, *, expected_revision=None):
        return self._engine.documents(expected_revision=expected_revision)

    def document(self, document_id, *, expected_revision=None):
        return self._engine.document(document_id, expected_revision=expected_revision)

    def remove(self, document_id, *, expected_revision):
        return self._engine.remove(document_id, expected_revision=expected_revision)

    def status(self):
        return self._scheduler.status()

    def close(self):
        with self._close_lock:
            self._close()

    def _close(self):
        self._engine.stop_admission()
        try:
            self._scheduler.close()
        finally:
            if self._scheduler.status()['executing'] == 0:
                self._engine.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.close()
        except Exception:
            if exc_type is None:
                raise
            import logging
            logging.getLogger(__name__).error('retrieval_cleanup_failed code=retrieval_cleanup_failed')
