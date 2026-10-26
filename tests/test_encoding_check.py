"""Bounded checkpoint protocol and parent process control, no live requests."""
import copy
import json
import os
from pathlib import Path
import subprocess
import pytest
import yaml
from naiyue_rag.validation import encoding_check as check
from naiyue_rag.validation.check_report import CheckError,Ledger,Journal,read_journal
from test_encoding_settings import config_data
from test_sparse_encoding_settings import sparse_config
from test_document_chunker import offline

PRIVATE='SYNTHETIC_PRIVATE'
NAME='TEST_CHECK_KEY'


def setup_job(tmp_path,monkeypatch,**runtime):
    root=tmp_path/'project';root.mkdir()
    source=root/'examples/encoding-check';source.mkdir(parents=True)
    for name in ['feature.md','threshold.md']:
        origin=Path('examples/encoding-check')/name
        (source/name).write_text(origin.read_text())
    raw=config_data();raw['runtime'].update(runtime)
    encoding=root/'encoding.yaml';encoding.write_text(yaml.safe_dump(raw))
    sparse=root/'sparse.yaml';sparse.write_text(yaml.safe_dump(dict(sparse_config(root).to_dict(),cache_dir='./cache')))
    (root/'.env').write_text(f'{NAME}={PRIVATE}\n')
    monkeypatch.delenv(NAME,raising=False)
    output=root/'data/validation/run'
    kwargs=dict(project_root=root,key_env=NAME,cleanup_seconds=5,max_checkpoint_bytes=65536,max_checkpoint_records=16)
    return encoding,sparse,output,kwargs


def test_success_uses_isolated_env_and_no_output_pipe(tmp_path,monkeypatch):
    from naiyue_rag.validation.encoding_worker import run_job
    from test_query_encoding import Dense
    from test_batch_processor import Sparse
    args=setup_job(tmp_path,monkeypatch);seen={}
    class Child:
        returncode=0;stdin=None
        def __init__(self,command,**kwargs):
            seen.update(kwargs);assert command[1:]==['-m','naiyue_rag.validation.encoding_worker']
            assert kwargs['stdout']==kwargs['stderr']==subprocess.DEVNULL
            assert kwargs['env']['NAIYUE_RAG_VALIDATION_KEY']==PRIVATE
            assert 'UNRELATED_SECRET' not in kwargs['env'] and 'OPENAI_API_KEY' not in kwargs['env']
        def communicate(self,input,timeout):
            job=json.loads(input)
            cfg=check.EncodingSettings.from_dict(job['settings'])
            class Provider:
                closed=False
                def close(self):self.closed=True
            provider=Provider()
            monkeypatch.setattr('naiyue_rag.validation.encoding_worker._components',lambda job,key:(provider,Dense(cfg),Sparse(cfg)))
            # Real encoders' task contracts remain active; only Dense/Sparse component bodies are fakes here.
            dense=Dense(cfg)
            def encode(batch,*,remaining_seconds):
                from naiyue_rag.encoding.validation import ProviderBatchResult
                from naiyue_rag.encoding.execution_report import new_report
                report=new_report();report.update(attempted_requests=1,http_status=200)
                return ProviderBatchResult([[1.,2.,3.] for i in batch],[i.item_id for i in batch],
                    [i.embedding_text_sha256 for i in batch],cfg.model_space_id,'synthetic-model','simulated',
                    dict(prompt_tokens=7,total_tokens=7),'known'),report
            dense.encode_batch=encode
            monkeypatch.setattr('naiyue_rag.validation.encoding_worker._components',lambda job,key:(provider,dense,Sparse(cfg)))
            assert run_job(job,PRIVATE)==0
            return None,None
        def poll(self):return self.returncode
    monkeypatch.setenv('UNRELATED_SECRET',PRIVATE);monkeypatch.setenv('OPENAI_API_KEY',PRIVATE)
    monkeypatch.setattr(check.subprocess,'Popen',Child)
    result=check.run_check(*args[:3],**args[3])
    assert result['status']=='complete' and result['attempted_requests']==2
    assert result['usage']['total_tokens']==14 and result['reaped']
    assert result['validation']['documents']['count']==2 and result['validation']['query']['count']==1
    assert PRIVATE not in json.dumps(result)+(args[2]/'checkpoints.jsonl').read_text()
    assert (args[2]/'cache').exists() is False  # injected Sparse does not initialize native resources
    assert (args[2]/'report.json').is_file()

@pytest.mark.parametrize('fault',['missing-key','budget','existing','outside','symlink','bad-limit'])
def test_preflight_never_starts_child(tmp_path,monkeypatch,fault):
    args=list(setup_job(tmp_path,monkeypatch,max_requests=1 if fault=='budget' else 100))
    if fault=='missing-key':(args[3]['project_root']/'.env').write_text('OTHER=ignored')
    elif fault=='existing':args[2].mkdir(parents=True)
    elif fault=='outside':args[2]=tmp_path/'outside'
    elif fault=='symlink':
        target=args[3]['project_root']/'elsewhere';target.mkdir()
        (args[3]['project_root']/'data').symlink_to(target,target_is_directory=True)
    elif fault=='bad-limit':args[3]['cleanup_seconds']=True
    monkeypatch.setattr(check.subprocess,'Popen',lambda *a,**k:pytest.fail('no process permitted'))
    with pytest.raises(CheckError):check.run_check(*args[:3],**args[3])

@pytest.mark.parametrize('fault',['spawn','timeout','kill','reap','crash'])
def test_supervisor_failure_is_bounded_and_safe(tmp_path,monkeypatch,fault):
    args=setup_job(tmp_path,monkeypatch);calls=[]
    class Child:
        returncode=-9;stdin=None
        def __init__(self,*a,**k):
            if fault=='spawn':raise OSError(PRIVATE)
        def communicate(self,input,timeout):
            if fault=='crash':return None,None
            raise subprocess.TimeoutExpired('worker',timeout)
        def poll(self):return None if fault!='crash' else -9
        def kill(self):
            calls.append('kill')
            if fault=='kill':raise OSError(PRIVATE)
        def wait(self,timeout):
            calls.append(('wait',timeout))
            if fault=='reap':raise subprocess.TimeoutExpired('worker',timeout)
            return -9
    monkeypatch.setattr(check.subprocess,'Popen',Child)
    result=check.run_check(*args[:3],**args[3])
    assert result['status']=='failed' and PRIVATE not in json.dumps(result)
    if fault in ('timeout','kill','reap'):assert ('wait',5) in calls
    if fault=='reap':assert result['cleanup_error']=='worker_reap_timeout' and not result['reaped']
    if fault=='kill':assert result['cleanup_error']=='worker_kill_failed'


def test_journal_limits_and_incomplete_tail_keep_only_valid_prefix(tmp_path,monkeypatch):
    args=setup_job(tmp_path,monkeypatch)
    job,key,prep=check.prepare_job(*args[:3],**args[3])
    journal=Journal(job)
    journal.emit('worker_started',dict(model_space_id=job['model_space_id'],representation_id=job['representation_id'],tokenizer_id='a'*64,dimensions=3))
    journal.emit('task_started',dict(stage='documents'))
    journal.emit('request_reserved',dict(ordinal=1,stage='documents',input_count=2,input_fingerprint=job['plans']['documents']['input_fingerprint']))
    with (Path(job['run_dir'])/'checkpoints.jsonl').open('ab') as f:f.write(b'{"seq":4')
    ledger,error,truncated=read_journal(job)
    assert truncated and error is None and len(ledger.reservations)==1
    assert ledger.summary()['attempted_requests'] is None

@pytest.mark.parametrize('fault',['sequence','extra-field','identity','final-first','duplicate-start'])
def test_protocol_rejects_bad_events_without_payload(tmp_path,monkeypatch,fault):
    args=setup_job(tmp_path,monkeypatch);job,_,_=check.prepare_job(*args[:3],**args[3])
    ledger=Ledger(job)
    data=dict(model_space_id=job['model_space_id'],representation_id=job['representation_id'],tokenizer_id='a'*64,dimensions=3)
    event=dict(seq=1,run_id=job['run_id'],type='worker_started',data=data)
    if fault=='sequence':event['seq']=2
    elif fault=='extra-field':event['secret']=PRIVATE
    elif fault=='identity':event['data']['model_space_id']='0'*64
    elif fault=='final-first':event['type']='final';event['data']=dict(status='complete',stage='cleanup',error_code=None)
    else:ledger.accept(event);event['seq']=2
    with pytest.raises(CheckError,match='checkpoint_protocol_invalid'):ledger.accept(event)
    assert len(ledger.reservations)==0


def test_journal_write_failure_stops_before_execution(tmp_path,monkeypatch):
    args=setup_job(tmp_path,monkeypatch);job,_,_=check.prepare_job(*args[:3],**args[3]);journal=Journal(job)
    monkeypatch.setattr('naiyue_rag.validation.check_report.os.fsync',lambda fd:(_ for _ in ()).throw(OSError(PRIVATE)))
    with pytest.raises(CheckError,match='checkpoint_write_failed'):journal.emit('worker_started',dict(
        model_space_id=job['model_space_id'],representation_id=job['representation_id'],tokenizer_id='a'*64,dimensions=3))
