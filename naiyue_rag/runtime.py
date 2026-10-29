"""One owned, bounded application runtime over the existing RAG core."""
from contextlib import ExitStack,contextmanager
import logging
from pathlib import Path
import threading
from .core.application_settings import ApplicationSettings,_assemble
from .core.model_registry import load_model_registry
from .core.errors import SettingsError
from .encoding import OpenAICompatibleEmbedding,DenseEncoder,SparseEncoder,QueryEncoder,BatchProcessor
from .ingestion.pipeline import IngestionPipeline
from .storage.document_manager import DocumentManager
from .query.hybrid_search import HybridSearch
from .query.knowledge_reader import KnowledgeReader
from .query.retrieval_pipeline import RetrievalPipeline
from .reranking.core import CoreReranker
from .reranking.llm import LLMReranker
from .response.builder import ResponseBuilder
from .storage.query_cache import QueryResourceCache

LOGGER=logging.getLogger(__name__)


class ApplicationRuntime:
    def __init__(self,settings):
        try:
            if type(settings) is not ApplicationSettings:raise ValueError()
            self.settings=_assemble(Path(settings.config_path),settings.to_dict())
        except Exception:raise SettingsError('invalid_application_settings') from None
        cfg=self.settings;self.registry=load_model_registry(cfg)
        self.registry.encoding_settings()
        if cfg.rerank.backend=='llm':self.registry.llm_settings(cfg.rerank.model)
        elif cfg.rerank.backend=='cross_encoder':self.registry.local_settings(cfg.rerank.model)
        self.manager=DocumentManager(cfg.storage,cfg.chroma,cfg.bm25,project_root=Path(cfg.config_path).parent)
        self._stack=ExitStack();self._lock=threading.Lock();self._closed=False
        self._provider=None;self._dense=None;self._sparse=None;self._pipeline=None
        self._failed_closers=[]
        self._resources=QueryResourceCache()

    @contextmanager
    def _operation(self):
        if not self._lock.acquire(blocking=False):raise SettingsError('application_busy')
        try:
            if self._closed:raise SettingsError('application_closed')
            yield
        finally:self._lock.release()

    def _encoding(self):
        if self._provider is None:
            cfg=self.registry.encoding_settings();key=self.registry.resolve_key(self.settings.encoding.model)
            with ExitStack() as pending:
                provider=pending.enter_context(OpenAICompatibleEmbedding(cfg,api_key=key))
                dense=DenseEncoder(cfg,provider);sparse=SparseEncoder(cfg,self.settings.sparse)
                pending.pop_all();self._own(provider)
                self._provider=provider;self._dense=dense;self._sparse=sparse
        return self._dense,self._sparse

    def _close_owned(self,resource):
        try:resource.close()
        except Exception:
            if resource not in self._failed_closers:self._failed_closers.append(resource)
            LOGGER.error('application_resource_close_failed code=application_close_failed')
            raise

    def _own(self,resource):
        self._stack.callback(self._close_owned,resource)
        return resource

    def _query_pipeline(self):
        if self._pipeline is None:
            cfg=self.settings;dense,sparse=self._encoding();backend=None
            if cfg.rerank.backend=='llm':
                backend=self._own(LLMReranker(self.registry.llm_settings(cfg.rerank.model),
                    api_key=self.registry.resolve_key(cfg.rerank.model)))
            elif cfg.rerank.backend=='cross_encoder':
                from .reranking.cross_encoder import CrossEncoderReranker
                backend=CrossEncoderReranker(self.registry.local_settings(cfg.rerank.model))
            self._pipeline=RetrievalPipeline(HybridSearch(self.manager,
                QueryEncoder(dense.settings,dense,sparse),cfg.hybrid),CoreReranker(cfg.rerank.settings,backend),
                ResponseBuilder(KnowledgeReader(cfg.storage),cfg.evidence))
        return self._pipeline

    def documents(self,*,expected_revision=None):
        with self._operation():return self.manager.list_documents(expected_revision=expected_revision).to_dict()

    def ingest(self,*,expected_revision,force=False):
        with self._operation():
            self._resources.clear()
            cfg=self.settings;dense,sparse=self._encoding()
            pipeline=IngestionPipeline(cfg.storage,cfg.ingestion,BatchProcessor(dense.settings,dense,sparse),
                cfg.chroma,cfg.bm25,knowledge_base_root=cfg.knowledge_base_root,project_root=Path(cfg.config_path).parent)
            return pipeline.run(expected_revision=expected_revision,force=force).to_dict()

    def query(self,query,*,scope_document_ids=None,exclude_document_ids=None,expected_revision=None):
        with self._operation(),self._resources.use(self.manager):
            return self._query_pipeline().query(query,scope_document_ids=scope_document_ids,
                exclude_document_ids=exclude_document_ids,expected_revision=expected_revision)

    def remove(self,document_id,*,expected_revision):
        with self._operation():
            self._resources.clear()
            cfg=self.settings;dense,sparse=self._encoding()
            pipeline=IngestionPipeline(cfg.storage,cfg.ingestion,BatchProcessor(dense.settings,dense,sparse),
                cfg.chroma,cfg.bm25,knowledge_base_root=cfg.knowledge_base_root,project_root=Path(cfg.config_path).parent)
            return pipeline.remove_document(document_id,expected_revision=expected_revision).to_dict()

    def close(self):
        if not self._lock.acquire(blocking=False):raise SettingsError('application_busy')
        try:
            if self._closed:return
            self._closed=True
            try:
                try:self._resources.clear()
                finally:self._stack.close()
            except Exception:
                LOGGER.error('application_close_failed code=application_close_failed')
                raise SettingsError('application_close_failed') from None
        finally:self._lock.release()

    def _retry_close(self):
        if not self._lock.acquire(blocking=False):raise SettingsError('application_busy')
        try:
            retry,self._failed_closers=self._failed_closers,[]
            failed=False
            for resource in retry:
                try:self._close_owned(resource)
                except Exception:failed=True
            try:self._resources.clear()
            except Exception:
                LOGGER.error('application_resource_close_failed code=application_close_failed');failed=True
            if failed:raise SettingsError('application_close_failed')
        finally:self._lock.release()

    def __enter__(self):return self

    def __exit__(self,exc_type,exc_value,traceback):
        try:self.close()
        except SettingsError:
            if exc_type is None:raise
            LOGGER.error('application_cleanup_failed code=application_close_failed')
        return False
