"""Bounded private artifact publication and strict read-only reload; local serial IO."""
from dataclasses import dataclass,asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from ..core.errors import StorageError,SettingsError
from ..core.storage_settings import validate_storage_settings
from .artifact_bundle import IndexBundle
from .artifact_bundle_v2 import IndexBundleV2
from .bundle_encoding import bundle_encoding

FILES=('documents.json','chunks.json','relations.json','encoding.json')
MANIFEST_FIELDS={'schema_version','status','bundle_id','knowledge_base_id','document_count','chunk_count',
                 'model_space_id','representation_id','tokenizer_id','source_fingerprint','files'}
ENCODING_FIELDS={'encoding_settings','ingestion_settings','encoding_result','preparation_diagnostics'}
ENCODING_FIELDS_V2={'encoding_settings','ingestion_settings','encoding_snapshot','encoding_summary','preparation_diagnostics'}


def _json_bytes(value,limit,*,newline=True):
    out=bytearray()
    encoder=json.JSONEncoder(ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    for part in encoder.iterencode(value):
        part=part.encode('utf-8')
        if len(out)+len(part)+int(newline)>limit:raise StorageError('bundle_limit_exceeded')
        out.extend(part)
    if newline:out.extend(b'\n')
    return bytes(out)


def _digest(value):return hashlib.sha256(value).hexdigest()


def _hash(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None


def _parse(raw,*,canonical=True):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError()
            result[key]=value
        return result
    def reject(value):raise ValueError()
    try:
        value=json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=reject)
        if canonical and _json_bytes(value,len(raw))!=raw:raise ValueError()
        return value
    except Exception:raise StorageError('bundle_integrity_failed') from None


@dataclass(frozen=True)
class StoredBundle:
    bundle_id:str
    status:str
    document_count:int
    chunk_count:int
    model_space_id:str
    representation_id:str
    tokenizer_id:str

    def to_dict(self):return asdict(self)


class BundleStore:
    """One configured KB; no source reads, implicit model calls, repair or active index."""
    def __init__(self,settings):
        validate_storage_settings(settings)
        self.settings=settings

    def _path(self,bundle_id=None,*,namespace='artifacts',error_code='bundle_path_invalid'):
        try:
            validate_storage_settings(self.settings)
            if namespace not in ('artifacts','vectors','bm25'):raise StorageError(error_code)
            root=Path(self.settings.storage_root)/_digest(self.settings.knowledge_base_id.encode('utf-8'))/namespace
            target=root if bundle_id is None else root/bundle_id
            for part in [target,*target.parents]:
                if part.is_symlink() or part.exists() and not part.is_dir():raise StorageError(error_code)
            return target
        except StorageError:raise
        except Exception:raise StorageError(error_code) from None

    def _check_counts(self,documents,chunks):
        if type(documents) is not list or type(chunks) is not list:raise StorageError('invalid_index_bundle')
        if len(documents)>self.settings.max_documents or len(chunks)>self.settings.max_chunks:raise StorageError('bundle_limit_exceeded')

    def _materialize(self,bundle):
        if type(bundle) not in (IndexBundle,IndexBundleV2):raise StorageError('invalid_index_bundle')
        self._check_counts(bundle.documents,bundle.chunks)
        raw=bundle.to_dict()
        if raw['knowledge_base_id']!=self.settings.knowledge_base_id:raise StorageError('bundle_scope_mismatch')
        data={name:raw[name.removesuffix('.json')] for name in FILES[:3]}
        fields=ENCODING_FIELDS if type(bundle) is IndexBundle else ENCODING_FIELDS_V2
        data['encoding.json']={key:raw[key] for key in fields}
        encoded={name:_json_bytes(value,self.settings.max_file_bytes) for name,value in data.items()}
        if sum(map(len,encoded.values()))>self.settings.max_bundle_bytes:raise StorageError('bundle_limit_exceeded')
        result=bundle_encoding(bundle)
        header=dict(schema_version=1 if type(bundle) is IndexBundle else 2,status='ready',knowledge_base_id=bundle.knowledge_base_id,
            document_count=len(bundle.documents),chunk_count=len(bundle.chunks),model_space_id=result.model_space_id,
            representation_id=result.representation_id,tokenizer_id=result.tokenizer_id,
            source_fingerprint=bundle.relations['source_fingerprint'],
            files={name:dict(bytes=len(value),sha256=_digest(value)) for name,value in encoded.items()})
        uid=_digest(_json_bytes(header,self.settings.max_manifest_bytes,newline=False))
        header['bundle_id']=uid
        encoded['manifest.json']=_json_bytes(header,self.settings.max_manifest_bytes)
        if sum(map(len,encoded.values()))>self.settings.max_bundle_bytes:raise StorageError('bundle_limit_exceeded')
        return header,encoded

    def _write_file(self,path,payload):
        fd=None
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            stream=os.fdopen(fd,'wb');fd=None
            with stream:
                written=stream.write(payload)
                if type(written) is not int or written!=len(payload):raise OSError()
                stream.flush();os.fsync(stream.fileno())
        finally:
            if fd is not None:os.close(fd)

    def _read_file(self,path,limit):
        fd=None
        try:
            if path.is_symlink():raise StorageError('bundle_path_invalid')
            fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
            stream=os.fdopen(fd,'rb');fd=None
            with stream:
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):raise StorageError('bundle_path_invalid')
                if info.st_size>limit:raise StorageError('bundle_limit_exceeded')
                raw=stream.read(limit+1)
                if len(raw)>limit:raise StorageError('bundle_limit_exceeded')
                return raw
        finally:
            if fd is not None:os.close(fd)

    def _sync_directory(self,path):
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))
        try:os.fsync(fd)
        finally:os.close(fd)

    def _receipt(self,header,status):
        return StoredBundle(header['bundle_id'],status,header['document_count'],header['chunk_count'],
                            header['model_space_id'],header['representation_id'],header['tokenizer_id'])

    def save(self,bundle):
        published=False;stage='validate'
        try:
            self._path();header,encoded=self._materialize(bundle);target=self._path(header['bundle_id'])
            if target.exists():
                existing=self.load(header['bundle_id'])
                actual,_=self._materialize(existing)
                if actual!=header:raise StorageError('bundle_integrity_failed')
                return self._receipt(header,'unchanged')
            stage='write';root=self._path();missing=[];parent=root
            # Path.mkdir(parents=True) would create intermediate directories with default permissions.
            while not parent.exists():
                missing.append(parent);parent=parent.parent
            for directory in reversed(missing):directory.mkdir(mode=0o700)
            pending=root/('.pending-'+uuid.uuid4().hex);pending.mkdir(mode=0o700)
            for name,payload in encoded.items():self._write_file(pending/name,payload)
            self._sync_directory(pending);stage='publish'
            # The local serial writer never overwrites an existing destination, even an incomplete one.
            if target.exists() or target.is_symlink():raise StorageError('bundle_publish_failed')
            os.rename(pending,target);published=True
            self._sync_directory(root)
            return self._receipt(header,'ready')
        except StorageError:raise
        except Exception:
            code='bundle_publish_uncertain' if published else 'bundle_publish_failed' if stage=='publish' else 'bundle_write_failed' if stage=='write' else 'invalid_index_bundle'
            raise StorageError(code) from None

    def _manifest(self,raw,uid):
        header=_parse(raw)
        try:
            if type(header) is not dict or set(header)!=MANIFEST_FIELDS:raise ValueError()
            if type(header['schema_version']) is not int or header['schema_version'] not in (1,2) or header['status']!='ready':raise ValueError()
            if header['bundle_id']!=uid or header['knowledge_base_id']!=self.settings.knowledge_base_id:raise ValueError()
            for key in ['model_space_id','representation_id','tokenizer_id','source_fingerprint']:
                if not _hash(header[key]):raise ValueError()
            for key,limit in [('document_count',self.settings.max_documents),('chunk_count',self.settings.max_chunks)]:
                if type(header[key]) is not int or header[key]<0:raise ValueError()
                if header[key]>limit:raise StorageError('bundle_limit_exceeded')
            files=header['files']
            if type(files) is not dict or set(files)!=set(FILES):raise ValueError()
            for descriptor in files.values():
                if type(descriptor) is not dict or set(descriptor)!={'bytes','sha256'}:raise ValueError()
                if type(descriptor['bytes']) is not int or descriptor['bytes']<=0 or not _hash(descriptor['sha256']):raise ValueError()
                if descriptor['bytes']>self.settings.max_file_bytes:raise StorageError('bundle_limit_exceeded')
            if sum(row['bytes'] for row in files.values())+len(raw)>self.settings.max_bundle_bytes:raise StorageError('bundle_limit_exceeded')
            unsigned={k:v for k,v in header.items() if k!='bundle_id'}
            if _digest(_json_bytes(unsigned,self.settings.max_manifest_bytes,newline=False))!=uid:raise ValueError()
            return header
        except StorageError:raise
        except Exception:raise StorageError('bundle_integrity_failed') from None

    def load(self,bundle_id):
        if not _hash(bundle_id):raise StorageError('invalid_bundle_id')
        try:
            root=self._path(bundle_id)
            if not root.exists():raise StorageError('bundle_not_found')
            names={p.name for p in root.iterdir()}
            if not set(FILES)|{'manifest.json'}<=names:raise StorageError('bundle_incomplete')
            if names!=set(FILES)|{'manifest.json'}:raise StorageError('bundle_integrity_failed')
            header=self._manifest(self._read_file(root/'manifest.json',self.settings.max_manifest_bytes),bundle_id)
            data={}
            for name in FILES:
                raw=self._read_file(root/name,self.settings.max_file_bytes);descriptor=header['files'][name]
                if len(raw)!=descriptor['bytes'] or _digest(raw)!=descriptor['sha256']:raise StorageError('bundle_integrity_failed')
                data[name]=_parse(raw)
            self._check_counts(data['documents.json'],data['chunks.json'])
            encoding=data['encoding.json']
            fields=ENCODING_FIELDS if header['schema_version']==1 else ENCODING_FIELDS_V2
            kind=IndexBundle if header['schema_version']==1 else IndexBundleV2
            if type(encoding) is not dict or set(encoding)!=fields:raise StorageError('bundle_integrity_failed')
            bundle=kind.from_dict(dict(knowledge_base_id=self.settings.knowledge_base_id,
                documents=data['documents.json'],chunks=data['chunks.json'],relations=data['relations.json'],**encoding))
            actual,_=self._materialize(bundle)
            if actual!=header:raise StorageError('bundle_integrity_failed')
            return bundle
        except StorageError:raise
        except Exception:raise StorageError('bundle_read_failed') from None
