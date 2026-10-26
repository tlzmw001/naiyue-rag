import importlib
import json
import socket
import subprocess
from urllib.error import HTTPError,URLError

import pytest
from vector_fixtures import CORPUS,config,response


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*a,**k): raise AssertionError('real network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbid)
    monkeypatch.setattr(socket.socket,'connect_ex',forbid)
    monkeypatch.setenv('NAIYUE_RAG_ZHIPU_API_KEY','offline-secret-sentinel')


@pytest.fixture
def mod(): return importlib.import_module('experiments.vector_embedding')


@pytest.mark.parametrize('field,value',[('dimensions',1024),('batch_size',17),('max_requests',6),
    ('max_inputs',57),('timeout_seconds',31),('deadline_seconds',181),('candidate_k',21),
    ('max_context_chars',8001),('max_context_chars',True),('max_response_bytes',4194305),
    ('max_input_utf8_bytes',3073),('unit_price_cny_per_million',float('nan')),
    ('endpoint','http://example.com'),('model','other')])
def test_config_boundaries(mod,tmp_path,field,value):
    cfg=config(tmp_path);cfg[field]=value
    with pytest.raises(mod.ProbeError):mod.validate_config(cfg)


def test_http_body_headers_and_limits(mod,tmp_path,monkeypatch):
    cfg=config(tmp_path);texts=['完整正文与上下文']*16
    class Reply:
        status=200
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,limit):
            assert limit==4194305
            return json.dumps(response(16)).encode()
    class Opener:
        def open(self,request,timeout):
            assert json.loads(request.data)=={'model':'embedding-3','dimensions':2048,'input':texts}
            assert request.get_header('Authorization')=='Bearer offline-secret-sentinel'
            assert timeout==30 and request.method=='POST'
            return Reply()
    def opener(handler):
        assert isinstance(handler,mod.NoRedirect);return Opener()
    monkeypatch.setattr(mod,'build_opener',opener)
    assert mod.send_batch(cfg,texts,'offline-secret-sentinel')['model']=='embedding-3'


@pytest.mark.parametrize('fault',['http','timeout','json','large','secret','escaped_secret','duplicate'])
def test_http_errors_do_not_leak_key(mod,tmp_path,monkeypatch,fault):
    class Reply:
        status=200
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,limit):
            if fault=='large':return b'x'*limit
            if fault=='secret':return b'{"x":"offline-secret-sentinel"}'
            if fault=='escaped_secret':return b'{"x":"offline\\u002dsecret-sentinel"}'
            if fault=='duplicate':return b'{"x":1,"x":2}'
            return b'{'
    class Opener:
        def open(self,*a,**k):
            if fault=='http':raise HTTPError('url',429,'offline-secret-sentinel',{},None)
            if fault=='timeout':raise URLError('offline-secret-sentinel')
            return Reply()
    monkeypatch.setattr(mod,'build_opener',lambda handler:Opener())
    with pytest.raises(mod.ProbeError) as error:mod.send_batch(config(tmp_path),['test'],'offline-secret-sentinel')
    assert 'offline-secret-sentinel' not in str(error.value)


def job_for(cfg,path):
    from experiments.vector_index import load_corpus
    path.mkdir()
    return {'config':cfg,'folder':str(path),'fingerprint':load_corpus(CORPUS,cfg['dataset'])['fingerprint']}


def test_worker_batches_checkpoints_persist_and_known_cost(mod,tmp_path,monkeypatch):
    calls=[];checkpoints=[]
    def send(cfg,texts,key):
        assert key=='offline-secret-sentinel';calls.append(texts);return response(len(texts))
    monkeypatch.setattr(mod,'send_batch',send)
    result=mod.run_worker(job_for(config(tmp_path),tmp_path/'run'),checkpoints.append)
    assert result['status']=='complete' and result['attempt_count']==5
    assert list(map(len,calls))==[16,16,16,4,4]
    assert result['estimated_cost_cny']==pytest.approx(0.00028)
    assert checkpoints[0]['requests'][0]['usage'] is None
    assert (tmp_path/'run/index_manifest.json').is_file()
    assert 'offline-secret-sentinel' not in json.dumps(result)


@pytest.mark.parametrize('fault',['http','usage','vectors'])
def test_worker_failure_keeps_attempt_and_known_usage_no_retry(mod,tmp_path,monkeypatch,fault):
    calls=[]
    def send(cfg,texts,key):
        calls.append(1)
        if fault=='http':raise mod.ProbeError('http','http_error',503)
        payload=response(len(texts))
        if fault=='usage':payload.pop('usage')
        if fault=='vectors':payload['data'][0]['embedding'][0]=True
        return payload
    monkeypatch.setattr(mod,'send_batch',send)
    result=mod.run_worker(job_for(config(tmp_path),tmp_path/'run'),lambda state:None)
    assert result['status']=='error' and result['attempt_count']==len(calls)==1
    assert not (tmp_path/'run/index_manifest.json').exists()
    if fault=='vectors':assert result['estimated_cost_cny']==pytest.approx(0.00008)
    else:assert result['estimated_cost_cny'] is None


def test_deadline_kills_worker_and_preserves_attempt(mod,tmp_path,monkeypatch):
    cfg=config(tmp_path);state=mod.initial_state(cfg);state['attempt_count']=1
    state['requests']=[{'usage':None,'stage':'documents'}]
    class Child:
        returncode=-9
        def __init__(self,*a,**k):self.killed=False
        def communicate(self,input=None,timeout=None):
            if not self.killed:raise subprocess.TimeoutExpired('worker',timeout)
            return json.dumps({'event':'checkpoint','summary':state}), 'offline-secret-sentinel'
        def kill(self):self.killed=True
    monkeypatch.setattr(mod.subprocess,'Popen',Child)
    result=mod.supervise({'config':cfg},mod.time.monotonic())
    assert result['status']=='error' and result['attempt_count']==1
    assert result['sanitized_error']['category']=='deadline_exceeded'
    assert result['estimated_cost_cny'] is None


def test_supervisor_deducts_startup_time(mod,tmp_path,monkeypatch):
    cfg=config(tmp_path);state=mod.initial_state(cfg);state['status']='complete'
    times=iter([1.0,11.0])
    monkeypatch.setattr(mod.time,'monotonic',lambda:next(times))
    class Child:
        returncode=0
        def __init__(self,*a,**k):pass
        def communicate(self,input=None,timeout=None):
            assert timeout==169
            return json.dumps({'event':'result','summary':state}), ''
    monkeypatch.setattr(mod.subprocess,'Popen',Child)
    assert mod.supervise({'config':cfg},0.0)['status']=='complete'
