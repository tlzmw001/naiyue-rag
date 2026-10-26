"""Atomic evidence packing from one audited saved version, without model generation."""
import copy
import json
import logging
import time
from ..core.evidence_settings import EvidenceSettings
from ..core.rerank_results import RerankResult
from ..query.knowledge_reader import KnowledgeReader


class EvidenceError(ValueError):
    CODES=frozenset(('evidence_invalid_input','evidence_source_mismatch','evidence_read_failed','evidence_response_limit'))

    def __init__(self,code,observations=None):
        self.code=code if code in self.CODES else 'evidence_invalid_input'
        # Observations are assembled only from previously validated closed reports.
        self.observations=copy.deepcopy(observations)
        logging.getLogger(__name__).error('evidence_failed code=%s',self.code)
        super().__init__(self.code)

    def to_dict(self):return dict(code=self.code,observations=copy.deepcopy(self.observations))


def _render(evidence):
    span=evidence['body_span']
    heading=f"[{evidence['citation_id']}] {evidence['source_path']} L{span['line_start']}-L{span['line_end']}"
    return '\n'.join([heading]+[c['text'] for c in evidence['contexts']]+[evidence['body']])


class ResponseBuilder:
    def __init__(self,reader,settings):
        if type(reader) is not KnowledgeReader or type(settings) is not EvidenceSettings:raise EvidenceError('evidence_invalid_input')
        self.reader=reader;self.settings=EvidenceSettings.from_dict(settings.to_dict())

    def build(self,ranked):
        observations=None;started=time.monotonic()
        try:
            if type(ranked) is not RerankResult:raise EvidenceError('evidence_invalid_input')
            ranked=RerankResult.from_dict(ranked.to_dict());cfg=EvidenceSettings.from_dict(self.settings.to_dict())
            hybrid=ranked.hybrid;prepared=hybrid.prepared
            observations=dict(retrieval=copy.deepcopy(hybrid.trace_report),
                embedding=None if prepared.encoding is None else prepared.encoding.report.to_dict(),rerank=copy.deepcopy(ranked.report),
                retrieval_configuration=hybrid.settings.to_dict(),rerank_configuration=dict(enabled=ranked.settings.enabled,
                    provider=ranked.provider,model=ranked.model,top_k=ranked.settings.top_k))
            chunks={h.chunk.id:h.chunk for h in hybrid.hits}
            if prepared.active is not None:
                try:_,bundle=self.reader._bundle(prepared)
                except Exception:raise EvidenceError('evidence_read_failed',observations) from None
                saved={c.id:c for c in bundle.chunks}
                if any(uid not in saved or saved[uid].to_dict()!=c.to_dict() for uid,c in chunks.items()):
                    raise EvidenceError('evidence_source_mismatch',observations)
            elif chunks:raise EvidenceError('evidence_source_mismatch',observations)
            dense={h.chunk.id:h for h in hybrid.dense_hits};sparse={h.chunk.id:h for h in hybrid.sparse_hits}
            fused={h.chunk.id:h for h in hybrid.hits};selected=[];omitted=[];parts=[];characters=0
            for hit in ranked.hits:
                uid=hit['chunk_id'];chunk=chunks[uid];meta=chunk.metadata;rrf=fused[uid]
                evidence=dict(citation_id=f'E{len(selected)+1}',rank=hit['rank'],document_id=chunk.source_ref,chunk_id=uid,
                    source_path=meta['source_path'],source_sha256=meta['source_sha256'],body_span=copy.deepcopy(meta['body_span']),
                    body=chunk.text,contexts=copy.deepcopy(meta['contexts']),kind=meta['kind'],
                    retrieval=dict(dense_rank=rrf.dense_rank,sparse_rank=rrf.sparse_rank,
                        dense_distance=None if uid not in dense else dense[uid].distance,
                        dense_score=None if uid not in dense else dense[uid].score,
                        sparse_score=None if uid not in sparse else sparse[uid].score,
                        bm25_statistics_scope=hybrid.settings.bm25_statistics_scope,rrf_score=rrf.score,rrf_rank=rrf.rank,rrf_k=hybrid.settings.rrf_k,
                        dense_score_kind='chroma_cosine_affine_v1',sparse_score_kind=f'bm25s_lucene_{hybrid.settings.bm25_statistics_scope}_v1',
                        rerank_score=hit['score']))
                rendered=_render(evidence);needed=len(rendered)+(2 if parts else 0)
                if characters+needed>cfg.max_context_characters:
                    omitted.append(dict(chunk_id=uid,reason='context_budget'));continue
                selected.append(evidence);parts.append(rendered);characters+=needed
            status='retrieved' if selected else 'no_evidence_fits' if ranked.hits else 'empty'
            observations['packing']=dict(selected_count=len(selected),omitted_count=len(omitted),
                context_characters=characters,elapsed_seconds=max(0.,time.monotonic()-started))
            output=dict(schema_version=1,status=status,answerability='unknown',
                active=None if prepared.active is None else prepared.active.to_dict(),query_sha256=prepared.query_sha256,
                context_text='\n\n'.join(parts),evidence=selected,omitted=omitted,observations=observations)
            if len(json.dumps(output,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8'))>cfg.max_response_bytes:
                raise EvidenceError('evidence_response_limit',observations)
            return copy.deepcopy(output)
        except EvidenceError:raise
        except Exception:raise EvidenceError('evidence_invalid_input',observations) from None
