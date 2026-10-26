"""One preparation, explicitly configured branches and a strict no-degradation join."""
from concurrent.futures import ThreadPoolExecutor
import logging
import time
from ..core.hybrid_settings import HybridSettings
from ..core.sparse_query_settings import SparseQuerySettings
from ..core.hybrid_results import HybridResult
from ..core.query_preparation import PreparedQuery
from ..core.trace_context import TraceContext
from ..core.errors import QueryJobError,StorageError,TraceError
from ..storage.bundle_store import _json_bytes
from .pipeline import QueryPipeline
from .dense_retriever import DenseRetriever
from .sparse_retriever import SparseRetriever
from .fusion import RRFFusion

LOGGER=logging.getLogger(__name__)


class HybridSearch:
    def __init__(self,document_manager,query_encoder,settings):
        try:
            if type(settings) is not HybridSettings:raise ValueError()
            self.settings=HybridSettings.from_dict(settings.to_dict())
            self.pipeline=QueryPipeline(document_manager,query_encoder)
        except Exception:raise QueryJobError('request','query_invalid_request') from None

    def _dense(self,prepared,cfg):
        start=time.monotonic()
        try:
            result=DenseRetriever(self.pipeline.manager).retrieve(prepared,top_k=cfg.dense_top_k)
            return result,(time.monotonic()-start)*1000,None
        except Exception as error:return None,(time.monotonic()-start)*1000,error

    def _sparse(self,prepared,cfg):
        start=time.monotonic()
        try:
            result=SparseRetriever(self.pipeline.manager,SparseQuerySettings(cfg.sparse_top_k,cfg.bm25_statistics_scope)).retrieve(prepared)
            return result,(time.monotonic()-start)*1000,None
        except Exception as error:return None,(time.monotonic()-start)*1000,error

    def _record(self,context,stage,data,elapsed):
        try:context.record_stage(stage,data,elapsed_ms=elapsed)
        except Exception:raise TraceError('query_trace_failed') from None

    def search(self,query,*,scope_document_ids=None,exclude_document_ids=None,expected_revision=None):
        stage='request';context=None;prepared=None;active=None;report=None;trace=None;preparation_error=None
        try:
            try:context=TraceContext()
            except Exception:raise TraceError('query_trace_failed') from None
            cfg=HybridSettings.from_dict(self.settings.to_dict());maximum=self.pipeline.storage_settings.max_chunks
            if max(cfg.dense_top_k,cfg.sparse_top_k,cfg.fusion_top_k)>maximum:raise QueryJobError(stage,'query_invalid_request')
            try:
                prepared=self.pipeline.prepare(query,scope_document_ids=scope_document_ids,
                    exclude_document_ids=exclude_document_ids,expected_revision=expected_revision)
            except QueryJobError as error:
                preparation_error=error;raise
            active=prepared.active;report=None if prepared.encoding is None else prepared.encoding.report
            for old in prepared.trace_report['stages']:
                stage=old['stage'];self._record(context,stage,old['data'],old['elapsed_ms'])
            dense_input=PreparedQuery.from_dict(prepared.to_dict());sparse_input=PreparedQuery.from_dict(prepared.to_dict())
            stage='dense'
            if cfg.parallel_retrieval:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    d=executor.submit(self._dense,dense_input,cfg);s=executor.submit(self._sparse,sparse_input,cfg)
                    outcomes=[d.result(),s.result()]
            else:outcomes=[self._dense(dense_input,cfg),self._sparse(sparse_input,cfg)]
            errors=[]
            for name,(result,elapsed,error) in zip(('dense','sparse'),outcomes,strict=True):
                stage=name
                if error is not None:
                    code=error.code if type(error) in (QueryJobError,StorageError) else 'query_'+name+'_failed'
                    LOGGER.error('query_failed stage=%s code=%s',name,code);errors.append((name,error))
                else:self._record(context,name,dict(eligible_count=len(prepared.chunk_ids),candidate_count=len(result.hits)),elapsed)
            if errors:
                stage,error=errors[0];raise error
            dense,sparse=outcomes[0][0],outcomes[1][0];stage='fusion';start=time.monotonic()
            hits=RRFFusion(cfg.rrf_k).fuse(dense,sparse,top_k=cfg.fusion_top_k)
            self._record(context,stage,dict(union_count=len({h.chunk.id for h in dense.hits+sparse.hits}),candidate_count=len(hits)),
                         (time.monotonic()-start)*1000)
            trace=self.pipeline._finish(context,stage)
            result=HybridResult(prepared,cfg,dense.hits,sparse.hits,hits,trace)
            try:_json_bytes(result.to_dict(),self.pipeline.storage_settings.max_bundle_bytes,newline=False)
            except StorageError as error:
                if error.code=='bundle_limit_exceeded':raise QueryJobError(stage,'query_result_limit',active=active) from None
                raise
            return result
        except QueryJobError as error:
            if error is preparation_error:raise
            self.pipeline._fail(error,stage,context,active,report,trace)
        except Exception as error:self.pipeline._fail(error,stage,context,active,report,trace)
