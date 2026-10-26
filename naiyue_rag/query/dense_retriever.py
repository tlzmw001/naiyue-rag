"""Use one prepared query and its pinned version, without selecting latest or embedding."""
import logging
from ..core.storage_settings import StorageSettings
from ..core.query_preparation import PreparedQuery
from ..core.dense_results import DenseHit,DenseResult
from ..core.errors import QueryJobError,StorageError
from ..storage import DocumentManager,ChromaStore,ChromaSettings,BM25Settings
from ..storage.bundle_store import _json_bytes
from .prepared_scope import validate_prepared_scope

LOGGER=logging.getLogger(__name__)


class DenseRetriever:
    def __init__(self,document_manager):
        try:
            if type(document_manager) is not DocumentManager:raise ValueError()
            self.manager=document_manager
            self.settings=StorageSettings.from_dict(document_manager.settings.to_dict())
        except Exception:raise QueryJobError('dense','query_invalid_request') from None

    def retrieve(self,prepared,*,top_k):
        active=None;report=None
        try:
            if type(prepared) is not PreparedQuery:raise ValueError()
            prepared=PreparedQuery.from_dict(prepared.to_dict());active=prepared.active
            report=None if prepared.encoding is None else prepared.encoding.report
            if type(top_k) is not int or not 0<top_k<=self.settings.max_chunks or \
                    self.manager.settings.to_dict()!=self.settings.to_dict():raise ValueError()
            hits=[]
            if active is not None:
                version=active.version
                if version.knowledge_base_id!=self.settings.knowledge_base_id:raise StorageError('catalog_identity_mismatch')
                bundle=self.manager.bundles.load(version.bundle_id);validate_prepared_scope(prepared,bundle)
                chroma=ChromaSettings(version.chroma_collection_name,self.manager.chroma_settings.batch_size)
                if self.manager._audit(version.bundle_id,chroma,BM25Settings(version.bm25_k1,version.bm25_b))!=version:
                    raise StorageError('catalog_identity_mismatch')
                rows=ChromaStore(self.settings,chroma,project_root=self.manager.project_root).query(
                    version.bundle_id,prepared.encoding.dense_vector,document_ids=prepared.document_ids,top_k=top_k) \
                    if prepared.status=='ready' else []
                hits=[DenseHit(i,row['chunk'],row['distance'],row['score']) for i,row in enumerate(rows,1)]
            result=DenseResult(prepared,top_k,hits)
            try:_json_bytes(result.to_dict(),self.settings.max_bundle_bytes,newline=False)
            except StorageError as error:
                if error.code=='bundle_limit_exceeded':raise QueryJobError('dense','query_result_limit',active=active) from None
                raise
            LOGGER.info('dense_complete candidate_count=%s',len(hits))
            return result
        except Exception as error:
            code=error.code if type(error) in (QueryJobError,StorageError) else \
                'query_invalid_request' if type(error) is ValueError else 'query_dense_failed'
            LOGGER.error('query_failed stage=dense code=%s',code)
            raise QueryJobError('dense',code,active=active,encoding_report=report) from None
