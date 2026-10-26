import importlib
import json
from pathlib import Path

import pytest


def settings(tmp_path):
    from vector_fixtures import config
    root = Path(__file__).resolve().parents[1]
    return {**config(tmp_path), 'mode': 'build', 'vector_run': str(root/'data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e'),
            'runtime_python': str(root/'.venv-lightrag/bin/python'),
            'runtime_lock': str(root/'requirements-lightrag-runtime.lock.txt'), 'sdk_version': '1.5.7',
            'tokenizer_cache': str(root/'data/runtime/lightrag/o200k-cache'), 'tokenizer_encoding': 'o200k_base',
            'max_total_tokens': 32768, 'cosine_threshold': -1.0, 'worker_timeout_seconds': 60,
            'b0_run': None, 'output_root': str(tmp_path/'b0')}


@pytest.fixture
def mod(): return importlib.import_module('experiments.lightrag_probe')


def test_actual_full_build_replay_and_scope(mod, tmp_path):
    cfg = settings(tmp_path); state = mod.run(cfg)
    assert state['status'] == 'complete', state
    assert state['attempt_count'] == state['network_attempts'] == state['llm_calls'] == 0
    folder = Path(state['output_dir'])
    rows = [json.loads(s) for s in (folder/'results.jsonl').read_text().splitlines()]
    assert [r['B0']['compared_count'] for r in rows] == [52,52,10,52]
    assert all(r['B0']['context_characters'] <= 8000 and r['B0']['answerability'] == 'unknown' for r in rows)
    replay = mod.run(dict(cfg, mode='replay', b0_run=str(folder)))
    assert replay['status'] == 'complete', replay
    other = Path(replay['output_dir'])
    assert (folder/'evaluation.json').read_bytes() == (other/'evaluation.json').read_bytes()
    assert (folder/'results.jsonl').read_bytes() == (other/'results.jsonl').read_bytes()


@pytest.mark.parametrize('fault', ['query', 'baseline', 'lock', 'tokenizer'])
def test_failed_preflight_has_no_evaluation(mod, tmp_path, fault):
    cfg = settings(tmp_path)
    if fault == 'query':
        p=tmp_path/'tasks.json';data=json.loads(Path(cfg['tasks']).read_text());data['tasks'][0]['query']+='changed'
        p.write_text(json.dumps(data));cfg['tasks']=str(p)
    elif fault == 'baseline': cfg['vector_run'] = str(tmp_path/'missing')
    elif fault == 'lock': cfg['runtime_lock'] = str(tmp_path/'missing.lock')
    else: cfg['tokenizer_cache'] = str(tmp_path/'missing-tokens')
    state = mod.run(cfg)
    assert state['status'] == 'error' and state['evaluation'] is None
    assert not (Path(state['output_dir'])/'evaluation.json').exists()


def test_gold_read_only_after_all_retrieval(mod, tmp_path, monkeypatch):
    events=[];old=mod.load_labels;worker=mod.run_scope
    def scope(*a,**k):
        result=worker(*a,**k);events.append('scope');return result
    def labels(*a,**k):
        assert events==['scope','scope'];return old(*a,**k)
    monkeypatch.setattr(mod,'run_scope',scope);monkeypatch.setattr(mod,'load_labels',labels)
    assert mod.run(settings(tmp_path))['status']=='complete'


def test_report_deadline_cannot_mark_complete(mod, tmp_path, monkeypatch):
    cfg=settings(tmp_path);clock=[0.0];old=mod.build_report
    monkeypatch.setattr(mod.time,'monotonic',lambda:clock[0])
    def delayed(*a,**k):
        result=old(*a,**k);clock[0]=181.;return result
    monkeypatch.setattr(mod,'build_report',delayed)
    with pytest.raises(mod.ProbeError,match='deadline_exceeded'):mod.run(cfg)
    assert not list(Path(cfg['output_root']).rglob('summary.json'))


def test_failed_worker_external_attempts_remain_observable(mod, tmp_path, monkeypatch):
    cfg=settings(tmp_path)
    def failing(config,payload,native_root,scratch,started,build):
        p=Path(scratch)/'build';p.mkdir(parents=True)
        (p/'worker-result.json').write_text(json.dumps({'status':'error','trace':{'network_attempts':1,'llm_calls':1}}))
        raise mod.ProbeError('network','network_forbidden')
    monkeypatch.setattr(mod,'run_scope',failing)
    state=mod.run(cfg)
    assert state['status']=='error'
    assert state['network_attempts']==1 and state['llm_calls']==1


@pytest.mark.parametrize('fault',['manifest','native'])
def test_corrupt_replay_never_rebuilds(mod,tmp_path,fault,monkeypatch):
    cfg=settings(tmp_path);state=mod.run(cfg);assert state['status']=='complete'
    folder=Path(state['output_dir'])
    if fault=='manifest':(folder/'index_manifest.json').write_text('{}')
    else:next((folder/'native').rglob('vdb_chunks*.json')).write_text('{}')
    def forbidden(*a,**k):raise AssertionError('replay attempted to rebuild/query corrupt stores')
    monkeypatch.setattr(mod,'run_scope',forbidden)
    replay=mod.run(dict(cfg,mode='replay',b0_run=str(folder)))
    assert replay['status']=='error' and replay['evaluation'] is None
    assert not (Path(replay['output_dir'])/'native').exists()


def test_output_failure_leaves_no_complete_summary(mod,tmp_path,monkeypatch):
    cfg=settings(tmp_path);old=Path.open
    def fail(path,*args,**kwargs):
        if path.name=='evaluation.json' and 'b0' in path.parts:raise PermissionError('injected IO fault')
        return old(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',fail)
    with pytest.raises(mod.ProbeError,match='output_error'):mod.run(cfg)
    assert not list(Path(cfg['output_root']).rglob('summary.json'))
