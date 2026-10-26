"""One saved query representation, with configured keyword statistics semantics."""
import logging
from ..core.storage_settings import StorageSettings
from ..core.sparse_query_settings import SparseQuerySettings
from ..core.query_preparation import PreparedQuery
from ..core.sparse_results import SparseHit,SparseResult
from ..core.errors import QueryJobError,StorageError
from ..storage import DocumentManager,BM25Store,ChromaSettings,BM25Settings
from ..storage.bundle_store import _json_bytes
from .prepared_scope import validate_prepared_scope

LOGGER=logging.getLogger(__name__)


class SparseRetriever:
    def __init__(self,document_manager,settings):
        try:
            if type(document_manager) is not DocumentManager or type(settings) is not SparseQuerySettings:raise ValueError()
            self.manager=document_manager;self.config=SparseQuerySettings.from_dict(settings.to_dict())
            self.settings=StorageSettings.from_dict(document_manager.settings.to_dict())
        except Exception:raise QueryJobError('sparse','query_invalid_request') from None

    def retrieve(self,prepared):
        active=None;report=None
        try:
            if type(prepared) is not PreparedQuery:raise ValueError()
            prepared=PreparedQuery.from_dict(prepared.to_dict());active=prepared.active
            report=None if prepared.encoding is None else prepared.encoding.report
            cfg=SparseQuerySettings.from_dict(self.config.to_dict())
            if cfg.top_k>self.settings.max_chunks or self.manager.settings.to_dict()!=self.settings.to_dict():raise ValueError()
            hits=[]
            if active is not None:
                version=active.version
                if version.knowledge_base_id!=self.settings.knowledge_base_id:raise StorageError('catalog_identity_mismatch')
                bundle=self.manager.bundles.load(version.bundle_id);validate_prepared_scope(prepared,bundle)
                chroma=ChromaSettings(version.chroma_collection_name,self.manager.chroma_settings.batch_size)
                if self.manager._audit(version.bundle_id,chroma,BM25Settings(version.bm25_k1,version.bm25_b))!=version:
                    raise StorageError('catalog_identity_mismatch')
                rows=BM25Store(self.settings,BM25Settings(version.bm25_k1,version.bm25_b)).query(version.bundle_id,
                    [] if prepared.encoding is None else prepared.encoding.query_terms,
                    document_ids=prepared.document_ids,top_k=cfg.top_k,statistics_scope=cfg.statistics_scope)
                hits=[SparseHit(i,row['chunk'],row['score']) for i,row in enumerate(rows,1)]
            result=SparseResult(prepared,cfg.top_k,cfg.statistics_scope,hits)
            try:_json_bytes(result.to_dict(),self.settings.max_bundle_bytes,newline=False)
            except StorageError as error:
                if error.code=='bundle_limit_exceeded':raise QueryJobError('sparse','query_result_limit',active=active) from None
                raise
            LOGGER.info('sparse_complete statistics_scope=%s candidate_count=%s',cfg.statistics_scope,len(hits))
            return result
        except Exception as error:
            code=error.code if type(error) in (QueryJobError,StorageError) else \
                'query_invalid_request' if type(error) is ValueError else 'query_sparse_failed'
            LOGGER.error('query_failed stage=sparse code=%s',code)
            raise QueryJobError('sparse',code,active=active,encoding_report=report) from None
