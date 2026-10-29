"""Source-bound Chroma indexes: serial publication, semantic audits, no active pointer."""
from .bundle_encoding import bundle_encoding
import copy
from dataclasses import dataclass,asdict
import math
import os
from pathlib import Path
import uuid
import numpy as np
from ..core.chroma_settings import ChromaSettings
from ..core.storage_settings import validate_storage_settings
from ..core.errors import StorageError
from .bundle_store import BundleStore,_digest,_json_bytes,_parse
from .chroma_backend import SDK_VERSION,call,open_collection
from .query_cache import cached_query_resource


@dataclass(frozen=True)
class VectorIndexReceipt:
    schema_version:int
    status:str
    index_id:str
    bundle_id:str
    knowledge_base_id:str
    document_count:int
    chunk_count:int
    verified_count:int
    model_space_id:str
    representation_id:str
    tokenizer_id:str
    dimensions:int
    sdk_version:str

    def to_dict(self):return asdict(self)


class ChromaStore:
    """Read business records only; native internal maintenance may still write files."""
    def __init__(self,storage_settings,chroma_settings,*,project_root):
        validate_storage_settings(storage_settings)
        if type(chroma_settings) is not ChromaSettings:raise StorageError('chroma_invalid_request')
        self.settings=storage_settings;self.config=ChromaSettings.from_dict(chroma_settings.to_dict())
        self.bundles=BundleStore(storage_settings)
        try:
            self.project_root=Path(project_root).resolve(strict=True)
            if not self.project_root.is_dir():raise ValueError()
        except Exception:raise StorageError('chroma_path_invalid') from None

    def _path(self,index_id):
        return self.bundles._path(index_id,namespace='vectors',error_code='chroma_path_invalid')

    @cached_query_resource
    def _prepare(self,bundle_id):
        bundle=self.bundles.load(bundle_id);result=bundle_encoding(bundle)
        policy=dict(schema_version=1,bundle_id=bundle_id,collection_name=self.config.collection_name,
                    sdk_version=SDK_VERSION,storage_policy='explicit-cosine-v1')
        index_id=_digest(_json_bytes(policy,self.settings.max_manifest_bytes,newline=False))
        chunks={c.id:c for c in bundle.chunks};rows={}
        try:
            for record in result.records:
                with np.errstate(over='raise',invalid='raise'):
                    vector=np.asarray(record.dense_vector,dtype=np.float32)
                if not np.isfinite(vector).all() or math.hypot(*vector)==0:raise ValueError()
                item=record.input
                meta=dict(bundle_id=bundle_id,document_id=item.source_document_id,source_sha256=item.source_sha256,
                    embedding_text_sha256=item.embedding_text_sha256,retrieval_text_sha256=item.retrieval_text_sha256,
                    chunk_sha256=_digest(_json_bytes(chunks[item.item_id].to_dict(),self.settings.max_file_bytes)))
                rows[item.item_id]=dict(vector=list(record.dense_vector),text=item.retrieval_text,metadata=meta)
        except StorageError:raise
        except Exception:raise StorageError('chroma_integrity_failed') from None
        identity=dict(bundle_id=bundle_id,knowledge_base_id=bundle.knowledge_base_id,model_space_id=result.model_space_id,
            representation_id=result.representation_id,tokenizer_id=result.tokenizer_id,dimensions=result.dimensions)
        header=dict(schema_version=1,status='ready',index_id=index_id,**identity,document_count=len(bundle.documents),
            chunk_count=len(rows),verified_count=len(rows),sdk_version=SDK_VERSION,
            source_fingerprint=bundle.relations['source_fingerprint'],
            records_sha256=_digest(_json_bytes(rows,self.settings.max_bundle_bytes)))
        return self._path(index_id),header,identity,rows,chunks

    def _receipt(self,header,status):
        return VectorIndexReceipt(**{key:status if key=='status' else header[key]
                                     for key in VectorIndexReceipt.__dataclass_fields__})

    def _native_files(self,path,*,secure=False):
        if path.is_symlink() or not path.is_dir():raise StorageError('chroma_path_invalid')
        files=[]
        for child in path.rglob('*'):
            if child.is_symlink() or not (child.is_file() or child.is_dir()):raise StorageError('chroma_path_invalid')
            if secure:child.chmod(0o700 if child.is_dir() else 0o600)
            if child.is_file():files.append(str(child.relative_to(path)))
        if secure:path.chmod(0o700)
        return sorted(files)

    def _marker(self,path,expected):
        if not path.exists():raise StorageError('chroma_index_not_found')
        try:
            marker=_parse(self.bundles._read_file(path/'ready.json',self.settings.max_manifest_bytes))
            if type(marker) is not dict or set(marker)!=set(expected)|{'configuration','native_files'}:raise ValueError()
            actual={k:marker[k] for k in expected}
            if _json_bytes(actual,self.settings.max_manifest_bytes)!=_json_bytes(expected,self.settings.max_manifest_bytes):
                raise ValueError()
            files=marker['native_files']
            if type(files) is not list or not files or any(type(f) is not str for f in files):raise ValueError()
            if len(set(files))!=len(files) or not set(files)<=set(self._native_files(path/'chroma')):raise ValueError()
            return marker
        except StorageError as error:
            if error.code=='chroma_path_invalid':raise
            raise StorageError('chroma_index_incomplete') from None
        except Exception:raise StorageError('chroma_index_incomplete') from None

    def _groups(self,ids):
        for start in range(0,len(ids),self.config.batch_size):yield ids[start:start+self.config.batch_size]

    def _check_rows(self,collection,ids,rows):
        for group in self._groups(ids):
            raw=call(collection.get,ids=group,include=['embeddings','documents','metadatas'])
            try:
                columns=[raw[k] for k in ['ids','embeddings','documents','metadatas']]
                if any(len(c)!=len(group) for c in columns) or set(columns[0])!=set(group):raise ValueError()
                if len(set(columns[0]))!=len(group):raise ValueError()
                for uid,vector,text,meta in zip(*columns,strict=True):
                    expected=rows[uid];value=np.asarray(vector)
                    if text!=expected['text'] or _json_bytes(meta,self.settings.max_file_bytes)!=_json_bytes(expected['metadata'],self.settings.max_file_bytes):raise ValueError()
                    if value.shape!=(len(expected['vector']),) or not np.isfinite(value).all() or \
                            not np.allclose(value,np.asarray(expected['vector'],dtype=np.float32),rtol=1e-6,atol=1e-8):raise ValueError()
            except StorageError:raise
            except Exception:raise StorageError('chroma_integrity_failed') from None

    def _audit_native(self,path,identity,rows,*,configuration=None):
        with open_collection(path/'chroma',self.project_root,self.config.collection_name,identity,self.config.batch_size) as collection:
            if configuration is not None and _json_bytes(collection.configuration,self.settings.max_manifest_bytes)!=_json_bytes(configuration,self.settings.max_manifest_bytes):
                raise StorageError('chroma_identity_mismatch')
            count=call(collection.count)
            if type(count) is not int or count!=len(rows):raise StorageError('chroma_integrity_failed')
            self._check_rows(collection,list(rows),rows)
            return copy.deepcopy(collection.configuration)

    def audit(self,bundle_id):
        path,header,identity,rows,_=self._prepare(bundle_id);marker=self._marker(path,header)
        self._audit_native(path,identity,rows,configuration=marker['configuration'])
        return self._receipt(header,'verified')

    def get_by_ids(self,bundle_id,ids):
        path,header,identity,rows,chunks=self._prepare(bundle_id)
        if type(ids) is not list or len(ids)>self.config.batch_size or any(type(i) is not str or i not in rows for i in ids) or len(set(ids))!=len(ids):
            raise StorageError('chroma_invalid_request')
        marker=self._marker(path,header)
        if not ids:return {}
        with open_collection(path/'chroma',self.project_root,self.config.collection_name,identity,self.config.batch_size) as collection:
            if _json_bytes(collection.configuration,self.settings.max_manifest_bytes)!=_json_bytes(marker['configuration'],self.settings.max_manifest_bytes):
                raise StorageError('chroma_identity_mismatch')
            self._check_rows(collection,ids,rows)
        return {uid:copy.deepcopy(chunks[uid]) for uid in ids}

    def query(self,bundle_id,query_vector,*,document_ids,top_k):
        from .chroma_query import query_index
        return query_index(self,bundle_id,query_vector,document_ids=document_ids,top_k=top_k)


class VectorUpserter(ChromaStore):
    """Only builds complete new versions; no updates to a published index."""
    def build(self,bundle_id):
        path,header,identity,rows,_=self._prepare(bundle_id)
        if path.exists():
            marker=self._marker(path,header)
            self._audit_native(path,identity,rows,configuration=marker['configuration'])
            return self._receipt(header,'unchanged')
        stage='write';published=False
        try:
            missing=[];parent=path.parent
            while not parent.exists():missing.append(parent);parent=parent.parent
            for directory in reversed(missing):directory.mkdir(mode=0o700)
            pending=path.parent/('.pending-'+uuid.uuid4().hex);pending.mkdir(mode=0o700)
            with open_collection(pending/'chroma',self.project_root,self.config.collection_name,identity,
                                 self.config.batch_size,create=True) as collection:
                for group in self._groups(list(rows)):
                    call(collection.upsert,code='chroma_write_failed',ids=group,
                         embeddings=[rows[i]['vector'] for i in group],documents=[rows[i]['text'] for i in group],
                         metadatas=[rows[i]['metadata'] for i in group])
                count=call(collection.count)
                if type(count) is not int or count!=len(rows):raise StorageError('chroma_integrity_failed')
                self._check_rows(collection,list(rows),rows)
            configuration=self._audit_native(pending,identity,rows)
            files=self._native_files(pending/'chroma',secure=True)
            marker=dict(header,configuration=configuration,native_files=files)
            self.bundles._write_file(pending/'ready.json',_json_bytes(marker,self.settings.max_manifest_bytes))
            self.bundles._sync_directory(pending);stage='publish'
            if path.exists() or path.is_symlink():raise StorageError('chroma_publish_failed')
            os.rename(pending,path);published=True;self.bundles._sync_directory(path.parent)
            return self._receipt(header,'ready')
        except StorageError:raise
        except Exception:
            raise StorageError('chroma_publish_uncertain' if published else
                               'chroma_publish_failed' if stage=='publish' else 'chroma_write_failed') from None
