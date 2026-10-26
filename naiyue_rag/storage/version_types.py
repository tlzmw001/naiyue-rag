"""Strict, payload-free descriptors binding three audited artifacts to one version."""
from dataclasses import dataclass,asdict
from ..core.chroma_settings import ChromaSettings
from ..core.bm25_settings import BM25Settings
from ..core.errors import StorageError
from .bundle_store import _hash,_digest,_json_bytes
from .chroma_backend import SDK_VERSION as CHROMA_VERSION
from .bm25_backend import SDK_VERSION as BM25_VERSION

MAX_REVISION=2**63-1


@dataclass(frozen=True,repr=False)
class IndexVersion:
    schema_version:int
    version_id:str
    knowledge_base_id:str
    bundle_id:str
    vector_index_id:str
    bm25_index_id:str
    document_count:int
    chunk_count:int
    source_fingerprint:str
    model_space_id:str
    representation_id:str
    tokenizer_id:str
    dimensions:int
    chroma_collection_name:str
    chroma_sdk_version:str
    bm25_k1:float
    bm25_b:float
    bm25_sdk_version:str

    def __post_init__(self):
        try:
            if type(self.schema_version) is not int or self.schema_version!=1:raise ValueError()
            for name in ('version_id','bundle_id','vector_index_id','bm25_index_id',
                         'source_fingerprint','model_space_id','representation_id','tokenizer_id'):
                if not _hash(getattr(self,name)):raise ValueError()
            kb=self.knowledge_base_id
            if type(kb) is not str or not kb.strip() or any(ord(c)<32 for c in kb):raise ValueError()
            kb.encode('utf-8')
            if any(type(v) is not int or v<0 for v in (self.document_count,self.chunk_count)):raise ValueError()
            if type(self.dimensions) is not int or self.dimensions<=0:raise ValueError()
            ChromaSettings(self.chroma_collection_name,1)
            bm25=BM25Settings(self.bm25_k1,self.bm25_b)
            object.__setattr__(self,'bm25_k1',bm25.k1);object.__setattr__(self,'bm25_b',bm25.b)
            if self.chroma_sdk_version!=CHROMA_VERSION or self.bm25_sdk_version!=BM25_VERSION:
                raise StorageError('catalog_schema_unsupported')
            raw=asdict(self);raw.pop('version_id')
            # No fixed manifest budget here: the catalog applies its configured bound.
            encoded=_json_bytes(raw,len(str(raw).encode('utf-8'))*6+1,newline=False)
            if _digest(encoded)!=self.version_id:raise StorageError('catalog_integrity_failed')
        except StorageError:raise
        except Exception:raise StorageError('catalog_invalid_request') from None

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):
            raise StorageError('catalog_invalid_request')
        try:return cls(**dict(data))
        except StorageError:raise
        except Exception:raise StorageError('catalog_invalid_request') from None


@dataclass(frozen=True,repr=False)
class ActiveVersion:
    revision:int
    version:IndexVersion

    def __post_init__(self):
        if type(self.revision) is not int or not 0<self.revision<=MAX_REVISION or type(self.version) is not IndexVersion:
            raise StorageError('catalog_invalid_request')
        self.version.__post_init__()

    def to_dict(self):
        self.__post_init__()
        return dict(revision=self.revision,version=self.version.to_dict())

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!={'revision','version'}:raise StorageError('catalog_invalid_request')
        return cls(data['revision'],IndexVersion.from_dict(data['version']))


@dataclass(frozen=True,repr=False)
class ActivationReceipt:
    status:str
    active:ActiveVersion

    def __post_init__(self):
        if type(self.status) is not str or self.status not in ('activated','unchanged') or type(self.active) is not ActiveVersion:
            raise StorageError('catalog_invalid_request')
        self.active.__post_init__()

    def to_dict(self):
        self.__post_init__()
        return dict(status=self.status,active=self.active.to_dict())

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!={'status','active'}:raise StorageError('catalog_invalid_request')
        return cls(data['status'],ActiveVersion.from_dict(data['active']))
