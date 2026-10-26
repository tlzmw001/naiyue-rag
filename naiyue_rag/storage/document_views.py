"""Metadata-only results and pure projections; an active binding is not a health certificate."""
from dataclasses import dataclass,asdict
import json
from pathlib import PurePosixPath
import re
from ..core.errors import StorageError
from .bundle_store import _hash,_digest
from .version_types import ActiveVersion


def _invalid():raise StorageError('document_invalid_request') from None


def _fields(data,cls):
    if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):_invalid()


def _valid_document_id(value):
    return type(value) is str and re.fullmatch(r'doc-[0-9a-f]{64}',value) is not None


def _active(value):
    if value is None:return None
    if type(value) is not ActiveVersion:_invalid()
    return ActiveVersion.from_dict(value.to_dict())


def _bound(info,active):
    raw=json.dumps([active.version.knowledge_base_id,info.source_path],ensure_ascii=False,separators=(',',':'))
    if info.document_id!='doc-'+_digest(raw.encode('utf-8')) or active.version.document_count==0 or \
            info.chunk_count>active.version.chunk_count:_invalid()


@dataclass(frozen=True,repr=False)
class DocumentInfo:
    document_id:str
    source_path:str
    source_sha256:str
    size_bytes:int
    chunk_count:int

    def __post_init__(self):
        try:
            if not _valid_document_id(self.document_id) or not _hash(self.source_sha256):raise ValueError()
            path=self.source_path
            if type(path) is not str or not path or '\x00' in path or '\\' in path:raise ValueError()
            path.encode('utf-8');given=PurePosixPath(path)
            if given.is_absolute() or '..' in given.parts or re.match(r'^[A-Za-z]:',path) or \
                    given.as_posix()!=path or given.suffix.lower()!='.md':raise ValueError()
            if any(type(v) is not int or v<0 for v in (self.size_bytes,self.chunk_count)):raise ValueError()
            if self.size_bytes==0 and self.chunk_count:raise ValueError()
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        _fields(data,cls)
        return cls(**dict(data))


@dataclass(frozen=True,repr=False)
class DocumentList:
    active:ActiveVersion|None
    documents:list

    def __post_init__(self):
        try:
            selected=_active(self.active)
            if type(self.documents) is not list or any(type(d) is not DocumentInfo for d in self.documents):raise ValueError()
            items=[DocumentInfo.from_dict(d.to_dict()) for d in self.documents]
            if selected is None:
                if items:raise ValueError()
            else:
                if len(items)!=selected.version.document_count or sum(d.chunk_count for d in items)!=selected.version.chunk_count:raise ValueError()
                for item in items:_bound(item,selected)
            keys=[(d.source_path,d.document_id) for d in items]
            if keys!=sorted(keys) or len({d.document_id for d in items})!=len(items) or \
                    len({d.source_path for d in items})!=len(items):raise ValueError()
            object.__setattr__(self,'active',selected);object.__setattr__(self,'documents',items)
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return dict(active=None if self.active is None else self.active.to_dict(),
                    documents=[d.to_dict() for d in self.documents])

    @classmethod
    def from_dict(cls,data):
        _fields(data,cls)
        try:
            if type(data['documents']) is not list:raise ValueError()
            return cls(None if data['active'] is None else ActiveVersion.from_dict(data['active']),
                       [DocumentInfo.from_dict(d) for d in data['documents']])
        except Exception:_invalid()


@dataclass(frozen=True,repr=False)
class DocumentDetail:
    active:ActiveVersion|None
    document:DocumentInfo|None
    chunk_ids:list

    def __post_init__(self):
        try:
            selected=_active(self.active);item=self.document
            if type(self.chunk_ids) is not list or any(type(uid) is not str or
                    re.fullmatch(r'unit-[0-9a-f]{64}',uid) is None for uid in self.chunk_ids):raise ValueError()
            ids=list(self.chunk_ids)
            if len(set(ids))!=len(ids):raise ValueError()
            if item is None:
                if ids:raise ValueError()
            else:
                if selected is None or type(item) is not DocumentInfo:raise ValueError()
                item=DocumentInfo.from_dict(item.to_dict());_bound(item,selected)
                if len(ids)!=item.chunk_count:raise ValueError()
            object.__setattr__(self,'active',selected);object.__setattr__(self,'document',item)
            object.__setattr__(self,'chunk_ids',ids)
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return dict(active=None if self.active is None else self.active.to_dict(),
                    document=None if self.document is None else self.document.to_dict(),chunk_ids=list(self.chunk_ids))

    @classmethod
    def from_dict(cls,data):
        _fields(data,cls)
        try:return cls(None if data['active'] is None else ActiveVersion.from_dict(data['active']),
                       None if data['document'] is None else DocumentInfo.from_dict(data['document']),data['chunk_ids'])
        except Exception:_invalid()


def _inventory(bundle):
    documents={};groups={};seen=set()
    for doc in bundle.documents:
        if doc.id in documents:raise ValueError()
        documents[doc.id]=doc;groups[doc.id]=[]
    for chunk in bundle.chunks:
        if chunk.source_ref not in groups or chunk.id in seen:raise ValueError()
        seen.add(chunk.id);groups[chunk.source_ref].append(chunk)
    infos={uid:DocumentInfo(uid,doc.metadata['source_path'],doc.metadata['source_sha256'],
                           doc.metadata['size_bytes'],len(groups[uid])) for uid,doc in documents.items()}
    return infos,groups


def project_list(active,bundle):
    try:
        if active is None:
            if bundle is not None:raise ValueError()
            return DocumentList(None,[])
        infos,_=_inventory(bundle)
        return DocumentList(active,sorted(infos.values(),key=lambda d:(d.source_path,d.document_id)))
    except Exception:raise StorageError('document_integrity_failed') from None


def project_detail(active,bundle,document_id):
    try:
        if active is None:
            if bundle is not None:raise ValueError()
            return DocumentDetail(None,None,[])
        infos,groups=_inventory(bundle)
        chunks=sorted(groups.get(document_id,[]),key=lambda c:(c.start_offset,c.end_offset,c.id))
        return DocumentDetail(active,infos.get(document_id),[c.id for c in chunks])
    except Exception:raise StorageError('document_integrity_failed') from None
