"""B1 supervised pilot, two isolated graph scopes, fixed evaluation and replay."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from experiments.embedding_probe import KEY_ENV,ProbeError
from experiments.graph_callbacks import Journal,canonical
from experiments.graph_transport import validate_config
from experiments.graph_worker import map_native
from experiments.lightrag_mapping import make_payload,map_results
from experiments.lightrag_probe import baseline,native_files
from experiments.lightrag_runtime import check_tokenizer,supervise,worker_environment
from experiments.markdown_probe import new_run_id
from experiments.vector_eval import load_queries,load_labels,evaluate,covered
from experiments.vector_index import digest,load_corpus,load_index,read_json,read_rows,pack_evidence
from experiments.vector_probe import check_deadline


def write_json(path,data):
    with Path(path).open('x',encoding='utf-8') as handle:json.dump(data,handle,ensure_ascii=False,indent=2,allow_nan=False)


def prepare(config):
    validate_config(config)
    corpus=load_corpus(config['corpus_run'],config['dataset']);queries=load_queries(config['tasks'],corpus)
    vector_config={**config,'model':config['embedding_model'],'endpoint':config['embedding_endpoint']}
    index=load_index(config['vector_run'],corpus['fingerprint'],vector_config)
    if set(index['query_hashes'])!={q['task_id'] for q in queries} or any(index['query_hashes'][q['task_id']]!=digest(q['query'].encode()) for q in queries):
        raise ProbeError('cache','cache_mismatch')
    a1=baseline(vector_config,corpus,index,queries,time.monotonic())
    refs={};previous={}
    for name in ['b0','a2']:
        root=Path(config[name+'_run']);summary=read_json(root/'summary.json','baseline')
        if summary['status']!='complete' or summary['corpus_fingerprint']!=corpus['fingerprint'] or summary['index_id']!=index['index_id']:
            raise ProbeError('baseline','baseline_mismatch')
        previous[name]=read_rows(root/'results.jsonl','baseline')
        if [r['task_id'] for r in previous[name]]!=[q['task_id'] for q in queries]:raise ProbeError('baseline','baseline_mismatch')
        refs[name]={n:digest((root/n).read_bytes()) for n in ['summary.json','results.jsonl','evaluation.json']}
    b0root=Path(config['b0_run']);b0manifest=read_json(b0root/'index_manifest.json','baseline')
    if native_files(b0root/'native')!=b0manifest['native_files']:raise ProbeError('baseline','baseline_mismatch')
    payloads={}
    for q in queries:
        p=make_payload(corpus,index,[q]);key=p['scope_key']
        payloads[key]=p if key not in payloads else make_payload(corpus,index,payloads[key]['queries']+[q])
    full=next(p for p in payloads.values() if len(p['units'])==52)
    pilots=[u for u in full['units'] if u['document_id']=='MOCK-CASE-001' and u['case_id']=='TC-01']
    if len(pilots)!=1 or len(payloads)!=2:raise ProbeError('preflight','fixed_scope_mismatch')
    tokenizer=check_tokenizer(config['tokenizer_cache'],config['tokenizer_encoding'])
    descriptor={'schema_version':1,'fingerprint':corpus['fingerprint'],'index_id':index['index_id'],'references':refs,
                'queries':queries,'tokenizer':tokenizer,'runtime_lock_sha256':digest(Path(config['runtime_lock']).read_bytes()),
                'policy':{k:v for k,v in config.items() if k not in ['mode','graph_run','output_root']},
                'sdk_prompt_sha256':digest((Path(config['runtime_python']).parent.parent/'lib/python3.12/site-packages/lightrag/prompt.py').read_bytes()),
                'adapter_sha256':{p.name:digest(p.read_bytes()) for p in Path(__file__).parent.glob('graph_*.py')}}
    return {'corpus':corpus,'queries':queries,'index':index,'payloads':payloads,'pilot_unit':pilots[0],
            'pilot_query':next(q for q in queries if q['task_id']=='Q01'),'full':full,'a1':a1,
            'b0':previous['b0'],'a2':previous['a2'],'descriptor':descriptor}


def invoke(job,cwd,timeout):
    cfg=job['config'];env=worker_environment(cfg['tokenizer_cache'])
    if cfg['mode']=='live':
        key=os.environ.get(KEY_ENV,'').strip()
        if not key:raise ProbeError('preflight','missing_key')
        env[KEY_ENV]=key
    return supervise([os.path.abspath(cfg['runtime_python']),'-m','experiments.graph_worker'],job,cwd,env,timeout)


def do_stage(config,folder,origin,payload,action,started,limit,cache_root,extra=None):
    check_deadline(config,started)
    timeout=min(limit,config['deadline_seconds']-(time.monotonic()-started))
    job={'config':config,'payload':payload,'action':action,'working_dir':str(origin/('pilot-native' if action=='pilot' else 'native')),
         'cache_root':str(cache_root),**(extra or {})}
    cwd=folder/'workers'/payload['scope_key']/action
    try:cwd.mkdir(parents=True,exist_ok=False)
    except OSError:raise ProbeError('output','output_error') from None
    result=invoke(job,cwd,timeout)
    check_deadline(config,started)
    if result.get('dotenv_sentinel_loaded') or result.get('network_forbidden_attempts',0):raise ProbeError('worker','unexpected_external_call')
    write_json(folder/(action+'-'+payload['scope_key']+'.json'),result)
    return result


def assess(config,prepared,scopes):
    query_rows={q['task_id']:q for s in scopes.values() for q in s['queries']};rows=[]
    for query,a1,b0,a2 in zip(prepared['queries'],prepared['a1'],prepared['b0'],prepared['a2'],strict=True):
        data=query_rows[query['task_id']];payload=make_payload(prepared['corpus'],prepared['index'],[query])
        naive_chunks=data['naive'].get('data',{}).get('chunks',[])
        candidates=map_results(payload,data['raw_vector'],naive_chunks,prepared['index'],config['candidate_k'])
        naive={**query,'candidates':candidates,**pack_evidence(candidates,config['max_context_chars'])}
        for field in ['candidates','selected']:
            if [r['unit_id'] for r in naive[field]]!=[r['unit_id'] for r in b0['B0'][field]]:
                raise ProbeError('baseline','naive_baseline_changed')
        if any(abs(a['score']-b['score'])>1e-6 for a,b in zip(naive['candidates'],b0['B0']['candidates'],strict=True)):
            raise ProbeError('baseline','naive_baseline_changed')
        mix=map_native(payload,data['mix'].get('data',{}).get('chunks',[]))
        dense_ids={c['id'] for c in data['raw_vector']}
        graph_ids={sid for key in ['entities','relationships'] for item in data['mix'].get('data',{}).get(key,[]) for sid in item.get('source_id','').split('<SEP>') if sid}
        for row in mix:
            row['retrieval_info'].update(vector_supported=row['native_id'] in dense_ids,graph_source_supported=row['native_id'] in graph_ids)
        b1={**query,'candidates':mix,'compared_count':len(payload['units']),**pack_evidence(mix,config['max_context_chars'])}
        rows.append({**query,'A1':a1,'A2':a2['hybrid'],'B0':b0['B0'],'B1':b1,'native':data})
    # Fixed labels are not read until all SDK retrieval has finished.
    gold=load_labels(config['tasks'],prepared['corpus'])
    metrics=[{'task_id':r['task_id'],**{name:evaluate(r[name],prepared['corpus'],gold) for name in ['A1','A2','B0','B1']}} for r in rows]
    for name,reference in [('A1',config['vector_run']),('B0',config['b0_run'])]:
        original=read_json(Path(reference)/'evaluation.json','baseline')
        actual=[m[name] for m in metrics]
        expected=original if name=='A1' else [m['B0'] for m in original]
        if actual!=expected:raise ProbeError('baseline','baseline_evaluation_changed')
    if [m['A2'] for m in metrics]!=[m['A2'] for m in read_json(Path(config['a2_run'])/'evaluation.json','baseline')]:
        raise ProbeError('baseline','baseline_evaluation_changed')
    return rows,metrics,gold


def build_report(state,rows):
    lines=['# B1原生图＋片段实际对照','',f"状态：{state['status']}；模式：{state['config']['mode']}",
           '固定合成语料和assistant_constructed/not_reviewed标签；来源登记不证明关系/描述正确。',
           'graph描述只作定位；最终上下文为完整原文。score=null/native_order不是cosine或RRF。',
           '', '| 任务 | 路径 | Recall@20 | Coverage@8000 | 条/字符 |','|---|---|---:|---:|---|']
    metrics={m['task_id']:m for m in state['evaluation'] or []}
    for row in rows:
        for name in ['A1','A2','B0','B1']:
            m=metrics[row['task_id']][name];result=row[name]
            lines.append(f"| {row['task_id']} | {name} | {m['recall_at_20']} | {m['coverage_at_budget']} | {len(result['selected'])}/{result['context_characters']} |")
        lines.extend(['','## '+row['task_id'],'',row['query'],'','````markdown',row['B1']['context_text'],'````'])
    lines.extend(['','## 实际请求记账','','```json',json.dumps(state['requests'],ensure_ascii=False,indent=2),'```',
                  '费用/实际账单unknown；没有提供当前标价或账单。Q04 answerability=unknown。',
                  '内部round-robin完整池及逐路贡献未侵入式观测，记unknown，不伪造归因。',
                  '错误：'+json.dumps(state['sanitized_error']),
                  '缺summary或status非complete的目录为partial；不是生产/MCP/生成用例或答案验证。'])
    return '\n'.join(lines)+'\n'


def failure_analysis(rows,gold):
    lines=['# B1必要原文去留','','| 任务/证据 | A2返回 | B0返回 | B1候选 | B1返回 | 结果 |','|---|---|---|---|---|---|']
    for row in rows:
        for eid in gold['tasks'][row['task_id']]['required']:
            label=gold['evidence'][eid];in_candidates=covered(label,row['B1']['candidates']);returned=covered(label,row['B1']['selected'])
            status='returned' if returned else ('budget_excluded' if in_candidates else 'not_recalled')
            lines.append(f"| {row['task_id']}/{eid} | {covered(label,row['A2']['selected'])} | {covered(label,row['B0']['selected'])} | {in_candidates} | {returned} | {status} |")
    return '\n'.join(lines)+'\n'


def run(config):
    started=time.monotonic();validate_config(config);folder=Path(config['output_root']).resolve()/new_run_id()
    try:folder.mkdir(parents=True,exist_ok=False)
    except OSError:raise ProbeError('output','output_error') from None
    origin=folder if config['mode']=='live' else Path(config['graph_run']).resolve();cache_root=origin/'provider-cache'
    # Read-only on replay; an error before worker startup never becomes a request.
    journal=Journal(cache_root,config,config['mode'])
    state={'status':'running','config':config,'output_dir':str(folder),'source_graph_run':str(origin),
           'evaluation':None,'sanitized_error':None,'requests':journal.summary(),'attempt_count':0,'scopes':{}}
    rows=[];metrics=None;analysis=None
    try:
        prepared=prepare(config);check_deadline(config,started)
        if config['mode']=='live' and not os.environ.get(KEY_ENV,'').strip():raise ProbeError('preflight','missing_key')
        header=None
        if config['mode']=='replay':
            header=read_json(origin/'graph_manifest.json','cache')
            if read_json(origin/'summary.json','cache')['status']!='complete' or header['descriptor']!=prepared['descriptor'] or \
                    header['native_files']!=native_files(origin/'native') or header['provider_files']!=native_files(cache_root):
                raise ProbeError('cache','graph_cache_mismatch')
        else:
            pilot=do_stage(config,folder,origin,prepared['full'],'pilot',started,config['pilot_timeout_seconds'],cache_root,
                           {'pilot_unit':prepared['pilot_unit'],'pilot_query':prepared['pilot_query']})
            state['pilot']=pilot
        scopes={}
        for key,payload in prepared['payloads'].items():
            if config['mode']=='live':
                limit=config['history_build_timeout_seconds'] if len(payload['units'])==52 else config['single_build_timeout_seconds']
                built=do_stage(config,folder,origin,payload,'build',started,limit,cache_root)
                state['scopes'][key]={'build':built}
            queried=do_stage(config,folder,origin,payload,'query',started,config['query_timeout_seconds'],cache_root)
            state['scopes'].setdefault(key,{})['query']=queried;scopes[key]=queried
            if header and queried['runtime']!=header['runtime']:raise ProbeError('runtime','runtime_mismatch')
        rows,metrics,gold=assess(config,prepared,scopes);state['evaluation']=metrics
        if config['mode']=='replay' and (native_files(origin/'native')!=header['native_files'] or native_files(cache_root)!=header['provider_files']):
            raise ProbeError('cache','replay_modified_cache')
        manifest={'status':'complete','descriptor':prepared['descriptor'],'runtime':next(iter(scopes.values()))['runtime'],
                  'native_files':native_files(origin/'native'),'provider_files':native_files(cache_root)}
        write_json(folder/'graph_manifest.json',manifest)
        write_json(folder/'unit_mapping.json',{key:p['units'] for key,p in prepared['payloads'].items()})
        write_json(folder/'native_storage_audit.json',{key:q['audit'] for key,q in scopes.items()})
        write_json(folder/'native_queries.json',{q['task_id']:q for s in scopes.values() for q in s['queries']})
        analysis=failure_analysis(rows,gold);check_deadline(config,started);state['status']='complete'
    except ProbeError as error:state.update(status='error',sanitized_error=error.record(),evaluation=None);rows=[]
    except Exception as error:
        state.update(status='error',sanitized_error=ProbeError('pipeline','unexpected_error').record(),error_type=type(error).__name__,evaluation=None);rows=[]
    actual=Journal(cache_root,config,config['mode']).summary()
    actual['new_chat_requests']=actual['chat_requests'] if config['mode']=='live' else 0
    actual['new_embedding_requests']=actual['embedding_requests'] if config['mode']=='live' else 0
    state['requests']=actual;state['attempt_count']=actual['new_chat_requests']+actual['new_embedding_requests']
    state['exit_code']=0 if state['status']=='complete' else 2
    try:
        if state['evaluation'] is not None:
            with (folder/'results.jsonl').open('x',encoding='utf-8') as handle:
                for row in rows:handle.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            write_json(folder/'evaluation.json',metrics)
            with (folder/'failure-analysis.md').open('x',encoding='utf-8') as handle:handle.write(analysis)
        report=build_report(state,rows)
        if state['status']=='complete':check_deadline(config,started)
        with (folder/'report.md').open('x',encoding='utf-8') as handle:handle.write(report)
        if state['status']=='complete':check_deadline(config,started)
        state['elapsed_ms']=round((time.monotonic()-started)*1000,3);write_json(folder/'summary.json',state)
    except (OSError,ValueError,TypeError):raise ProbeError('output','output_error') from None
    return state


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True)
    parser.add_argument('--mode',choices=['live','replay']);parser.add_argument('--graph-run')
    args=parser.parse_args(argv)
    try:
        config=read_json(args.config,'config')
        if args.mode is not None:config['mode']=args.mode
        if args.graph_run is not None:config['graph_run']=args.graph_run
        state=run(config)
    except ProbeError as error:print(str(error),file=sys.stderr);return 2
    print(f"status={state['status']} attempts={state['attempt_count']} output={state['output_dir']}")
    if state['sanitized_error']:print(json.dumps(state['sanitized_error']),file=sys.stderr)
    return state['exit_code']


if __name__=='__main__':raise SystemExit(main())
