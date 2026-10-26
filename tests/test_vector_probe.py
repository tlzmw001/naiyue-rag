import importlib
import json
import socket
from pathlib import Path

import pytest
from vector_fixtures import config,response


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*a,**k):raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbid)
    monkeypatch.setattr(socket.socket,'connect_ex',forbid)
    monkeypatch.setenv('NAIYUE_RAG_ZHIPU_API_KEY','offline-secret-sentinel')


@pytest.fixture
def mod():return importlib.import_module('experiments.vector_probe')


def fake_live(mod,monkeypatch):
    from experiments import vector_embedding
    monkeypatch.setattr(vector_embedding,'send_batch',lambda cfg,texts,key:response(len(texts)))
    monkeypatch.setattr(mod,'supervise',lambda job,started:vector_embedding.run_worker(job,lambda state:None))


def test_live_reload_scoped_query_and_keyless_replay(mod,tmp_path,monkeypatch):
    fake_live(mod,monkeypatch);cfg=config(tmp_path)
    first=mod.run(cfg)
    assert first['status']=='complete' and first['attempt_count']==5
    folder=Path(first['output_dir'])
    results=[json.loads(line) for line in (folder/'results.jsonl').read_text().splitlines()]
    assert len(results)==4 and all(r['context_characters']<=8000 for r in results)
    scoped=next(r for r in results if r['task_id']=='Q03')
    assert scoped['compared_count']==10
    assert all(r['document_id']=='MOCK-CASE-001' for r in scoped['candidates'])
    assert 'offline-secret-sentinel' not in (folder/'report.md').read_text()
    cfg.update(mode='replay',replay_run=str(folder));monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY')
    def no_supervisor(*a):raise AssertionError('replay must not start network worker')
    monkeypatch.setattr(mod,'supervise',no_supervisor)
    second=mod.run(cfg);replayed=Path(second['output_dir'])
    assert second['attempt_count']==0 and second['estimated_cost_cny']==0
    old=[{k:v for k,v in r.items() if k!='elapsed_ms'} for r in results]
    new=[{k:v for k,v in r.items() if k!='elapsed_ms'} for r in map(json.loads,(replayed/'results.jsonl').read_text().splitlines())]
    assert old==new
    assert json.loads((folder/'evaluation.json').read_text())==json.loads((replayed/'evaluation.json').read_text())


def test_replay_query_change_fails_without_network(mod,tmp_path,monkeypatch):
    fake_live(mod,monkeypatch);cfg=config(tmp_path);first=mod.run(cfg)
    data=json.loads(Path(cfg['tasks']).read_text());data['tasks'][0]['query']+=' changed'
    path=tmp_path/'changed.json';path.write_text(json.dumps(data))
    cfg.update(mode='replay',replay_run=first['output_dir'],tasks=str(path))
    result=mod.run(cfg)
    assert result['status']=='error' and result['attempt_count']==0
    assert result['sanitized_error']['category']=='cache_mismatch'


def test_output_conflict_and_failure_marker(mod,tmp_path,monkeypatch):
    fake_live(mod,monkeypatch);cfg=config(tmp_path)
    monkeypatch.setattr(mod,'new_run_id',lambda:'existing');(tmp_path/'existing').mkdir()
    marker=tmp_path/'existing/report.md';marker.write_text('user work')
    with pytest.raises(mod.ProbeError,match='output_error'):mod.run(cfg)
    assert marker.read_text()=='user work'


def test_cli_requires_key_before_worker(mod,tmp_path,monkeypatch,capsys):
    cfg=config(tmp_path);monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY')
    args=[part for key,value in cfg.items() if value is not None for part in ['--'+key.replace('_','-'),str(value)]]
    assert mod.main(args)==2
    assert 'missing_key' in capsys.readouterr().err


def test_worker_failure_is_reported_not_fake_evaluation(mod,tmp_path,monkeypatch):
    from experiments.vector_embedding import initial_state
    cfg=config(tmp_path);state=initial_state(cfg)
    state.update(status='error',attempt_count=1,estimated_cost_cny=None,
                 sanitized_error={'stage':'http','category':'http_error','http_status':429})
    monkeypatch.setattr(mod,'supervise',lambda *a:state)
    result=mod.run(cfg);folder=Path(result['output_dir'])
    assert result['status']=='error' and result['evaluation'] is None
    assert not (folder/'evaluation.json').exists()


def test_deadline_after_worker_stops_query_and_evaluation(mod,tmp_path,monkeypatch):
    import shutil
    fake_live(mod,monkeypatch);cfg=config(tmp_path)
    original=mod.run(cfg);source=Path(original['output_dir']);clock=[0.0]
    def delayed(job,started):
        for name in ['index_vectors.jsonl','query_vectors.json','index_manifest.json']:
            shutil.copyfile(source/name,Path(job['folder'])/name)
        clock[0]=181.0
        return {**original,'status':'complete'}
    monkeypatch.setattr(mod,'supervise',delayed)
    monkeypatch.setattr(mod.time,'monotonic',lambda:clock[0])
    result=mod.run(cfg)
    assert result['status']=='error' and result['evaluation'] is None
    assert result['sanitized_error']['category']=='deadline_exceeded'
    assert result['attempt_count']==5 and result['estimated_cost_cny']==original['estimated_cost_cny']


def test_output_write_error_not_completion(mod,tmp_path,monkeypatch):
    fake_live(mod,monkeypatch);original=Path.open
    def fail(path,*args,**kwargs):
        if path.name=='results.jsonl':raise PermissionError('injected')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',fail)
    with pytest.raises(mod.ProbeError,match='output_error'):mod.run(config(tmp_path))
    assert not list(tmp_path.rglob('summary.json'))
