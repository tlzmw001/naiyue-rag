import importlib
import json
from pathlib import Path

import pytest
from test_graph_transport import settings


@pytest.fixture
def mod():return importlib.import_module('experiments.graph_probe')


def test_preflight_preserves_baselines_labels_not_passed_to_workers(mod,tmp_path):
    prepared=mod.prepare(settings(tmp_path))
    assert len(prepared['corpus']['units'])==52 and len(prepared['payloads'])==2
    assert sorted(len(p['units']) for p in prepared['payloads'].values())==[10,52]
    assert 'candidate_required_evidence' not in str(prepared['payloads'])
    assert prepared['pilot_unit']['document_id']=='MOCK-CASE-001' and prepared['pilot_unit']['case_id']=='TC-01'


def test_missing_key_fails_before_spawning(mod,tmp_path,monkeypatch):
    cfg=settings(tmp_path);monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY',raising=False)
    def forbidden(*a,**k):raise AssertionError('spawned without key')
    monkeypatch.setattr(mod,'invoke',forbidden)
    state=mod.run(cfg)
    assert state['status']=='error' and state['sanitized_error']['category']=='missing_key'
    assert state['evaluation'] is None and state['requests']['chat_requests']==0


@pytest.mark.parametrize('fault',['query','b0','a2','sdk'])
def test_corrupt_reference_rejected_before_live_requests(mod,tmp_path,fault):
    cfg=settings(tmp_path)
    if fault=='query':
        p=tmp_path/'tasks.json';d=json.loads(Path(cfg['tasks']).read_text());d['tasks'][0]['query']+='changed'
        p.write_text(json.dumps(d));cfg['tasks']=str(p)
    elif fault=='sdk':cfg['sdk_version']='1.5.8'
    else:cfg[fault+'_run']=str(tmp_path/'missing')
    with pytest.raises(mod.ProbeError):mod.prepare(cfg)


def test_full_native_sdk_with_fake_provider_and_keyless_parent_replay(mod,tmp_path,monkeypatch):
    from test_graph_worker import fake_run
    cfg=settings(tmp_path);monkeypatch.setenv('NAIYUE_RAG_ZHIPU_API_KEY','test-sentinel')
    def invoke(job,cwd,timeout):return fake_run(job,Path(cwd))
    monkeypatch.setattr(mod,'invoke',invoke)
    built=mod.run(cfg);assert built['status']=='complete',built
    root=Path(built['output_dir']);rows=[json.loads(s) for s in (root/'results.jsonl').read_text().splitlines()]
    assert [r['B1']['compared_count'] for r in rows]==[52,52,10,52]
    assert all(r['B1']['context_characters']<=8000 for r in rows)
    assert all(u['score'] is None for r in rows for u in r['B1']['candidates'])
    monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY')
    replay=mod.run(dict(cfg,mode='replay',graph_run=str(root)))
    assert replay['status']=='complete',replay
    other=Path(replay['output_dir'])
    assert (root/'evaluation.json').read_bytes()==(other/'evaluation.json').read_bytes()
    assert (root/'results.jsonl').read_bytes()==(other/'results.jsonl').read_bytes()


def test_report_deadline_and_io_never_create_complete(mod,tmp_path,monkeypatch):
    from test_graph_worker import fake_run
    cfg=settings(tmp_path);monkeypatch.setenv('NAIYUE_RAG_ZHIPU_API_KEY','test-sentinel')
    monkeypatch.setattr(mod,'invoke',lambda job,cwd,timeout:fake_run(job,Path(cwd)))
    original=mod.build_report;clock=[0.0]
    monkeypatch.setattr(mod.time,'monotonic',lambda:clock[0])
    def slow(*a):text=original(*a);clock[0]=3601.;return text
    monkeypatch.setattr(mod,'build_report',slow)
    with pytest.raises(mod.ProbeError,match='deadline_exceeded'):mod.run(cfg)
    assert not list(Path(cfg['output_root']).rglob('summary.json'))
