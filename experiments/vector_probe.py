"""A1 file-vector baseline: live bounded job or explicit keyless replay."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from experiments.embedding_probe import KEY_ENV,ProbeError
from experiments.markdown_probe import new_run_id
from experiments.vector_embedding import initial_state,plan_batches,run_worker,supervise,validate_config
from experiments.vector_eval import evaluate,load_labels,load_queries
from experiments.vector_index import digest,load_corpus,load_index,pack_evidence,read_json,search


def build_report(state,results):
    lines=['# A1向量检索基线实际报告','',f"状态：{state['status']}；模式：{state['config']['mode']}",
           f"本次请求：{state['attempt_count']}；已知估算元：{state['known_estimated_cost_cny']}；总估算元：{state['estimated_cost_cny']}",
           '真实供应商账单：unknown。合成固定标签非全部人工审阅，无真实材料/生成答案质量结果。',
           '', '| 任务 | 范围内比较数 | Recall@10 | Recall@20 | Coverage@预算 | 返回字符 | 未召回 | 预算遗漏 |',
           '|---|---:|---:|---:|---:|---:|---|---|']
    for result,metric in zip(results,state['evaluation'] or [],strict=True):
        lines.append(f"| {result['task_id']} | {result['compared_count']} | {metric['recall_at_10']} | "
                     f"{metric['recall_at_20']} | {metric['coverage_at_budget']} | {result['context_characters']} | "
                     f"{','.join(metric['not_recalled'])} | {','.join(metric['budget_excluded'])} |")
    lines.extend(['','## 逐题实际返回与候选',''])
    for result in results:
        lines.extend([f"### {result['task_id']}",'',result['query'],'',
                      f"status={result['status']}；answerability={result['answerability']}；budget={result['max_context_chars']}",
                      '', '| 候选排名 | cosine | 文档 | 用例/正文位置 | 已返回 |','|---|---:|---|---|---|'])
        selected={u['unit_id'] for u in result['selected']}
        for row in result['candidates']:
            span=row['body_span']
            lines.append(f"| {row['rank']} | {row['score']:.8f} | {row['document_id']} | "
                         f"{row['case_id'] or ''} L{span['line_start']}-{span['line_end']} | {row['unit_id'] in selected} |")
        lines.extend(['','````markdown',result['context_text'],'````',''])
    lines.extend(['## 用量与错误','','```json',json.dumps(state['requests'],ensure_ascii=False,indent=2),'```',
                  '错误：'+json.dumps(state['sanitized_error'],ensure_ascii=False),'',
                  'Q04自动无答案判断未实现：系统unknown，标签insufficient_evidence仅作评价注记。',
                  '没有BM25/RRF、关系扩展、重排、LightRAG、MCP或答案生成；缓存hash非外部恶意文件认证。'])
    return '\n'.join(lines)+'\n'


def check_deadline(config,started):
    if time.monotonic()-started>=config['deadline_seconds']:
        raise ProbeError('deadline','deadline_exceeded')


def run(config):
    started=time.monotonic();validate_config(config)
    corpus=load_corpus(config['corpus_run'],config['dataset'])
    queries=load_queries(config['tasks'],corpus)
    load_labels(config['tasks'],corpus)  # Preflight label integrity; never passed to retrieval.
    plan_batches(config,corpus,queries)
    if config['mode']=='live' and not os.environ.get(KEY_ENV,'').strip():
        raise ProbeError('preflight','missing_key')
    check_deadline(config,started)
    folder=Path(config['output_root']).resolve()/new_run_id()
    try:folder.mkdir(parents=True,exist_ok=False)
    except OSError:raise ProbeError('output','output_error') from None
    state=initial_state(config);results=[];state['evaluation']=None
    try:
        if config['mode']=='live':
            state=supervise({'config':config,'folder':str(folder),'fingerprint':corpus['fingerprint']},started)
            state['evaluation']=None
            cache=folder
        else:
            cache=Path(config['replay_run'])
            previous=read_json(cache/'summary.json','cache')
            if previous['status']!='complete':raise ProbeError('cache','cache_mismatch')
            state['cached_request_count']=previous['attempt_count']
            state['cached_estimated_cost_cny']=previous['estimated_cost_cny']
            state['status']='complete'
        if state['status']=='complete':
            check_deadline(config,started)
            index=load_index(cache,corpus['fingerprint'],config)
            check_deadline(config,started)
            if set(index['query_hashes'])!={q['task_id'] for q in queries} or any(
                    index['query_hashes'][q['task_id']]!=digest(q['query'].encode()) for q in queries):
                raise ProbeError('cache','cache_mismatch')
            state['index_id']=index['index_id'];state['source_vector_run']=str(cache.resolve())
            for query in queries:
                check_deadline(config,started)
                began=time.monotonic()
                ranked=search(index,index['query_vectors'][query['task_id']],query['scope_ids'],
                              query['exclude_ids'],config['candidate_k'])
                packed=pack_evidence(ranked['candidates'],config['max_context_chars'])
                results.append({**query,**ranked,**packed,'index_id':index['index_id'],
                                'elapsed_ms':round((time.monotonic()-began)*1000,3)})
                check_deadline(config,started)
            gold=load_labels(config['tasks'],corpus)
            state['evaluation']=[evaluate(result,corpus,gold) for result in results]
            check_deadline(config,started)
    except ProbeError as error:
        state.update(status='error',sanitized_error=error.record());state['evaluation']=None;results=[]
    except Exception:
        state.update(status='error',sanitized_error=ProbeError('pipeline','unexpected_error').record())
        state['evaluation']=None;results=[]
    state['output_dir']=str(folder);state['corpus_fingerprint']=corpus['fingerprint']
    state['elapsed_ms']=round((time.monotonic()-started)*1000,3)
    state['exit_code']=0 if state['status']=='complete' else 2
    try:
        if state['evaluation'] is not None:
            with (folder/'results.jsonl').open('x',encoding='utf-8') as handle:
                for result in results:handle.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
            with (folder/'evaluation.json').open('x',encoding='utf-8') as handle:
                json.dump(state['evaluation'],handle,ensure_ascii=False,indent=2,allow_nan=False)
        with (folder/'report.md').open('x',encoding='utf-8') as handle:handle.write(build_report(state,results))
        with (folder/'summary.json').open('x',encoding='utf-8') as handle:
            json.dump(state,handle,ensure_ascii=False,indent=2,allow_nan=False)
    except (OSError,ValueError,TypeError):raise ProbeError('output','output_error') from None
    return state


def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    if args==['--worker']:
        try:
            job=json.load(sys.stdin)
            def emit(state):print(json.dumps({'event':'checkpoint','summary':state}),flush=True)
            state=run_worker(job,emit)
            print(json.dumps({'event':'result','summary':state}),flush=True)
            return 0 if state['status']=='complete' else 2
        except Exception:
            print('worker: invalid_input',file=sys.stderr);return 2
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['mode','dataset','corpus-run','tasks','endpoint','model','output-root']:
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--replay-run')
    for name in ['dimensions','batch-size','max-inputs','max-requests','timeout-seconds','deadline-seconds',
                 'max-response-bytes','max-input-utf8-bytes','candidate-k','max-context-chars']:
        parser.add_argument('--'+name,type=int,required=True)
    parser.add_argument('--unit-price-cny-per-million',type=float,required=True)
    try:state=run(vars(parser.parse_args(args)))
    except ProbeError as error:
        print(str(error),file=sys.stderr);return 2
    print(f"status={state['status']} attempts={state['attempt_count']} output={state['output_dir']}")
    if state['sanitized_error']:
        error=state['sanitized_error'];print(f"{error['stage']}: {error['category']}",file=sys.stderr)
    return state['exit_code']


if __name__=='__main__':raise SystemExit(main())
