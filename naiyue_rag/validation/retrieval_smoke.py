"""A bounded synthetic comparison, not a production evaluation platform."""
import argparse
from contextlib import ExitStack
from dataclasses import replace
import json
import logging
import re
from pathlib import Path
import subprocess
import sys
import time


def score_ids(selected,required):
    gold=set(required);hits=len(set(selected)&gold)
    return dict(hits=hits,required=len(gold),recall=hits/len(gold) if gold else None)


def resolve_gold(chunks,required):
    result=[]
    for label in required:
        found=[c.id for c in chunks if c.metadata['source_path']==label['source_path'] and label['anchor'] in c.text]
        if len(found)!=1:raise ValueError('smoke_ambiguous_labels')
        result.append(found[0])
    return result


def validate_labels(data):
    try:
        if type(data) is not dict or set(data)!={'label_source','review_status','unit','questions'} or \
                data['label_source']!='assistant_constructed' or data['review_status']!='not_reviewed_by_user' or \
                data['unit']!='exact_current_chunk_selected_by_unique_source_and_body_anchor':raise ValueError()
        questions=data['questions'];seen=set()
        if type(questions) is not list or not 1<=len(questions)<=4:raise ValueError()
        for question in questions:
            if type(question) is not dict or not {'id','query','required'}<=set(question) or \
                    set(question)-{'id','query','required','unanswerable'}:raise ValueError()
            uid=question['id'];query=question['query'];required=question['required']
            if type(uid) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,32}',uid) or uid in seen:raise ValueError()
            seen.add(uid)
            if type(query) is not str or not query.strip() or len(query)>4096 or \
                    type(required) is not list or len(required)>100 or type(question.get('unanswerable',False)) is not bool:raise ValueError()
            for label in required:
                if type(label) is not dict or set(label)!={'source_path','anchor'} or \
                        any(type(v) is not str or not v.strip() for v in label.values()):raise ValueError()
        return questions
    except Exception:raise ValueError('smoke_invalid_labels') from None


def worker(args):
    import httpx
    from ..app import load_app_settings,_manager
    from ..core.encoding_settings import load_encoding_settings
    from ..core.sparse_encoding_settings import load_sparse_encoding_settings
    from ..core.hybrid_settings import load_hybrid_settings
    from ..core.rerank_settings import load_rerank_settings
    from ..core.evidence_settings import load_evidence_settings
    from ..core.credentials import resolve_api_key
    from ..encoding import OpenAICompatibleEmbedding,DenseEncoder,SparseEncoder,QueryEncoder
    from ..query.hybrid_search import HybridSearch
    from ..query.knowledge_reader import KnowledgeReader
    from ..reranking.core import CoreReranker
    from ..reranking.bootstrap import load_llm_reranker
    from ..response.builder import ResponseBuilder
    output=Path(args.output_dir);cfg=load_app_settings(args.config);started=time.monotonic()
    question_path=Path(args.questions)
    if question_path.stat().st_size>65536:raise ValueError('smoke_input_limit')
    labels=json.loads(question_path.read_text());questions=validate_labels(labels)
    native=httpx.HTTPTransport;requests=[]
    class Counted(httpx.BaseTransport):
        def __init__(self,**kwargs):self.inner=native(**kwargs)
        def handle_request(self,request):
            if len(requests)>=args.max_requests or time.monotonic()-started>=args.deadline_seconds:
                raise RuntimeError('smoke_request_limit')
            requests.append(dict(index=len(requests)+1,kind='embedding' if request.url.path.endswith('/embeddings') else 'rerank'))
            (output/'requests.json').write_text(json.dumps(requests))
            return self.inner.handle_request(request)
        def close(self):self.inner.close()
    httpx.HTTPTransport=Counted
    try:
        manager=_manager(cfg);encoding=load_encoding_settings(cfg['encoding'])
        rerank=load_rerank_settings(cfg['rerank']);baseline_cfg=replace(rerank,enabled=False)
        builder=ResponseBuilder(KnowledgeReader(manager.settings),load_evidence_settings(cfg['evidence']))
        with ExitStack() as owned:
            provider=owned.enter_context(OpenAICompatibleEmbedding(encoding,api_key=resolve_api_key(cfg['project_root'],cfg['key_env'])))
            encoder=QueryEncoder(encoding,DenseEncoder(encoding,provider),SparseEncoder(encoding,load_sparse_encoding_settings(cfg['sparse'])))
            search=HybridSearch(manager,encoder,load_hybrid_settings(cfg['hybrid']))
            if cfg['rerank_backend']=='llm':backend=owned.enter_context(load_llm_reranker(cfg['model_settings'],project_root=cfg['project_root'],key_env=cfg['key_env']))
            elif cfg['rerank_backend']=='cross_encoder':
                from ..reranking.cross_encoder import load_cross_encoder
                backend=load_cross_encoder(cfg['model_settings'])
            else:raise ValueError('smoke_requires_backend')
            rows=[]
            for question in questions:
                hybrid=search.search(question['query']);bundle=manager.bundles.load(hybrid.prepared.active.version.bundle_id)
                gold=resolve_gold(bundle.chunks,question['required']);base=CoreReranker(baseline_cfg).rerank(hybrid)
                ranked=CoreReranker(rerank,backend).rerank(hybrid)
                before=builder.build(base);after=builder.build(ranked)
                row=dict(id=question['id'],gold_chunk_ids=gold,
                    pool=score_ids([h.chunk.id for h in hybrid.hits],gold),
                    baseline=score_ids([h['chunk_id'] for h in base.hits],gold),
                    reranked=score_ids([h['chunk_id'] for h in ranked.hits],gold),
                    packed_baseline=score_ids([e['chunk_id'] for e in before['evidence']],gold),
                    packed_reranked=score_ids([e['chunk_id'] for e in after['evidence']],gold),
                    answerability=after['answerability'],unanswerable=question.get('unanswerable',False),
                    embedding_report=hybrid.prepared.encoding.report.to_dict(),rerank_report=ranked.report)
                rows.append(row)
                (output/(question['id']+'.hybrid.json')).write_text(json.dumps(hybrid.to_dict(),ensure_ascii=False))
                (output/(question['id']+'.rerank.json')).write_text(json.dumps(ranked.to_dict(),ensure_ascii=False))
                (output/(question['id']+'.evidence.json')).write_text(json.dumps(after,ensure_ascii=False))
            report=dict(status='success',label_source=labels['label_source'],review_status=labels['review_status'],
                metric='chunk Recall@configured_top_k = unique required IDs returned / required IDs; empty gold => null',
                top_k=rerank.top_k,pool_k=search.settings.fusion_top_k,backend=cfg['rerank_backend'],
                rows=rows,requests=len(requests),elapsed_seconds=time.monotonic()-started,cost_cny=None,
                unanswerable_policy='answerability remains unknown; no classifier implemented')
            (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps(dict(status='success',requests=len(requests),rows=[{k:r[k] for k in
                ('id','pool','baseline','reranked','answerability')} for r in rows]),ensure_ascii=False))
    finally:httpx.HTTPTransport=native


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--questions',required=True)
    parser.add_argument('--output-dir',required=True);parser.add_argument('--max-requests',type=int,required=True)
    parser.add_argument('--deadline-seconds',type=int,required=True);parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if not 1<=args.max_requests<=12 or not 1<=args.deadline_seconds<=300:parser.error('invalid bounded validation limits')
    if args.worker:
        try:worker(args);return 0
        except Exception as error:
            from ..core.errors import QueryJobError,IngestionJobError,SettingsError,StorageError
            from ..reranking.report import RerankError
            from ..response.builder import EvidenceError
            known=(QueryJobError,IngestionJobError,RerankError,EvidenceError)
            details=error.to_dict() if isinstance(error,known) else {'code':error.code} if isinstance(error,(SettingsError,StorageError)) else {'code':'smoke_failed'}
            logging.getLogger(__name__).error('smoke_failed code=%s',details.get('code','smoke_failed'))
            failure=dict(status='failed',error=details)
            try:(Path(args.output_dir)/'failure.json').write_text(json.dumps(failure,ensure_ascii=False))
            except OSError:logging.getLogger(__name__).error('smoke_failed code=smoke_report_write_failed')
            print(json.dumps(failure,ensure_ascii=False));return 2
    output=Path(args.output_dir)
    output.mkdir(parents=True,exist_ok=False)
    command=[sys.executable,'-m','naiyue_rag.validation.retrieval_smoke']+sys.argv[1:]+['--worker']
    try:
        process=subprocess.run(command,text=True,capture_output=True,timeout=args.deadline_seconds)
        (output/'process.json').write_text(json.dumps(dict(returncode=process.returncode,stdout=process.stdout,stderr=process.stderr),ensure_ascii=False))
        print(process.stdout);return process.returncode
    except subprocess.TimeoutExpired:
        (output/'supervision.json').write_text(json.dumps(dict(status='deadline_exceeded',remote_completion='unknown')))
        print(json.dumps(dict(status='deadline_exceeded')));return 2


if __name__=='__main__':raise SystemExit(main())
