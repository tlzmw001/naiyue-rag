"""Strict source-bearing Dense results; affine scores are not confidence."""
from dataclasses import dataclass
import math
from .types import Chunk
from .query_preparation import PreparedQuery


def _invalid():raise ValueError('query_invalid_request') from None


@dataclass(frozen=True,repr=False)
class DenseHit:
    rank:int
    chunk:Chunk
    distance:float
    score:float

    def __post_init__(self):
        try:
            if type(self.rank) is not int or self.rank<=0 or type(self.chunk) is not Chunk or \
                    any(type(v) not in (int,float) or not math.isfinite(v) for v in (self.distance,self.score)) or \
                    self.score!=max(0.,1-self.distance/2):raise ValueError()
            object.__setattr__(self,'chunk',Chunk.from_dict(self.chunk.to_dict()))
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return dict(rank=self.rank,chunk=self.chunk.to_dict(),distance=self.distance,score=self.score)

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            return cls(data['rank'],Chunk.from_dict(data['chunk']),data['distance'],data['score'])
        except Exception:_invalid()


@dataclass(frozen=True,repr=False)
class DenseResult:
    prepared:PreparedQuery
    top_k:int
    hits:list
    score_kind='chroma_cosine_affine_v1'

    def __post_init__(self):
        try:
            if type(self.prepared) is not PreparedQuery or type(self.top_k) is not int or self.top_k<=0 or \
                    type(self.hits) is not list or any(type(h) is not DenseHit for h in self.hits):raise ValueError()
            prepared=PreparedQuery.from_dict(self.prepared.to_dict());hits=[DenseHit.from_dict(h.to_dict()) for h in self.hits]
            if len(hits)!=(min(self.top_k,len(prepared.chunk_ids)) if prepared.status=='ready' else 0):raise ValueError()
            ids=[h.chunk.id for h in hits]
            if len(set(ids))!=len(ids) or any(h.rank!=i or h.chunk.id not in prepared.chunk_ids or \
                    h.chunk.source_ref not in prepared.document_ids for i,h in enumerate(hits,1)):raise ValueError()
            if [(h.distance,h.chunk.id) for h in hits]!=sorted((h.distance,h.chunk.id) for h in hits):raise ValueError()
            object.__setattr__(self,'prepared',prepared);object.__setattr__(self,'hits',hits)
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return dict(prepared=self.prepared.to_dict(),top_k=self.top_k,hits=[h.to_dict() for h in self.hits],score_kind=self.score_kind)

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!={'prepared','top_k','hits','score_kind'} or \
                    data['score_kind']!=cls.score_kind or type(data['hits']) is not list:raise ValueError()
            return cls(PreparedQuery.from_dict(data['prepared']),data['top_k'],[DenseHit.from_dict(h) for h in data['hits']])
        except Exception:_invalid()
