"""A source-bound RRF join and its strict cross-field result invariants."""
import copy
from dataclasses import dataclass
import math
from .types import Chunk
from .dense_results import DenseHit,DenseResult
from .sparse_results import SparseHit,SparseResult
from .hybrid_settings import HybridSettings
from .query_preparation import PreparedQuery
from .trace_context import validate_trace_report


def _invalid():raise ValueError('query_invalid_request') from None


@dataclass(frozen=True,repr=False)
class FusedHit:
    rank:int
    chunk:Chunk
    score:float
    dense_rank:int|None
    sparse_rank:int|None

    def __post_init__(self):
        try:
            if type(self.rank) is not int or self.rank<=0 or type(self.chunk) is not Chunk or \
                    type(self.score) not in (int,float) or not math.isfinite(self.score) or self.score<=0:raise ValueError()
            ranks=(self.dense_rank,self.sparse_rank)
            if all(r is None for r in ranks) or any(r is not None and (type(r) is not int or r<=0) for r in ranks):raise ValueError()
            object.__setattr__(self,'chunk',Chunk.from_dict(self.chunk.to_dict()))
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return dict(rank=self.rank,chunk=self.chunk.to_dict(),score=self.score,dense_rank=self.dense_rank,sparse_rank=self.sparse_rank)

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            return cls(data['rank'],Chunk.from_dict(data['chunk']),data['score'],data['dense_rank'],data['sparse_rank'])
        except Exception:_invalid()


def fused_hits(dense,sparse,k,top_k):
    """Shared arithmetic for producing the join and checking its serialized contract."""
    if type(k) is not int or k<=0 or type(top_k) is not int or top_k<=0:_invalid()
    scores={};chunks={};ranks={}
    for label,hits in [('dense',dense),('sparse',sparse)]:
        for hit in hits:
            uid=hit.chunk.id
            if uid in chunks and chunks[uid].to_dict()!=hit.chunk.to_dict():_invalid()
            chunks[uid]=hit.chunk;scores[uid]=scores.get(uid,0.)+1/(k+hit.rank)
            ranks.setdefault(uid,{})[label]=hit.rank
    order=sorted(scores,key=lambda uid:(-scores[uid],uid))[:top_k]
    return [FusedHit(i,chunks[uid],scores[uid],ranks[uid].get('dense'),ranks[uid].get('sparse')) for i,uid in enumerate(order,1)]


@dataclass(frozen=True,repr=False)
class HybridResult:
    prepared:PreparedQuery
    settings:HybridSettings
    dense_hits:list
    sparse_hits:list
    hits:list
    trace_report:dict

    def __post_init__(self):
        try:
            if type(self.prepared) is not PreparedQuery or type(self.settings) is not HybridSettings or \
                    type(self.hits) is not list or any(type(h) is not FusedHit for h in self.hits):raise ValueError()
            prep=PreparedQuery.from_dict(self.prepared.to_dict());cfg=HybridSettings.from_dict(self.settings.to_dict())
            dense=DenseResult(prep,cfg.dense_top_k,self.dense_hits).hits
            sparse=SparseResult(prep,cfg.sparse_top_k,cfg.bm25_statistics_scope,self.sparse_hits).hits
            hits=[FusedHit.from_dict(h.to_dict()) for h in self.hits]
            expected=fused_hits(dense,sparse,cfg.rrf_k,cfg.fusion_top_k)
            if [h.to_dict() for h in hits]!=[h.to_dict() for h in expected]:raise ValueError()
            trace=copy.deepcopy(self.trace_report);validate_trace_report(trace)
            originals=prep.trace_report['stages'];stages=trace['stages']
            if trace['status']!='success' or [s['stage'] for s in stages]!=[s['stage'] for s in originals]+['dense','sparse','fusion']:
                raise ValueError()
            for new,old in zip(stages,originals):
                if new['data']!=old['data'] or new['elapsed_ms']!=old['elapsed_ms']:raise ValueError()
            for entry,hits_ in zip(stages[-3:-1],(dense,sparse),strict=True):
                if entry['data']!=dict(eligible_count=len(prep.chunk_ids),candidate_count=len(hits_)):raise ValueError()
            union={h.chunk.id for h in dense+sparse}
            if stages[-1]['data']!=dict(union_count=len(union),candidate_count=len(hits)):raise ValueError()
            for key,value in [('prepared',prep),('settings',cfg),('dense_hits',dense),('sparse_hits',sparse),('hits',hits),('trace_report',trace)]:
                object.__setattr__(self,key,value)
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return dict(prepared=self.prepared.to_dict(),settings=self.settings.to_dict(),dense_hits=[h.to_dict() for h in self.dense_hits],
            sparse_hits=[h.to_dict() for h in self.sparse_hits],hits=[h.to_dict() for h in self.hits],trace_report=copy.deepcopy(self.trace_report))

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            return cls(PreparedQuery.from_dict(data['prepared']),HybridSettings.from_dict(data['settings']),
                [DenseHit.from_dict(h) for h in data['dense_hits']],[SparseHit.from_dict(h) for h in data['sparse_hits']],
                [FusedHit.from_dict(h) for h in data['hits']],data['trace_report'])
        except Exception:_invalid()
