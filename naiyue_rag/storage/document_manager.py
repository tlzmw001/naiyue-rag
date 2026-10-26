"""Activate only complete audited bundles; readers pin one persisted version."""
from pathlib import Path
from ..core.storage_settings import validate_storage_settings
from ..core.chroma_settings import ChromaSettings
from ..core.bm25_settings import BM25Settings
from ..core.errors import StorageError
from .bundle_store import BundleStore,_hash,_digest,_json_bytes
from .chroma_index import ChromaStore,VectorIndexReceipt
from .bm25_store import BM25Store,BM25IndexReceipt
from .version_types import IndexVersion,ActiveVersion,ActivationReceipt,MAX_REVISION
from .index_catalog import IndexCatalog
from .document_views import _valid_document_id,project_list,project_detail


class DocumentManager:
    def __init__(self,storage_settings,chroma_settings,bm25_settings,*,project_root):
        validate_storage_settings(storage_settings)
        if type(chroma_settings) is not ChromaSettings or type(bm25_settings) is not BM25Settings:
            raise StorageError('catalog_invalid_request')
        self.settings=storage_settings
        self.chroma_settings=ChromaSettings.from_dict(chroma_settings.to_dict())
        self.bm25_settings=BM25Settings.from_dict(bm25_settings.to_dict())
        try:
            self.project_root=Path(project_root).resolve(strict=True)
            if not self.project_root.is_dir():raise ValueError()
        except Exception:raise StorageError('catalog_path_invalid') from None
        self.bundles=BundleStore(storage_settings);self.catalog=IndexCatalog(storage_settings)

    def _audit(self,bundle_id,chroma,bm25):
        bundle=self.bundles.load(bundle_id);result=bundle.encoding_result
        vector=ChromaStore(self.settings,chroma,project_root=self.project_root).audit(bundle_id)
        sparse=BM25Store(self.settings,bm25).audit(bundle_id)
        common=dict(bundle_id=bundle_id,knowledge_base_id=bundle.knowledge_base_id,
            document_count=len(bundle.documents),chunk_count=len(bundle.chunks),
            model_space_id=result.model_space_id,representation_id=result.representation_id,
            tokenizer_id=result.tokenizer_id,verified_count=len(bundle.chunks))
        if type(vector) is not VectorIndexReceipt or type(sparse) is not BM25IndexReceipt:
            raise StorageError('catalog_identity_mismatch')
        for receipt in (vector,sparse):
            values=receipt.to_dict()
            selected={key:values[key] for key in common}
            if _json_bytes(selected,self.settings.max_manifest_bytes)!=_json_bytes(common,self.settings.max_manifest_bytes) or \
                    receipt.status!='verified' or type(receipt.schema_version) is not int or receipt.schema_version!=1:
                raise StorageError('catalog_identity_mismatch')
        if type(vector.dimensions) is not int or vector.dimensions!=result.dimensions:
            raise StorageError('catalog_identity_mismatch')
        raw=dict(schema_version=1,knowledge_base_id=bundle.knowledge_base_id,bundle_id=bundle_id,
            vector_index_id=vector.index_id,bm25_index_id=sparse.index_id,document_count=len(bundle.documents),
            chunk_count=len(bundle.chunks),source_fingerprint=bundle.relations['source_fingerprint'],
            model_space_id=result.model_space_id,representation_id=result.representation_id,
            tokenizer_id=result.tokenizer_id,dimensions=result.dimensions,chroma_collection_name=chroma.collection_name,
            chroma_sdk_version=vector.sdk_version,bm25_k1=bm25.k1,bm25_b=bm25.b,bm25_sdk_version=sparse.sdk_version)
        raw['version_id']=_digest(_json_bytes(raw,self.settings.max_manifest_bytes,newline=False))
        return IndexVersion.from_dict(raw)

    def activate(self,bundle_id,*,expected_revision):
        if not _hash(bundle_id) or type(expected_revision) is not int or not 0<=expected_revision<=MAX_REVISION:
            raise StorageError('catalog_invalid_request')
        with self.catalog.write() as conn:
            current=self.catalog.current(conn);revision=0 if current is None else current.revision
            if revision!=expected_revision:raise StorageError('catalog_revision_conflict')
            version=self._audit(bundle_id,self.chroma_settings,self.bm25_settings)
            existing=self.catalog.lookup(conn,version.version_id)
            if existing is not None and existing!=version:raise StorageError('catalog_integrity_failed')
            if current is not None and current.version==version:
                receipt=ActivationReceipt('unchanged',current)
            else:
                if revision==MAX_REVISION:raise StorageError('catalog_limit_exceeded')
                active=ActiveVersion(revision+1,version)
                self.catalog.publish(conn,version,active.revision)
                receipt=ActivationReceipt('activated',active)
        return receipt

    def open_active(self):
        active=self.catalog.read()
        if active is None:return None
        version=active.version
        chroma=ChromaSettings(version.chroma_collection_name,self.chroma_settings.batch_size)
        bm25=BM25Settings(version.bm25_k1,version.bm25_b)
        actual=self._audit(version.bundle_id,chroma,bm25)
        if actual!=version:raise StorageError('catalog_identity_mismatch')
        return active

    def _document_bundle(self,expected_revision):
        if expected_revision is not None and (type(expected_revision) is not int or not 0<=expected_revision<=MAX_REVISION):
            raise StorageError('document_invalid_request')
        active=self.catalog.read()
        revision=0 if active is None else active.revision
        if expected_revision is not None and expected_revision!=revision:raise StorageError('catalog_revision_conflict')
        if active is None:return None,None
        bundle=self.bundles.load(active.version.bundle_id);result=bundle.encoding_result;version=active.version
        actual=(bundle.knowledge_base_id,len(bundle.documents),len(bundle.chunks),bundle.relations['source_fingerprint'],
                result.model_space_id,result.representation_id,result.tokenizer_id,result.dimensions)
        expected=(version.knowledge_base_id,version.document_count,version.chunk_count,version.source_fingerprint,
                  version.model_space_id,version.representation_id,version.tokenizer_id,version.dimensions)
        if actual!=expected or bundle.knowledge_base_id!=self.settings.knowledge_base_id:
            raise StorageError('catalog_identity_mismatch')
        return active,bundle

    def _document_response(self,response):
        try:_json_bytes(response.to_dict(),self.settings.max_bundle_bytes,newline=False)
        except StorageError as error:
            if error.code=='bundle_limit_exceeded':raise StorageError('document_limit_exceeded') from None
            raise
        return response

    def list_documents(self,*,expected_revision=None):
        active,bundle=self._document_bundle(expected_revision)
        return self._document_response(project_list(active,bundle))

    def get_document_detail(self,document_id,*,expected_revision=None):
        if not _valid_document_id(document_id):raise StorageError('document_invalid_request')
        active,bundle=self._document_bundle(expected_revision)
        return self._document_response(project_detail(active,bundle,document_id))
