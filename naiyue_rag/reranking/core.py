"""The fixed pipeline controls budgets; providers can only score existing IDs."""
import time
from ..core.hybrid_results import HybridResult
from ..core.rerank_settings import RerankSettings
from ..core.rerank_results import RerankResult,ranked_hits
from .report import RerankError,new_report,validate_report,validate_scores


class CoreReranker:
    def __init__(self,settings,backend=None):
        if type(settings) is not RerankSettings:raise RerankError('rerank_invalid_input')
        self.settings=RerankSettings.from_dict(settings.to_dict());self.backend=backend
        if self.settings.enabled and (backend is None or getattr(backend,'provider',None) not in ('llm','cross_encoder') or
                type(getattr(backend,'model',None)) is not str or not backend.model.strip()):raise RerankError('rerank_invalid_input')

    def rerank(self,hybrid):
        started=time.monotonic();report=new_report();encoding=None
        try:
            if type(hybrid) is not HybridResult:raise RerankError('rerank_invalid_input')
            hybrid=HybridResult.from_dict(hybrid.to_dict());encoding=hybrid.prepared.encoding.report if hybrid.prepared.encoding else None
            cfg=RerankSettings.from_dict(self.settings.to_dict());scores=[]
            provider=self.backend.provider if cfg.enabled else 'none';model=self.backend.model if cfg.enabled else None
            if not cfg.enabled:report['status']='disabled'
            elif not hybrid.hits:report['status']='empty'
            else:
                query=hybrid.prepared.encoding.input.retrieval_text
                candidates=[dict(passage_id=h.chunk.id,text='\n'.join(
                    [c['text'] for c in h.chunk.metadata['contexts']]+[h.chunk.metadata['retrieval_view']['text']])) for h in hybrid.hits]
                if len(candidates)>cfg.max_candidates or len(query)+sum(len(c['text']) for c in candidates)>cfg.max_input_characters:
                    raise RerankError('rerank_input_limit',report)
                scores,report=self.backend.score(query,candidates)
                validate_report(report);validate_scores(scores,[h.chunk.id for h in hybrid.hits])
                if report['status']!='success':raise ValueError()
            report['elapsed_seconds']=max(report['elapsed_seconds'],time.monotonic()-started)
            return RerankResult(hybrid,cfg,provider,model,scores,ranked_hits(hybrid,scores,cfg.top_k),report)
        except RerankError as error:
            raise RerankError(error.code,error.report,encoding_report=encoding) from None
        except Exception:
            report['elapsed_seconds']=max(0.,time.monotonic()-started)
            raise RerankError('rerank_invalid_output',report,encoding_report=encoding) from None
