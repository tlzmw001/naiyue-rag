import importlib
import json
import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args,**kwargs):raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbid);monkeypatch.setattr(socket.socket,'connect_ex',forbid)
    monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY',raising=False)


@pytest.fixture
def mod():return importlib.import_module('experiments.relation_probe')


def setup_run(tmp_path):
    from test_hybrid_probe import setup_run as a2_setup
    from experiments.hybrid_probe import run
    cfg=a2_setup(tmp_path);a2=run(cfg);assert a2['status']=='complete'
    return {**cfg,'a2_run':a2['output_dir'],'mode':'build','relation_run':None,'output_root':str(tmp_path/'a3'),
            'relation_policy':'explicit-doc-v1','seed_k':5,'max_seed_documents':3,'max_hops':2,
            'max_related_documents':8,'per_document_k':4,'relation_k':20,'max_graph_nodes':64,'max_edge_visits':128}


def test_actual_wiring_and_replay_and_q03_scope(mod,tmp_path):
    cfg=setup_run(tmp_path);state=mod.run(cfg)
    assert state['status']=='complete' and state['attempt_count']==0 and state['network_attempts'] is None
    folder=Path(state['output_dir']);rows=[json.loads(s) for s in (folder/'results.jsonl').read_text().splitlines()]
    q3=next(r for r in rows if r['task_id']=='Q03')
    assert q3['expansion']['related_documents']==[]
    assert q3['A2']['hybrid']==q3['A3']
    assert all(r['A3']['context_characters']<=8000 and r['A3']['answerability']=='unknown' for r in rows)
    replay=mod.run(dict(cfg,mode='replay',relation_run=str(folder)))
    assert replay['status']=='complete'
    other=Path(replay['output_dir'])
    assert (folder/'evaluation.json').read_bytes()==(other/'evaluation.json').read_bytes()
    def stable(rows):return [{k:v for k,v in r.items() if k!='timings_ms'} for r in rows]
    assert stable(rows)==stable([json.loads(s) for s in (other/'results.jsonl').read_text().splitlines()])


@pytest.mark.parametrize('fault',['a2-results','a2-evaluation','query','relation-cache'])
def test_corrupt_baseline_or_cache_fails_not_fakes_success(mod,tmp_path,fault):
    cfg=setup_run(tmp_path)
    if fault=='relation-cache':
        first=mod.run(cfg);(Path(first['output_dir'])/'relations/relation_manifest.json').write_text('{}')
        cfg.update(mode='replay',relation_run=first['output_dir'])
    elif fault=='a2-results':(Path(cfg['a2_run'])/'results.jsonl').write_text('{}\n')
    elif fault=='a2-evaluation':(Path(cfg['a2_run'])/'evaluation.json').write_text('[]')
    else:
        p=tmp_path/'tasks.json';data=json.loads(Path(cfg['tasks']).read_text());data['tasks'][0]['query']+='changed'
        p.write_text(json.dumps(data));cfg['tasks']=str(p)
    state=mod.run(cfg)
    assert state['status']=='error' and state['evaluation'] is None and state['attempt_count']==0
    assert not (Path(state['output_dir'])/'evaluation.json').exists()


def test_gold_only_after_all_relation_retrieval(mod,tmp_path,monkeypatch):
    cfg=setup_run(tmp_path);events=[];old=mod.build_route;labels=mod.load_labels
    def route(*a,**k):events.append('route');return old(*a,**k)
    def read(*a,**k):
        assert events==['route']*4
        return labels(*a,**k)
    monkeypatch.setattr(mod,'build_route',route);monkeypatch.setattr(mod,'load_labels',read)
    assert mod.run(cfg)['status']=='complete'


def test_deadline_in_report_or_write_failure_never_marks_complete(mod,tmp_path,monkeypatch):
    cfg=setup_run(tmp_path);clock=[0.0];original=mod.build_report
    monkeypatch.setattr(mod.time,'monotonic',lambda:clock[0])
    def delayed(*a,**k):
        text=original(*a,**k);clock[0]=181.0;return text
    monkeypatch.setattr(mod,'build_report',delayed)
    with pytest.raises(mod.ProbeError,match='deadline_exceeded'):mod.run(cfg)
    assert not list((tmp_path/'a3').rglob('summary.json'))


def test_output_write_failure(mod,tmp_path,monkeypatch):
    cfg=setup_run(tmp_path);original=Path.open
    def fail(path,*args,**kwargs):
        if path.name=='results.jsonl' and 'a3' in path.parts:raise PermissionError('injected')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',fail)
    with pytest.raises(mod.ProbeError,match='output_error'):mod.run(cfg)
    assert not list((tmp_path/'a3').rglob('summary.json'))


def test_cli_keyless_and_observed_network_zero(mod,tmp_path):
    cfg=setup_run(tmp_path);cfg.pop('keyword_run')
    argv=[p for k,v in cfg.items() if v is not None for p in ['--'+k.replace('_','-'),str(v)]]
    assert mod.main(argv)==0
    state=json.loads(next((tmp_path/'a3').glob('*/summary.json')).read_text())
    assert state['network_attempts']==0
