"""Versioned keyword artifacts bound to one complete M1/M2/M3 bundle."""
from dataclasses import dataclass,asdict
import os
import uuid
from ..core.bm25_settings import BM25Settings
from ..core.storage_settings import validate_storage_settings
from ..core.errors import StorageError
from .bundle_store import BundleStore,_digest,_hash,_json_bytes,_parse
from . import bm25_backend as backend


@dataclass(frozen=True)
class BM25IndexReceipt:
    schema_version:int
    status:str
    index_id:str
    bundle_id:str
    knowledge_base_id:str
    document_count:int
    chunk_count:int
    tokenized_chunk_count:int
    empty_chunk_count:int
    vocab_count:int
    avgdl:float
    verified_count:int
    model_space_id:str
    representation_id:str
    tokenizer_id:str
    sdk_version:str

    def to_dict(self):return asdict(self)


class BM25Store:
    """Read-only audits; missing/corrupt keyword artifacts are never empty results."""
    def __init__(self,storage_settings,bm25_settings):
        validate_storage_settings(storage_settings)
        if type(bm25_settings) is not BM25Settings:raise StorageError('bm25_invalid_request')
        self.settings=storage_settings;self.config=BM25Settings.from_dict(bm25_settings.to_dict())
        self.bundles=BundleStore(storage_settings)

    def _path(self,index_id):
        return self.bundles._path(index_id,namespace='bm25',error_code='bm25_path_invalid')

    def _prepare(self,bundle_id):
        bundle=self.bundles.load(bundle_id);result=bundle.encoding_result;records=[r.sparse for r in result.records]
        postings,avgdl,nnz=backend.statistics(records)
        if max(len(records),len(postings),nnz)>2147483647:raise StorageError('bm25_limit_exceeded')
        # Bound native payloads before the SDK allocates its arrays; header overhead is checked after save.
        if max(nnz*8,nnz*4,(len(postings)+1)*8)>self.settings.max_file_bytes:raise StorageError('bm25_limit_exceeded')
        policy=dict(schema_version=1,bundle_id=bundle_id,**self.config.to_dict(),sdk_version=backend.SDK_VERSION,
                    storage_policy='bm25s-lucene-v1')
        index_id=_digest(_json_bytes(policy,self.settings.max_manifest_bytes,newline=False))
        rows=[dict(item_id=r.input.item_id,source_document_id=r.input.source_document_id,
            source_sha256=r.input.source_sha256,retrieval_text_sha256=r.input.retrieval_text_sha256,
            doc_length=r.sparse.doc_length,unique_terms=r.sparse.unique_terms) for r in result.records]
        tokenized=sum(bool(r.tokens) for r in records)
        header=dict(schema_version=1,status='ready',index_id=index_id,bundle_id=bundle_id,
            knowledge_base_id=bundle.knowledge_base_id,document_count=len(bundle.documents),chunk_count=len(records),
            tokenized_chunk_count=tokenized,empty_chunk_count=len(records)-tokenized,vocab_count=len(postings),
            avgdl=avgdl,verified_count=len(records),model_space_id=result.model_space_id,
            representation_id=result.representation_id,tokenizer_id=result.tokenizer_id,sdk_version=backend.SDK_VERSION,
            source_fingerprint=bundle.relations['source_fingerprint'],parameters=backend.parameters(self.config),
            native_state='indexed' if postings else 'empty',
            terms_sha256=_digest(_json_bytes([r.to_dict() for r in records],self.settings.max_bundle_bytes)))
        return self._path(index_id),header,rows,records

    def _receipt(self,header,status):
        return BM25IndexReceipt(**{k:status if k=='status' else header[k] for k in BM25IndexReceipt.__dataclass_fields__})

    def _read_file(self,path,limit):
        try:return self.bundles._read_file(path,limit)
        except StorageError as error:
            raise StorageError('bm25_limit_exceeded' if error.code=='bundle_limit_exceeded' else
                               'bm25_path_invalid' if error.code=='bundle_path_invalid' else 'bm25_read_failed') from None
        except Exception:raise StorageError('bm25_read_failed') from None

    def _payloads(self,path,names):
        payloads={name:self._read_file(path/name,self.settings.max_file_bytes) for name in names}
        if sum(map(len,payloads.values()))>self.settings.max_bundle_bytes:raise StorageError('bm25_limit_exceeded')
        return payloads

    def _load_index(self,path,expected,rows,records):
        if not path.exists():raise StorageError('bm25_index_not_found')
        try:
            names={'rows.json'}|(set(backend.NATIVE_FILES) if expected['native_state']=='indexed' else set())
            if {p.name for p in path.iterdir()}!=names|{'ready.json'}:raise StorageError('bm25_index_incomplete')
            raw=self._read_file(path/'ready.json',self.settings.max_manifest_bytes)
            try:marker=_parse(raw)
            except StorageError:raise StorageError('bm25_index_incomplete') from None
            if type(marker) is not dict or set(marker)!=set(expected)|{'files'}:raise StorageError('bm25_index_incomplete')
            if _json_bytes({k:marker[k] for k in expected},self.settings.max_manifest_bytes)!=_json_bytes(expected,self.settings.max_manifest_bytes):
                raise StorageError('bm25_identity_mismatch')
            descriptors=marker['files']
            if type(descriptors) is not dict or set(descriptors)!=names:raise StorageError('bm25_index_incomplete')
            total=len(raw)
            for value in descriptors.values():
                if type(value) is not dict or set(value)!={'bytes','sha256'} or type(value['bytes']) is not int or \
                        value['bytes']<=0 or not _hash(value['sha256']):raise StorageError('bm25_integrity_failed')
                if value['bytes']>self.settings.max_file_bytes:raise StorageError('bm25_limit_exceeded')
                total+=value['bytes']
            if total>self.settings.max_bundle_bytes:raise StorageError('bm25_limit_exceeded')
            payloads=self._payloads(path,sorted(names))
            for name,content in payloads.items():
                if len(content)!=descriptors[name]['bytes'] or _digest(content)!=descriptors[name]['sha256']:
                    raise StorageError('bm25_integrity_failed')
            if payloads['rows.json']!=_json_bytes(rows,self.settings.max_file_bytes):raise StorageError('bm25_integrity_failed')
            backend.check_runtime()
            if expected['native_state']=='empty':return None
            return backend.load_native(path,payloads,records,self.config)
        except StorageError:raise
        except Exception:raise StorageError('bm25_read_failed') from None

    def audit(self,bundle_id):
        path,header,rows,records=self._prepare(bundle_id)
        self._load_index(path,header,rows,records)
        return self._receipt(header,'verified')

    def query(self,bundle_id,query_terms,*,document_ids,top_k,statistics_scope):
        from .bm25_query import query_index
        return query_index(self,bundle_id,query_terms,document_ids=document_ids,top_k=top_k,statistics_scope=statistics_scope)


class BM25Indexer(BM25Store):
    """Full new candidates; no in-place updates and no automatic activation."""
    def build(self,bundle_id):
        path,header,rows,records=self._prepare(bundle_id)
        if path.exists():
            self._load_index(path,header,rows,records)
            return self._receipt(header,'unchanged')
        backend.check_runtime();stage='write';published=False
        try:
            row_bytes=_json_bytes(rows,self.settings.max_file_bytes)
            missing=[];parent=path.parent
            while not parent.exists():missing.append(parent);parent=parent.parent
            for directory in reversed(missing):directory.mkdir(mode=0o700)
            pending=path.parent/('.pending-'+uuid.uuid4().hex);pending.mkdir(mode=0o700)
            if header['native_state']=='indexed':backend.build_native(pending,records,self.config)
            self.bundles._write_file(pending/'rows.json',row_bytes)
            names={'rows.json'}|(set(backend.NATIVE_FILES) if header['native_state']=='indexed' else set())
            if {p.name for p in pending.iterdir()}!=names:raise StorageError('bm25_index_incomplete')
            payloads=self._payloads(pending,sorted(names))
            for name in names:
                file=pending/name
                file.chmod(0o600)
                fd=os.open(file,os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
                try:os.fsync(fd)
                finally:os.close(fd)
            marker=dict(header,files={name:dict(bytes=len(value),sha256=_digest(value)) for name,value in payloads.items()})
            encoded=_json_bytes(marker,self.settings.max_manifest_bytes)
            if len(encoded)+sum(map(len,payloads.values()))>self.settings.max_bundle_bytes:raise StorageError('bm25_limit_exceeded')
            self.bundles._write_file(pending/'ready.json',encoded)
            self._load_index(pending,header,rows,records)
            self.bundles._sync_directory(pending);stage='publish'
            if path.exists() or path.is_symlink():raise StorageError('bm25_publish_failed')
            os.rename(pending,path);published=True;self.bundles._sync_directory(path.parent)
            return self._receipt(header,'ready')
        except StorageError:raise
        except Exception:
            raise StorageError('bm25_publish_uncertain' if published else
                               'bm25_publish_failed' if stage=='publish' else 'bm25_write_failed') from None
