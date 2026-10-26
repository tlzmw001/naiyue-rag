"""Positive keyword hits with an explicit, noninterchangeable statistics mode."""
from dataclasses import dataclass
import math
from .types import Chunk
from .query_preparation import PreparedQuery


def _invalid():raise ValueError('query_invalid_request') from None


@dataclass(frozen=True,repr=False)
class SparseHit:
    rank:int
    chunk:Chunk
    score:float

    def __post_init__(self):
        try:
            if type(self.rank) is not int or self.rank<=0 or type(self.chunk) is not Chunk or \
                    type(self.score) not in (int,float) or not math.isfinite(self.score) or self.score<=0:raise ValueError()
            object.__setattr__(self,'chunk',Chunk.from_dict(self.chunk.to_dict()))
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return dict(rank=self.rank,chunk=self.chunk.to_dict(),score=self.score)

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            return cls(data['rank'],Chunk.from_dict(data['chunk']),data['score'])
        except Exception:_invalid()


@dataclass(frozen=True,repr=False)
class SparseResult:
    prepared:PreparedQuery
    top_k:int
    statistics_scope:str
    hits:list

    @property
    def score_kind(self):return 'bm25s_lucene_'+self.statistics_scope+'_v1'

    def __post_init__(self):
        try:
            if type(self.prepared) is not PreparedQuery or type(self.top_k) is not int or self.top_k<=0 or \
                    type(self.statistics_scope) is not str or self.statistics_scope not in ('global','scope') or \
                    type(self.hits) is not list or any(type(h) is not SparseHit for h in self.hits):raise ValueError()
            prepared=PreparedQuery.from_dict(self.prepared.to_dict());hits=[SparseHit.from_dict(h.to_dict()) for h in self.hits]
            if len(hits)>self.top_k or prepared.status!='ready' and hits:raise ValueError()
            ids=[h.chunk.id for h in hits]
            if len(set(ids))!=len(ids) or any(h.rank!=i or h.chunk.id not in prepared.chunk_ids or \
                    h.chunk.source_ref not in prepared.document_ids for i,h in enumerate(hits,1)):raise ValueError()
            if [(-h.score,h.chunk.id) for h in hits]!=sorted((-h.score,h.chunk.id) for h in hits):raise ValueError()
            object.__setattr__(self,'prepared',prepared);object.__setattr__(self,'hits',hits)
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return dict(prepared=self.prepared.to_dict(),top_k=self.top_k,statistics_scope=self.statistics_scope,
                    hits=[h.to_dict() for h in self.hits],score_kind=self.score_kind)

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!={'prepared','top_k','statistics_scope','hits','score_kind'} or \
                    type(data['hits']) is not list:raise ValueError()
            result=cls(PreparedQuery.from_dict(data['prepared']),data['top_k'],data['statistics_scope'],
                       [SparseHit.from_dict(h) for h in data['hits']])
            if result.score_kind!=data['score_kind']:raise ValueError()
            return result
        except Exception:_invalid()
