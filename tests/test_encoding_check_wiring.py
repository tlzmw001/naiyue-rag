"""Real M1/M2/M3 components under mock HTTP, plus actual child termination."""
import copy
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import pytest
import httpx
from naiyue_rag.validation import encoding_check as parent,encoding_worker as worker
from naiyue_rag.validation.check_report import CheckError,Journal,Ledger,read_journal
from naiyue_rag.core.errors import EmbeddingExecutionError,EncodingError
from naiyue_rag.encoding.execution_report import new_report
from test_encoding_check import setup_job,PRIVATE
from test_openai_embedding import safe_ambient,payload
from test_document_chunker import offline


def mock_http(monkeypatch,fault=None):
    requests=[]
    def handle(request):
        wire=json.loads(request.content);requests.append(wire)
        assert request.headers['authorization']=='Bearer '+PRIVATE
        if fault=='http':return httpx.Response(429,json={'error':PRIVATE})
        result=payload(len(wire['input']));result['usage']={'prompt_tokens':7,'total_tokens':7}
        if fault=='missing-usage':result.pop('usage')
        return httpx.Response(200,json=result)
    monkeypatch.setattr(httpx,'HTTPTransport',lambda **kwargs:httpx.MockTransport(handle))
    return requests


def execute_in_process(monkeypatch,returncode=None):
    class Child:
        stdin=None
        def __init__(self,*args,**kwargs):self.key=kwargs['env'][parent.KEY_NAME];self.returncode=None
        def communicate(self,input,timeout):
            self.returncode=worker.run_job(json.loads(input),self.key) if returncode is None else returncode
            return None,None
    monkeypatch.setattr(parent.subprocess,'Popen',Child)


@pytest.mark.parametrize('fault',[None,'http','sparse','close','sparse-and-close','missing-usage','initialize'])
def test_actual_sdk_sparse_and_parent_reports(tmp_path,monkeypatch,fault,caplog):
    args=setup_job(tmp_path,monkeypatch);requests=mock_http(monkeypatch,fault)
    if fault in ('sparse','sparse-and-close'):
        def fail(*a,**k):raise EncodingError('sparse_encoding_failed')
        monkeypatch.setattr(worker.SparseEncoder,'encode_batch',fail)
    if fault in ('close','sparse-and-close'):
        normal=worker.OpenAICompatibleEmbedding.close
        def fail(self):normal(self);raise OSError(PRIVATE)
        monkeypatch.setattr(worker.OpenAICompatibleEmbedding,'close',fail)
    if fault=='initialize':
        def fail(*args):raise OSError(PRIVATE)
        monkeypatch.setattr(worker,'SparseEncoder',fail)
    execute_in_process(monkeypatch)
    report=parent.run_check(*args[:3],**args[3])
    assert PRIVATE not in json.dumps(report)+caplog.text+(args[2]/'checkpoints.jsonl').read_text()
    assert report['protocol_error_code'] is None and not report['checkpoint_truncated']
    if fault in (None,'missing-usage'):
        assert report['status']=='complete' and len(requests)==2 and len(requests[0]['input'])==2 and len(requests[1]['input'])==1
        assert report['attempted_requests']==2 and report['usage']['total_tokens']==(14 if fault is None else None)
        assert report['validation']['documents']['dimensions']==report['validation']['query']['dimensions']==3
        assert report['validation']['query']['tokenizer_id']==report['validation']['documents']['tokenizer_id']==report['tokenizer_id']
        assert report['documents']['usage']['known_total_tokens_sum']==(7 if fault is None else None)
        assert report['client_cleanup']['closed']
        assert (args[2]/'cache').is_dir()
        assert len((args[2]/'checkpoints.jsonl').read_text().splitlines())==11
    else:
        expected={'http':'embedding_http_429','sparse':'sparse_encoding_failed','close':'worker_close_failed',
                  'sparse-and-close':'sparse_encoding_failed','initialize':'worker_initialization_failed'}[fault]
        assert report['status']=='failed' and report['error_code']==expected
        assert len(requests)==(0 if fault=='initialize' else 2 if fault=='close' else 1)
        assert report['usage']['total_tokens']==(14 if fault=='close' else 7 if fault.startswith('sparse') else None)
        if fault in ('close','sparse-and-close'):assert report['client_cleanup']['error_code']=='worker_close_failed'
        if fault in ('sparse','sparse-and-close','http'):assert report['validation']['documents'] is None and report['query'] is None


@pytest.mark.parametrize('fault',['observe-twice','oversize','records','bad-json','duplicate-key','bad-model','after-final','wrong-task-report','unknown-dense'])
def test_corruption_and_unknown_calls_keep_prefix(tmp_path,monkeypatch,fault):
    args=setup_job(tmp_path,monkeypatch);job,_,_=parent.prepare_job(*args[:3],**args[3]);journal=Journal(job)
    journal.emit('worker_started',dict(model_space_id=job['model_space_id'],representation_id=job['representation_id'],tokenizer_id='a'*64,dimensions=3))
    journal.emit('task_started',dict(stage='documents'))
    journal.emit('request_reserved',dict(ordinal=1,stage='documents',**job['plans']['documents']['batches'][0]))
    report=new_report();report.update(attempted_requests=1,http_status=200)
    observation=dict(ordinal=1,report=report,returned_model='synthetic-model',source_kind='simulated',usage=dict(prompt_tokens=7,total_tokens=7),usage_status='known')
    if fault=='bad-model':
        observation['returned_model']=PRIVATE
        with pytest.raises(CheckError):journal.emit('request_observed',observation)
    elif fault!='unknown-dense':journal.emit('request_observed',observation)
    path=Path(job['run_dir'])/'checkpoints.jsonl'
    if fault=='observe-twice':
        with pytest.raises(CheckError):journal.emit('request_observed',observation)
    elif fault=='oversize':job['max_checkpoint_bytes']=100
    elif fault=='records':job['max_checkpoint_records']=2
    elif fault in ('bad-json','duplicate-key'):
        with path.open('ab') as stream:stream.write(b'not-json\n' if fault=='bad-json' else b'{"seq":5,"seq":5}\n')
    elif fault=='after-final':
        journal.emit('cleanup',dict(attempted=True,closed=True,error_code=None))
        journal.emit('final',dict(status='failed',stage='documents',error_code='worker_failed'))
        with path.open('ab') as stream:stream.write(b'{"invalid":"data"}\n')
    elif fault=='wrong-task-report':
        with pytest.raises(CheckError):journal.emit('task_result',dict(stage='documents',report={},summary=None))
    ledger,error,truncated=read_journal(job)
    assert truncated is (fault=='oversize') and PRIVATE not in json.dumps(ledger.summary())
    if fault in ('oversize','records','bad-json','duplicate-key','after-final'):assert error is not None
    else:assert error is None
    if fault in ('bad-model','unknown-dense'):assert ledger.summary()['attempted_requests'] is None
    elif fault not in ('oversize','records'):assert ledger.summary()['attempted_requests']==1 and ledger.summary()['usage']['total_tokens']==7


@pytest.mark.parametrize('failure',['write','read'])
def test_parent_io_failure_is_explicit(tmp_path,monkeypatch,failure):
    args=setup_job(tmp_path,monkeypatch);mock_http(monkeypatch);execute_in_process(monkeypatch)
    if failure=='write':
        normal=parent._write_new
        def fail(path,payload):
            if path.name=='report.json':raise OSError(PRIVATE)
            return normal(path,payload)
        monkeypatch.setattr(parent,'_write_new',fail)
    else:monkeypatch.setattr(parent,'read_journal',lambda job:(Ledger(job),'checkpoint_read_failed',False))
    report=parent.run_check(*args[:3],**args[3])
    assert report['status']=='failed' and PRIVATE not in json.dumps(report)
    if failure=='write':assert report['persistence_error']=='report_write_failed' and report['attempted_requests']==2
    else:assert report['protocol_error_code']=='checkpoint_read_failed' and report['attempted_requests'] is None


def test_checkpoint_failure_prevents_dense_call(tmp_path,monkeypatch):
    args=setup_job(tmp_path,monkeypatch);job,_,_=parent.prepare_job(*args[:3],**args[3]);journal=Journal(job)
    class Dense:
        settings=parent.EncodingSettings.from_dict(job['settings'])
        def encode_batch(self,*a,**k):pytest.fail('checkpoint must precede Dense')
    journal.emit('worker_started',dict(model_space_id=job['model_space_id'],representation_id=job['representation_id'],tokenizer_id='a'*64,dimensions=3))
    journal.emit('task_started',dict(stage='documents'))
    normal=os.fsync
    monkeypatch.setattr(os,'fsync',lambda fd:(_ for _ in ()).throw(OSError(PRIVATE)))
    dense=worker.ObservedDense(Dense(),journal);dense.stage='documents'
    with pytest.raises(CheckError,match='checkpoint_write_failed'):dense.encode_batch([worker.EncodingInput.from_dict(i) for i in job['inputs']],remaining_seconds=5)
    monkeypatch.setattr(os,'fsync',normal)
    assert journal.failed


def test_real_blocking_child_is_killed_reaped_and_keeps_dense_usage(tmp_path,monkeypatch):
    args=setup_job(tmp_path,monkeypatch);real_popen=subprocess.Popen;ready_r,ready_w=os.pipe();seen={}
    # The test substitutes only process construction. Real worker/core/Dense checkpoint logic runs in the child.
    script='''
import json,sys,os,threading
from naiyue_rag.validation import encoding_worker as w
from naiyue_rag.encoding.validation import ProviderBatchResult
from naiyue_rag.encoding.execution_report import new_report
class Provider:
    closed=False
    def close(self):self.closed=True
class Dense:
    def __init__(self,cfg):self.settings=cfg
    def encode_batch(self,items,**kwargs):
        report=new_report();report.update(attempted_requests=1,http_status=200)
        return ProviderBatchResult([[1.,2.,3.] for i in items],[i.item_id for i in items],[i.embedding_text_sha256 for i in items],self.settings.model_space_id,'synthetic-model','simulated',dict(prompt_tokens=7,total_tokens=7),'known'),report
class Sparse:
    tokenizer_id='a'*64
    def __init__(self,cfg):self.encoding_settings=cfg
    def encode_batch(self,items):
        os.write(int(sys.argv[1]),b'R');threading.Event().wait()
job=json.load(sys.stdin)
cfg=w.EncodingSettings.from_dict(job['settings'])
w._components=lambda job,key:(Provider(),Dense(cfg),Sparse(cfg))
sys.exit(w.run_job(job,os.environ.pop(w.KEY_NAME)))
'''
    class Child:
        def __init__(self,command,**kwargs):
            self.process=real_popen([sys.executable,'-c',script,str(ready_w)],pass_fds=(ready_w,),**kwargs)
            seen['process']=self.process
        @property
        def returncode(self):return self.process.returncode
        @property
        def stdin(self):return self.process.stdin
        def communicate(self,input,timeout):
            self.process.stdin.write(input);self.process.stdin.close();self.process.stdin=None
            assert select.select([ready_r],[],[],10)[0], 'child did not reach Sparse boundary'
            assert os.read(ready_r,1)==b'R';seen['ready']=True
            # Exact timeout branch after the readiness handshake, without timing-sensitive sleeps.
            raise subprocess.TimeoutExpired('worker',timeout)
        def poll(self):return self.process.poll()
        def kill(self):return self.process.kill()
        def wait(self,timeout):return self.process.wait(timeout=timeout)
    monkeypatch.setattr(parent.subprocess,'Popen',Child)
    try:
        report=parent.run_check(*args[:3],**args[3])
        assert seen['ready'] and report['error_code']=='worker_deadline_exceeded' and report['kill_requested'] and report['reaped']
        assert seen['process'].poll() is not None and report['attempted_requests']==1 and report['usage']['total_tokens']==7
        assert report['documents'] is None and report['validation']['documents'] is None
    finally:
        os.close(ready_r);os.close(ready_w)
        process=seen.get('process')
        if process is not None and process.poll() is None:process.kill();process.wait(timeout=5)

@pytest.mark.parametrize('fault',['unknown-dense','unknown-sparse','checkpoint-cap','task-cap','bad-exit','bad-final-exit'])
def test_failure_evidence_has_no_fabricated_usage(tmp_path,monkeypatch,fault):
    args=setup_job(tmp_path,monkeypatch);requests=mock_http(monkeypatch)
    if fault=='unknown-dense':
        def fail(*a,**k):raise OSError(PRIVATE)
        monkeypatch.setattr(worker.DenseEncoder,'encode_batch',fail)
    elif fault=='unknown-sparse':
        def fail(*a,**k):raise OSError(PRIVATE)
        monkeypatch.setattr(worker.SparseEncoder,'encode_batch',fail)
    elif fault=='checkpoint-cap':args[3]['max_checkpoint_records']=2
    elif fault=='task-cap':args[3]['max_checkpoint_records']=4
    if fault in ('bad-exit','bad-final-exit'):
        normal=worker.run_job
        def altered(job,key):
            result=normal(job,key)
            return 1 if fault=='bad-exit' else 0
        monkeypatch.setattr(worker,'run_job',altered)
        if fault=='bad-final-exit':
            def fail(*a,**k):raise EncodingError('sparse_encoding_failed')
            monkeypatch.setattr(worker.SparseEncoder,'encode_batch',fail)
    execute_in_process(monkeypatch)
    report=parent.run_check(*args[:3],**args[3])
    assert report['status']=='failed' and PRIVATE not in json.dumps(report)
    if fault=='unknown-dense':
        assert requests==[] and report['attempted_requests'] is None and report['usage']['status']=='unknown'
        assert report['error_code']=='encoding_stage_failed'
    elif fault=='checkpoint-cap':assert requests==[] and report['attempted_requests']==0
    elif fault=='task-cap':assert len(requests)==1 and report['attempted_requests']==1 and report['usage']['total_tokens']==7
    elif fault=='unknown-sparse':assert report['error_code']=='encoding_stage_failed' and len(requests)==1 and report['usage']['total_tokens']==7
    elif fault=='bad-exit':assert report['error_code']=='worker_failed'
    else:assert report['error_code']=='checkpoint_protocol_invalid'

@pytest.mark.parametrize('fault',['extra','model-space','query','plan','traversal','cache','too-many'])
def test_worker_rechecks_descriptor_before_components(tmp_path,monkeypatch,fault):
    args=setup_job(tmp_path,monkeypatch);job,_,_=parent.prepare_job(*args[:3],**args[3])
    if fault=='extra':job['secret']=PRIVATE
    elif fault=='model-space':job['model_space_id']='0'*64
    elif fault=='query':job['query']=PRIVATE
    elif fault=='plan':job['plans']['query']['input_count']=2
    elif fault=='traversal':job['run_dir']=str(Path(job['run_dir'])/'..'/'escape')
    elif fault=='cache':job['sparse_settings']['cache_dir']=str(tmp_path/'cache')
    else:job['inputs'].append(copy.deepcopy(job['inputs'][0]))
    monkeypatch.setattr(worker,'_components',lambda *a:pytest.fail('components must not initialize'))
    with pytest.raises(CheckError,match='check_descriptor_invalid'):worker.run_job(job,PRIVATE)

@pytest.mark.parametrize('fault',['unsafe-sdk-env','output-parent-file','corrupt-source'])
def test_additional_preflight_contracts(tmp_path,monkeypatch,fault):
    args=setup_job(tmp_path,monkeypatch)
    if fault=='unsafe-sdk-env':monkeypatch.setenv('OPENAI_CUSTOM_HEADERS',PRIVATE)
    elif fault=='output-parent-file':(args[3]['project_root']/'data').write_text('not a directory')
    else:(args[3]['project_root']/'examples/encoding-check/feature.md').write_text('# Private material\n'+PRIVATE)
    monkeypatch.setattr(parent.subprocess,'Popen',lambda *a,**k:pytest.fail('no child permitted'))
    with pytest.raises(CheckError):parent.run_check(*args[:3],**args[3])
