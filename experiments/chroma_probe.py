"""Chroma persistence and A2/reference-profile comparison over frozen vectors."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from experiments.embedding_probe import ProbeError
from experiments.hybrid_probe import scope_key, write_json
from experiments.keyword_index import Tokenizer, build_index, search as sparse_search, parameters
from experiments.lightrag_runtime import offline_guard, supervise, worker_environment
from experiments.markdown_probe import new_run_id
from experiments.rank_fusion import fuse
from experiments.vector_eval import evaluate, load_labels, load_queries
from experiments.vector_index import digest, identity, load_corpus, load_index, pack_evidence, read_json, read_rows, search
from experiments.vector_probe import check_deadline
from naiyue_rag.chroma_store import validate_config as validate_store_config
from naiyue_rag.retrieval import RetrievalError


def launch_worker(job, action, scratch, timeout):
    # Existing supervisor preserves safe stderr/result and kills timed-out children.
    env = worker_environment(Path(scratch)/'unused-tokenizer-cache')
    env.update(OMP_NUM_THREADS='1',TOKENIZERS_PARALLELISM='false',CHROMA_SLICE_OFFLINE='1')
    return supervise([os.path.abspath(sys.executable),'-m','experiments.chroma_worker'],
                     {**job,'action':action},scratch,env,timeout)


def store_config(config, corpus, index, native_root):
    return {'persist_directory':str(native_root.resolve()),'collection_name':config['collection_name'],
            'embedding_identity':identity(config),'corpus_id':corpus['fingerprint'],'index_id':index['index_id'],
            'authorized_document_ids':sorted(corpus['sources']),'excluded_document_ids':corpus['excluded_ids']}


def validate_config(config):
    try:
        parameters(config)
        for key in ['dataset','corpus_run','tasks','vector_run','keyword_run','output_root','runtime_lock','endpoint','model']:
            if type(config.get(key)) is not str or not config[key]:
                raise ValueError('path')
        for key,expected in [('dimensions',2048),('candidate_k',20),('rrf_k',60),('max_context_chars',8000)]:
            if type(config.get(key)) is not int or config[key] != expected:
                raise ValueError('parameters')
        for key,maximum in [('deadline_seconds',180),('worker_timeout_seconds',60)]:
            if type(config.get(key)) is not int or not 0 < config[key] <= maximum:
                raise ValueError('deadline')
        validate_store_config({'persist_directory':str(Path(config['output_root']).resolve()),
            'collection_name':config['collection_name'],'embedding_identity':identity(config),
            'corpus_id':'preflight','index_id':'preflight','authorized_document_ids':['preflight'],
            'excluded_document_ids':[]})
    except (ValueError,KeyError,TypeError,RetrievalError):
        raise ProbeError('config','invalid_chroma_config') from None


def compare(corpus,index,queries,native_rows,tokenizer,config,baseline_rows):
    results=[]; keyword_indices={}
    if {r['task_id'] for r in baseline_rows} != {q['task_id'] for q in queries}:
        raise ProbeError('baseline','baseline_mismatch')
    prior={r['task_id']:r for r in baseline_rows}
    if len(native_rows) != len(queries):
        raise ProbeError('chroma-audit','query_count_mismatch')
    for query,native in zip(queries,native_rows,strict=True):
        if any(native.get(k)!=v for k,v in query.items()):
            raise ProbeError('chroma-audit','query_binding_mismatch')
        exact=search(index,index['query_vectors'][query['task_id']],query['scope_ids'],query['exclude_ids'],20)
        key=scope_key(query)
        if key not in keyword_indices:
            keyword_indices[key]=build_index(corpus,query['scope_ids'],query['exclude_ids'],tokenizer,config)
        sparse=sparse_search(keyword_indices[key],query['query'],tokenizer,20)
        sparse={**query,**sparse,**pack_evidence(sparse['candidates'],8000)}
        if sparse != prior[query['task_id']]['sparse']:
            raise ProbeError('baseline','keyword_baseline_mismatch')
        dense={'candidates':native['candidates'],'compared_count':native['compared_count']}
        profiles={}; unions={}
        for name,k in [('a2',20),('reference',10)]:
            fused=fuse(dense['candidates'],sparse['candidates'],index['units'],60,k)
            profiles[name]={**query,'candidates':fused['candidates'],**pack_evidence(fused['candidates'],8000)}
            unions[name]=fused['union_candidates']
        exact_ids=[u['unit_id'] for u in exact['candidates']]
        native_ids=[u['unit_id'] for u in dense['candidates']]
        before=[u['unit_id'] for u in prior[query['task_id']]['hybrid']['selected']]
        after=[u['unit_id'] for u in profiles['a2']['selected']]
        results.append({**query,'dense':dense,'sparse':sparse,'profiles':profiles,'union_candidates':unions,
            'distance_audit':native['distance_audit'],'comparison':{
                'exact_dense_ids':exact_ids,'native_dense_ids':native_ids,
                'dense_top20_overlap':len(set(exact_ids)&set(native_ids)),
                'dense_order_equal':exact_ids==native_ids,'a2_selected_order_equal':before==after,
                'old_selected_ids':before,'new_selected_ids':after}})
    return results


def report(state,rows):
    lines=['# Chroma与A2固定向量对照','',f"状态：{state['status']}；模型请求0；Python网络尝试：{state['python_network_attempts']}",
        '本机真实Chroma1.5.9；合成11文档/52单元/4题；标签assistant_constructed/not_reviewed。',
        '原生Rust网络未独立观测；遥测关闭，Python socket/DNS阻断，不声称全进程网络捕获。',
        '小样本不足以证明HNSW性能；延迟包含启动/审计/IO，不当生产检索基准。','',
        '| 题目 | Dense顺序一致 | Dense交集 | A2最终顺序一致 | A2必要证据覆盖 | 参考fusion10覆盖 |',
        '|---|---|---|---|---|---|']
    metrics={m['task_id']:m for m in (state.get('evaluation') or [])}
    for row in rows:
        c=row['comparison']; m=metrics[row['task_id']]
        lines.append(f"| {row['task_id']} | {c['dense_order_equal']} | {c['dense_top20_overlap']} | "
                     f"{c['a2_selected_order_equal']} | {m['a2']['coverage_at_budget']} | {m['reference']['coverage_at_budget']} |")
    lines+=['','Recall@k按与必要标注范围相交的相关公共单元计算；覆盖率按必要证据范围完整覆盖计算。',
        '无答案题Q04指标N/A，系统answerability仍unknown；没有问答/用例生成或真实材料质量结论。',
        'A2 profile为20/20/20/8000，reference profile为20/20/10/8000；两者均等权RRF60。']
    return '\n'.join(lines)+'\n'


def run(config):
    validate_config(config); started=time.monotonic()
    config = dict(config)
    for key in ['dataset','corpus_run','tasks','vector_run','output_root','runtime_lock','keyword_run']:
        config[key] = str(Path(config[key]).resolve())
    root=Path(config['output_root']).resolve()/new_run_id()
    try: root.mkdir(parents=True,exist_ok=False)
    except OSError: raise ProbeError('output','output_error') from None
    state={'status':'running','output_dir':str(root),'config':config,'workers':{},'attempt_count':0,
           'python_network_attempts':0,'evaluation':None,'sanitized_error':None}
    rows=[]; counter=[0]
    try:
        with offline_guard(counter):
            corpus=load_corpus(config['corpus_run'],config['dataset'])
            index=load_index(config['vector_run'],corpus['fingerprint'],config)
            queries=load_queries(config['tasks'],corpus)
            job={'config':config,'store_config':store_config(config,corpus,index,root/'chroma'),
                 'runtime_lock':config['runtime_lock'],'batch_size':100,'candidate_k':20}
            state.update(worker_job=job,source_units=index['units'],corpus_id=corpus['fingerprint'],index_id=index['index_id'])
            for action in ['build','query']:
                check_deadline(config,started)
                remaining=min(config['worker_timeout_seconds'],config['deadline_seconds']-(time.monotonic()-started))
                state['workers'][action]=launch_worker(job,action,root/'workers'/action,remaining)
            build,query=state['workers']['build'],state['workers']['query']
            if build['runtime'] != query['runtime'] or build['count'] != build['repeat_count'] or build['count'] != len(index['units']):
                raise ProbeError('chroma-audit','native_roundtrip_mismatch')
            tokenizer=Tokenizer(root/'jieba-cache')
            # Validate original A2 by its own manifest before comparing unchanged sparse output.
            baseline=read_rows(Path(config['keyword_run'])/'results.jsonl','baseline')
            baseline_state=read_json(Path(config['keyword_run'])/'summary.json','baseline')
            if baseline_state['status'] != 'complete' or baseline_state['index_id'] != index['index_id'] or \
                    baseline_state['corpus_fingerprint'] != corpus['fingerprint']:
                raise ProbeError('baseline','baseline_mismatch')
            rows=compare(corpus,index,queries,query['results'],tokenizer,config,baseline)
            check_deadline(config,started)
            # Labels enter only after native recall, sparse comparison and evidence packing.
            gold=load_labels(config['tasks'],corpus)
            state['evaluation']=[{'task_id':r['task_id'],**{name:evaluate(out,corpus,gold)
                for name,out in r['profiles'].items()}} for r in rows]
            state.update(status='complete',tokenizer_identity=tokenizer.identity)
    except ProbeError as error:
        state.update(status='error',sanitized_error=error.record(),evaluation=None); rows=[]
    except Exception:
        state.update(status='error',sanitized_error=ProbeError('pipeline','unexpected_error').record(),evaluation=None); rows=[]
    state['python_network_attempts']=counter[0]+sum(w['trace']['python_network_attempts'] for w in state['workers'].values())
    state.update(elapsed_ms=round((time.monotonic()-started)*1000,3),exit_code=0 if state['status']=='complete' else 2)
    try:
        if state['status']=='complete':
            with (root/'results.jsonl').open('x',encoding='utf-8') as handle:
                for row in rows: handle.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            write_json(root/'evaluation.json',state['evaluation'])
        (root/'report.md').write_text(report(state,rows),encoding='utf-8')
        write_json(root/'summary.json',state)
    except (OSError,ValueError,TypeError): raise ProbeError('output','output_error') from None
    return state


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-run',required=True)
    parser.add_argument('--output-root',required=True)
    parser.add_argument('--runtime-lock',required=True)
    parser.add_argument('--collection-name',required=True)
    parser.add_argument('--worker-timeout-seconds',type=int,required=True)
    parser.add_argument('--deadline-seconds',type=int,required=True)
    args=parser.parse_args(argv)
    try:
        prior=read_json(Path(args.baseline_run)/'summary.json')
        cfg={**prior['config'],'keyword_run':str(Path(args.baseline_run).resolve()),
             **{k:v for k,v in vars(args).items() if k!='baseline_run'}}
        state=run(cfg)
    except ProbeError as error:
        print(json.dumps(error.record()),file=sys.stderr); return 2
    print(f"status={state['status']} model_calls=0 python_network_attempts={state['python_network_attempts']} output={state['output_dir']}")
    if state['sanitized_error']: print(json.dumps(state['sanitized_error']),file=sys.stderr)
    return state['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
