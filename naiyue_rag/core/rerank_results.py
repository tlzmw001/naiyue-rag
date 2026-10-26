"""Candidate IDs, original source and independently accounted rerank results."""
import copy
from dataclasses import dataclass
from .hybrid_results import HybridResult
from .rerank_settings import RerankSettings
from ..reranking.report import validate_report,validate_scores


def ranked_hits(hybrid,scores,top_k):
    by_id={s['passage_id']:s['score'] for s in scores}
    ordered=sorted(hybrid.hits,key=lambda h:-by_id[h.chunk.id]) if scores else hybrid.hits
    return [dict(rank=i,chunk_id=h.chunk.id,score=by_id.get(h.chunk.id)) for i,h in enumerate(ordered[:top_k],1)]


@dataclass(frozen=True,repr=False)
class RerankResult:
    hybrid:HybridResult
    settings:RerankSettings
    provider:str
    model:str|None
    scores:list
    hits:list
    report:dict

    def __post_init__(self):
        try:
            if type(self.hybrid) is not HybridResult or type(self.settings) is not RerankSettings:raise ValueError()
            hybrid=HybridResult.from_dict(self.hybrid.to_dict());cfg=RerankSettings.from_dict(self.settings.to_dict())
            report=copy.deepcopy(self.report);validate_report(report)
            if type(self.provider) is not str or self.provider not in ('none','llm','cross_encoder'):raise ValueError()
            if cfg.enabled:
                if self.provider=='none' or type(self.model) is not str or not self.model.strip():raise ValueError()
                validate_scores(self.scores,[h.chunk.id for h in hybrid.hits])
                if report['status']!=('success' if hybrid.hits else 'empty'):raise ValueError()
            elif self.provider!='none' or self.model is not None or self.scores!=[] or report['status']!='disabled':raise ValueError()
            if report['status'] in ('empty','disabled') and (report['attempted_requests'] or report['usage'] is not None):raise ValueError()
            hits=ranked_hits(hybrid,self.scores,cfg.top_k)
            if type(self.hits) is not list or self.hits!=hits:raise ValueError()
            for hit in self.hits:
                if type(hit) is not dict or set(hit)!={'rank','chunk_id','score'} or type(hit['rank']) is not int:raise ValueError()
                if hit['score'] is not None and type(hit['score']) not in (int,float):raise ValueError()
            for k,v in [('hybrid',hybrid),('settings',cfg),('scores',copy.deepcopy(self.scores)),('hits',hits),('report',report)]:
                object.__setattr__(self,k,v)
        except Exception:raise ValueError('rerank_invalid_output') from None

    def to_dict(self):
        self.__post_init__()
        return dict(hybrid=self.hybrid.to_dict(),settings=self.settings.to_dict(),provider=self.provider,model=self.model,
                    scores=copy.deepcopy(self.scores),hits=copy.deepcopy(self.hits),report=copy.deepcopy(self.report))

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            return cls(HybridResult.from_dict(data['hybrid']),RerankSettings.from_dict(data['settings']),
                data['provider'],data['model'],data['scores'],data['hits'],data['report'])
        except Exception:raise ValueError('rerank_invalid_output') from None
