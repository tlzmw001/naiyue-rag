"""B0 real SDK naive retrieval using shared corpus and immutable A1 vector cache."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from experiments.embedding_probe import ProbeError
from experiments.lightrag_mapping import make_payload, map_results
from experiments.lightrag_runtime import check_tokenizer, offline_guard, supervise, worker_environment
from experiments.markdown_probe import new_run_id
from experiments.vector_eval import covered, evaluate, load_labels, load_queries
from experiments.vector_index import digest, load_corpus, load_index, pack_evidence, read_json, read_rows, search
from experiments.vector_probe import check_deadline


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def validate_config(config):
    if config.get('mode') not in ['build', 'replay'] or (config['mode']=='replay' and not config.get('b0_run')):
        raise ProbeError('config', 'invalid_mode')
    for key, limit in [('dimensions',2048),('candidate_k',20),('max_context_chars',8000),
                       ('max_total_tokens',32768),('worker_timeout_seconds',60),('deadline_seconds',180)]:
        if type(config.get(key)) is not int or not 0 < config[key] <= limit:
            raise ProbeError('config', 'invalid_'+key)
    if config['dimensions'] != 2048 or config.get('sdk_version') != '1.5.7' or \
            type(config.get('cosine_threshold')) not in (int,float) or config['cosine_threshold'] != -1:
        raise ProbeError('config', 'invalid_runtime_policy')
    for key in ['dataset','corpus_run','tasks','vector_run','runtime_python','runtime_lock','model','endpoint',
                'output_root','tokenizer_cache','tokenizer_encoding']:
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ProbeError('config', 'invalid_'+key)


def native_files(root):
    result = {}
    root = Path(root).resolve()
    if not root.is_dir(): raise ProbeError('cache', 'native_cache_missing')
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise ProbeError('cache', 'native_cache_path')
        if path.is_file(): result[str(path.relative_to(root))] = digest(path.read_bytes())
    if not result: raise ProbeError('cache', 'native_cache_missing')
    return result


def baseline(config, corpus, index, queries, started):
    prior = read_json(Path(config['vector_run'])/'summary.json', 'baseline')
    if prior.get('status') != 'complete': raise ProbeError('baseline', 'baseline_mismatch')
    rows = []
    for query in queries:
        check_deadline(config, started)
        ranked = search(index, index['query_vectors'][query['task_id']], query['scope_ids'], query['exclude_ids'], config['candidate_k'])
        rows.append({**query, **ranked, **pack_evidence(ranked['candidates'], config['max_context_chars']),
                     'index_id': index['index_id'], 'elapsed_ms': 0})
    old = read_rows(Path(config['vector_run'])/'results.jsonl', 'baseline')
    if [{k:v for k,v in row.items() if k!='elapsed_ms'} for row in old] != \
            [{k:v for k,v in row.items() if k!='elapsed_ms'} for row in rows]:
        raise ProbeError('baseline', 'baseline_mismatch')
    return old


def run_scope(config, payload, native_root, scratch, started, build):
    scope_started = time.monotonic(); result = {}; built = None
    settings = {k:config[k] for k in ['sdk_version','model','dimensions','candidate_k','max_total_tokens','cosine_threshold','tokenizer_encoding']}
    settings.update(runtime_lock=str(Path(config['runtime_lock']).resolve()),
                    tokenizer_cache=str(Path(config['tokenizer_cache']).resolve()), working_dir=str(Path(native_root).resolve()))
    # Resolving the venv's Python symlink would invoke the base interpreter and lose sys.prefix.
    command = [os.path.abspath(config['runtime_python']), '-m', 'experiments.lightrag_worker']
    for action in (['build', 'query'] if build else ['query']):
        check_deadline(config, started)
        remaining = min(config['deadline_seconds']-(time.monotonic()-started),
                        config['worker_timeout_seconds']-(time.monotonic()-scope_started))
        cwd = Path(scratch)/action
        result = supervise(command, {**payload, **settings, 'action':action}, cwd,
                           worker_environment(config['tokenizer_cache']), remaining)
        if result.get('dotenv_sentinel_loaded'): raise ProbeError('runtime', 'dotenv_loaded')
        if result['trace']['network_attempts'] or result['trace']['llm_calls']:
            raise ProbeError('worker', 'unexpected_external_call')
        if built is not None and built['runtime'] != result['runtime']: raise ProbeError('runtime','runtime_mismatch')
        if action=='build': built=result
        check_deadline(config, started)
    return {'build':built, 'query':result, 'elapsed_ms':round((time.monotonic()-scope_started)*1000,3)}


def descriptor(config, corpus, index, queries, payloads, tokenizer):
    policy = {k:config[k] for k in ['sdk_version','model','endpoint','dimensions','candidate_k','max_context_chars',
                                    'max_total_tokens','cosine_threshold','tokenizer_encoding']}
    return {'schema_version':1, 'corpus_fingerprint':corpus['fingerprint'], 'index_id':index['index_id'],
            'policy':policy, 'runtime_lock_sha256':digest(Path(config['runtime_lock']).read_bytes()), 'tokenizer':tokenizer,
            'queries':queries, 'scope_units':{key:[u['native_id'] for u in p['units']] for key,p in payloads.items()},
            'unit_input_sha256':{u['native_id']:u['input_sha256'] for p in payloads.values() for u in p['units']}}


def build_report(state, rows):
    lines=['# B0 LightRAG naive实际对照', '', f"状态：{state['status']}；模型请求：{state['attempt_count']}；网络尝试：{state['network_attempts']}",
           '固定合成资料；assistant_constructed/not_reviewed标签，无真实业务/图检索/答案质量证据。',
           '完成以最后summary.json为准；新模型tokens/费用不适用。', '',
           '| 任务 | 路径 | Recall@10 | Recall@20 | Coverage@8000 | 条/字符 |', '|---|---|---:|---:|---:|---|']
    metrics={m['task_id']:m for m in state['evaluation'] or []}
    for row in rows:
        for name in ['A1','B0']:
            m=metrics[row['task_id']][name];r=row[name]
            lines.append(f"| {row['task_id']} | {name} | {m['recall_at_10']} | {m['recall_at_20']} | {m['coverage_at_budget']} | {len(r['selected'])}/{r['context_characters']} |")
        native=row['native']
        lines.extend(['', '## '+row['task_id'], '',
                      f"范围内={row['B0']['compared_count']}；raw={len(native['raw'])}；SDK={len(native['chunks'])}；"
                      f"可用片段tokens={native['available_chunk_tokens']}；全scope正文tokens={native['scope_total_content_tokens']}",
                      '', '````markdown', row['B0']['context_text'], '````'])
    lines.extend(['', '错误：'+json.dumps(state['sanitized_error']),
                  'B0未建实体图、未重排/生成/MCP；Q04 answerability=unknown。耗时含进程启动/IO/验证，不是性能基准。'])
    return '\n'.join(lines)+'\n'


def failure_analysis(rows, gold):
    lines=['# B0必要证据去留', '', '| 任务/证据 | A1候选 | raw-VDB | SDK候选 | A1返回 | B0返回 | 状态 |',
           '|---|---:|---:|---:|---|---|---|']
    for row in rows:
        for eid in gold['tasks'][row['task_id']]['required']:
            label=gold['evidence'][eid]
            old=covered(label,row['A1']['selected']);new=covered(label,row['B0']['selected'])
            candidates=row['B0']['candidates']
            native_unit={r['retrieval_info']['native_chunk_id']:r for r in candidates}
            ranks=[next((r['rank'] for r in group if covered(label,[r])),None) for group in [row['A1']['candidates'],candidates]]
            raw_rank=next((i+1 for i,r in enumerate(row['native']['raw']) if r['id'] in native_unit and covered(label,[native_unit[r['id']]])),None)
            reason='returned' if new else ('budget_excluded' if covered(label,candidates) else 'not_recalled')
            lines.append(f"| {row['task_id']}/{eid} | {ranks[0]} | {raw_rank} | {ranks[1]} | {old} | {new} | {reason} |")
    return '\n'.join(lines)+'\n'


def run(config):
    started=time.monotonic();validate_config(config)
    folder=Path(config['output_root']).resolve()/new_run_id()
    try:folder.mkdir(parents=True,exist_ok=False)
    except OSError:raise ProbeError('output','output_error') from None
    state={'status':'running','config':config,'attempt_count':0,'llm_calls':0,'network_attempts':None,
           'model_usage':None,'model_cost_cny':None,'evaluation':None,'sanitized_error':None,'output_dir':str(folder)}
    rows=[];counter=[0];scopes={};analysis=None
    with offline_guard(counter):
        try:
            corpus=load_corpus(config['corpus_run'],config['dataset']);queries=load_queries(config['tasks'],corpus)
            index=load_index(config['vector_run'],corpus['fingerprint'],config)
            if set(index['query_hashes'])!={q['task_id'] for q in queries} or any(index['query_hashes'][q['task_id']]!=digest(q['query'].encode()) for q in queries):
                raise ProbeError('cache','cache_mismatch')
            tokenizer=check_tokenizer(config['tokenizer_cache'],config['tokenizer_encoding'])
            if not Path(config['runtime_python']).is_file():raise ProbeError('runtime','runtime_missing')
            payloads={}
            for query in queries:
                p=make_payload(corpus,index,[query]);key=p['scope_key']
                if key not in payloads:payloads[key]=p
                else:payloads[key]=make_payload(corpus,index,payloads[key]['queries']+[query])
            expected=descriptor(config,corpus,index,queries,payloads,tokenizer)
            a1=baseline(config,corpus,index,queries,started)
            origin=folder if config['mode']=='build' else Path(config['b0_run']).resolve()
            header=None
            if config['mode']=='replay':
                header=read_json(origin/'index_manifest.json','cache')
                if read_json(origin/'summary.json','cache')['status']!='complete' or header.get('descriptor')!=expected or \
                        native_files(origin/'native')!=header['native_files']:
                    raise ProbeError('cache','native_cache_mismatch')
            for key,payload in payloads.items():
                scopes[key]=run_scope(config,payload,origin/'native',folder/'workers'/key,started,config['mode']=='build')
                runtime=scopes[key]['query']['runtime']
                if header and runtime!=header['runtime']:raise ProbeError('runtime','runtime_mismatch')
            if len({json.dumps(s['query']['runtime'],sort_keys=True) for s in scopes.values()})!=1:
                raise ProbeError('runtime','runtime_mismatch')
            raw_files=native_files(origin/'native')
            if header and raw_files!=header['native_files']:raise ProbeError('cache','native_cache_modified')
            native_queries={q['task_id']:q for s in scopes.values() for q in s['query']['queries']}
            for query,old in zip(queries,a1,strict=True):
                payload=make_payload(corpus,index,[query]);native=native_queries[query['task_id']]
                candidates=map_results(payload,native['raw'],native['chunks'],index,config['candidate_k'])
                # This fixed cache baseline expects enough token budget to preserve all retrieved units.
                if len(native['raw'])!=len(native['chunks']):raise ProbeError('query','native_token_truncation')
                ranked={**query,'candidates':candidates,'compared_count':len(payload['units']),
                        'index_id':index['index_id'],**pack_evidence(candidates,config['max_context_chars'])}
                rows.append({**query,'A1':old,'B0':ranked,'native':native})
            gold=load_labels(config['tasks'],corpus)
            metrics=[{'task_id':r['task_id'],'A1':evaluate(r['A1'],corpus,gold),'B0':evaluate(r['B0'],corpus,gold)} for r in rows]
            if [m['A1'] for m in metrics]!=read_json(Path(config['vector_run'])/'evaluation.json','baseline'):
                raise ProbeError('baseline','baseline_mismatch')
            state.update(evaluation=metrics,corpus_fingerprint=corpus['fingerprint'],index_id=index['index_id'],
                         source_native_run=str(origin),scope_count=len(scopes),scopes=scopes)
            manifest={'status':'complete','descriptor':expected,'native_files':raw_files,
                      'runtime':next(iter(scopes.values()))['query']['runtime']}
            write_json(folder/'index_manifest.json',manifest)
            write_json(folder/'unit_mapping.json',{key:p['units'] for key,p in payloads.items()})
            write_json(folder/'native_storage_audit.json',{key:{a:s[a]['audit'] for a in ['build','query'] if s[a]} for key,s in scopes.items()})
            write_json(folder/'native_queries.json',native_queries)
            analysis=failure_analysis(rows,gold);check_deadline(config,started);state['status']='complete'
        except ProbeError as error:
            state.update(status='error',sanitized_error=error.record(),evaluation=None);rows=[]
        except Exception as error:
            state.update(status='error',sanitized_error=ProbeError('pipeline','unexpected_error').record(),evaluation=None,error_type=type(error).__name__);rows=[]
        # A failed scope is absent from scopes; consume saved terminal traces as well as successful workers.
        reports=list((folder/'workers').rglob('worker-result.json'))
        terminal=[read_json(path,'trace')['trace'] for path in reports]
        observed=counter[0]+sum(t['network_attempts'] for t in terminal)
        known=all((path.parent/'worker-result.json').exists() for path in (folder/'workers').rglob('worker-stderr.txt'))
        state['observed_network_attempts']=observed
        state['network_attempts']=observed if known else None
        state['llm_calls']=sum(t['llm_calls'] for t in terminal) if known else None
        state['exit_code']=0 if state['status']=='complete' else 2
        try:
            if state['evaluation'] is not None:
                with (folder/'results.jsonl').open('x',encoding='utf-8') as handle:
                    for row in rows:handle.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
                write_json(folder/'evaluation.json',state['evaluation'])
                with (folder/'failure-analysis.md').open('x',encoding='utf-8') as handle:handle.write(analysis)
            report=build_report(state,rows)
            if state['status']=='complete':check_deadline(config,started)
            with (folder/'report.md').open('x',encoding='utf-8') as handle:handle.write(report)
            if state['status']=='complete':check_deadline(config,started)
            state['elapsed_ms']=round((time.monotonic()-started)*1000,3);write_json(folder/'summary.json',state)
        except (OSError,ValueError,TypeError):raise ProbeError('output','output_error') from None
    return state


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['mode','dataset','corpus-run','tasks','vector-run','runtime-python','runtime-lock','sdk-version',
                 'model','endpoint','output-root','tokenizer-cache','tokenizer-encoding']:
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--b0-run')
    for name in ['dimensions','candidate-k','max-context-chars','max-total-tokens','worker-timeout-seconds','deadline-seconds']:
        parser.add_argument('--'+name,type=int,required=True)
    parser.add_argument('--cosine-threshold',type=float,required=True)
    try:state=run(vars(parser.parse_args(argv)))
    except ProbeError as error:print(str(error),file=sys.stderr);return 2
    print(f"status={state['status']} attempts={state['attempt_count']} network_attempts={state['network_attempts']} output={state['output_dir']}")
    if state['sanitized_error']:print(json.dumps(state['sanitized_error']),file=sys.stderr)
    return state['exit_code']


if __name__=='__main__':raise SystemExit(main())
