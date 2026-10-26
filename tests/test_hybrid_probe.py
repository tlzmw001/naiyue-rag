import importlib
import json
import socket
from pathlib import Path

import pytest
from vector_fixtures import config, vector


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args,**kwargs):raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbid)
    monkeypatch.setattr(socket.socket,'connect_ex',forbid)
    monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY',raising=False)


@pytest.fixture
def mod():return importlib.import_module('experiments.hybrid_probe')


def setup_run(tmp_path):
    from experiments.vector_index import load_corpus,write_index,load_index,search,pack_evidence
    from experiments.vector_eval import load_queries,load_labels,evaluate
    cfg=config(tmp_path);base=tmp_path/'a1';base.mkdir()
    data=load_corpus(cfg['corpus_run'],cfg['dataset']);queries=load_queries(cfg['tasks'],data)
    write_index(base,data,queries,[vector(i) for i in range(52)],[vector(i) for i in range(4)],cfg)
    index=load_index(base,data['fingerprint'],cfg);results=[]
    for q in queries:
        ranked=search(index,index['query_vectors'][q['task_id']],q['scope_ids'],q['exclude_ids'],20)
        results.append({**q,**ranked,**pack_evidence(ranked['candidates'],8000),
                        'index_id':index['index_id'],'elapsed_ms':0})
    (base/'summary.json').write_text(json.dumps({'status':'complete'}))
    (base/'results.jsonl').write_text('\n'.join(json.dumps(r) for r in results)+'\n')
    (base/'evaluation.json').write_text(json.dumps([evaluate(r,data,load_labels(cfg['tasks'],data)) for r in results]))
    return {k:cfg[k] for k in ['dataset','corpus_run','tasks','endpoint','model','dimensions','candidate_k',
                              'max_context_chars','deadline_seconds']} | {
        'mode':'build','vector_run':str(base),'keyword_run':None,'output_root':str(tmp_path/'a2'),
        'bm25_k1':1.5,'bm25_b':.75,'bm25_method':'lucene','tokenizer_policy':'zh-search-ascii-ident-v1',
        'backend':'numpy','rrf_k':60}


def test_complete_scope_native_reload_and_replay(mod,tmp_path):
    cfg=setup_run(tmp_path);state=mod.run(cfg)
    assert state['status']=='complete' and state['attempt_count']==0
    assert state['network_attempts'] is None  # Unmonitored library call must not invent zero.
    folder=Path(state['output_dir']);results=[json.loads(line) for line in (folder/'results.jsonl').read_text().splitlines()]
    assert len(results)==4
    q3=next(r for r in results if r['task_id']=='Q03')
    assert q3['dense']['compared_count']==q3['sparse']['compared_count']==10
    assert all(u['document_id']=='MOCK-CASE-001' for u in q3['union_candidates'])
    for row in results:
        for route in ['dense','sparse','hybrid']:
            assert row[route]['context_characters']<=8000 and row[route]['answerability']=='unknown'
    second=mod.run(dict(cfg,mode='replay',keyword_run=str(folder)))
    assert second['status']=='complete'
    replay=Path(second['output_dir'])
    assert json.loads((folder/'evaluation.json').read_text())==json.loads((replay/'evaluation.json').read_text())
    old=[{k:v for k,v in r.items() if k not in ('timings_ms','elapsed_ms')} for r in results]
    new=[{k:v for k,v in json.loads(line).items() if k not in ('timings_ms','elapsed_ms')}
         for line in (replay/'results.jsonl').read_text().splitlines()]
    assert old==new


@pytest.mark.parametrize('fault',['baseline','query','evaluation','keyword-cache'])
def test_mismatch_stops_without_success(mod,tmp_path,fault):
    cfg=setup_run(tmp_path)
    if fault=='keyword-cache':
        first=mod.run(cfg);p=Path(first['output_dir'])/'keyword_manifest.json';p.write_text('{}')
        cfg.update(mode='replay',keyword_run=first['output_dir'])
    elif fault=='baseline':(Path(cfg['vector_run'])/'results.jsonl').write_text('{}\n')
    elif fault=='evaluation':(Path(cfg['vector_run'])/'evaluation.json').write_text('[]')
    else:
        path=tmp_path/'tasks.json';data=json.loads(Path(cfg['tasks']).read_text());data['tasks'][0]['query']+='changed'
        path.write_text(json.dumps(data));cfg['tasks']=str(path)
    state=mod.run(cfg)
    assert state['status']=='error' and state['attempt_count']==0
    assert state['evaluation'] is None
    assert not (Path(state['output_dir'])/'evaluation.json').exists()


def test_gold_is_only_consumed_after_retrieval(mod,tmp_path,monkeypatch):
    cfg=setup_run(tmp_path);events=[];old_search=mod.keyword_search;old_labels=mod.load_labels
    def search(*args,**kwargs):events.append('search');return old_search(*args,**kwargs)
    def labels(*args,**kwargs):
        assert events.count('search')==4
        events.append('labels');return old_labels(*args,**kwargs)
    monkeypatch.setattr(mod,'keyword_search',search);monkeypatch.setattr(mod,'load_labels',labels)
    assert mod.run(cfg)['status']=='complete' and events[-1]=='labels'


def test_output_write_failure_cannot_leave_complete_marker(mod,tmp_path,monkeypatch):
    cfg=setup_run(tmp_path);original=Path.open
    def fail(path,*args,**kwargs):
        if path.name=='results.jsonl' and 'a2' in path.parts:raise PermissionError('injected')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',fail)
    with pytest.raises(mod.ProbeError,match='output_error'):mod.run(cfg)
    assert not list((tmp_path/'a2').rglob('summary.json'))


def test_deadline_after_index_build(mod,tmp_path,monkeypatch):
    cfg=setup_run(tmp_path);clock=[0.0];old=mod.keyword_write
    def delayed(*args,**kwargs):
        result=old(*args,**kwargs);clock[0]=181.0;return result
    monkeypatch.setattr(mod.time,'monotonic',lambda:clock[0]);monkeypatch.setattr(mod,'keyword_write',delayed)
    state=mod.run(cfg)
    assert state['status']=='error' and state['sanitized_error']['category']=='deadline_exceeded'


def test_cli_observes_zero_network_and_requires_no_key(mod,tmp_path,capsys):
    cfg=setup_run(tmp_path)
    args=[part for key,value in cfg.items() if value is not None for part in ['--'+key.replace('_','-'),str(value)]]
    assert mod.main(args)==0
    state=json.loads(next((tmp_path/'a2').glob('*/summary.json')).read_text())
    assert state['network_attempts']==0 and state['attempt_count']==0
    assert 'network_attempts=0' in capsys.readouterr().out


def test_deadline_during_reporting_never_marks_complete(mod,tmp_path,monkeypatch):
    cfg=setup_run(tmp_path);clock=[0.0];original=mod.build_report
    monkeypatch.setattr(mod.time,'monotonic',lambda:clock[0])
    def delayed(*args,**kwargs):
        report=original(*args,**kwargs);clock[0]=181.0;return report
    monkeypatch.setattr(mod,'build_report',delayed)
    with pytest.raises(mod.ProbeError,match='deadline_exceeded'):mod.run(cfg)
    assert not list((tmp_path/'a2').rglob('summary.json'))
