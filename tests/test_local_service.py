"""HTTP contract, explicit authentication and the actual owned runtime."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import pytest
from test_model_registry import settings_at
from test_application_runtime import runtime_job
from test_dense_retrieval import native_query
from test_openai_embedding import safe_ambient
from test_settings import offline


def client_for(settings,**kwargs):
    from fastapi.testclient import TestClient
    from naiyue_rag.service import create_service
    return TestClient(create_service(settings,**kwargs),base_url='http://127.0.0.1:8000')


def auth(settings):return {'Authorization':f'Bearer {settings.service.access_token}'}


def test_health_requires_token_and_does_not_echo_settings(tmp_path):
    cfg=settings_at(tmp_path)
    with client_for(cfg) as client:
        assert client.get('/v1/health').status_code==401
        health=client.get('/v1/health',headers=auth(cfg)).json()
        assert set(health)=={'protocol','instance_id','config_identity'} and health['protocol']==1
        assert len(health['config_identity'])==64
        assert cfg.service.access_token not in json.dumps(health)
        assert client.get('/v1/health',headers=auth(cfg)).json()==health
        assert client.get('/docs',headers=auth(cfg)).status_code==404
    with client_for(cfg) as other:
        next_health=other.get('/v1/health',headers=auth(cfg)).json()
        assert next_health['instance_id']!=health['instance_id']
        assert next_health['config_identity']==health['config_identity']


@pytest.mark.parametrize('headers',[{'Origin':'http://other.invalid'},{'Host':'evil.invalid'},{'Authorization':'Bearer wrong'},
                                  {'Authorization':'Bearer 密钥'}])
def test_access_boundary_before_body_parse(tmp_path,headers):
    cfg=settings_at(tmp_path)
    with client_for(cfg) as client:
        # Non-ASCII header bytes exercise the raw HTTP boundary.
        merged={**auth(cfg),**headers}
        raw=[(k.encode(),v.encode('utf-8')) for k,v in merged.items()]
        response=client.post('/v1/query',headers=raw,content=b'invalid-json')
        assert response.status_code in {401,403}
        assert 'invalid-json' not in response.text and '密钥' not in response.text


@pytest.mark.parametrize('body,status',[
    ('{"query":"a","query":"b"}',400),('{"query":NaN}',400),('[]',400),
    ('{"query":"secret","extra":1}',400),('{"query":1}',400),('{"query":" "}',400),
    ('{"query":"a","expected_revision":true}',400),('{"query":"a","scope_document_ids":"id"}',400),
    ('{"query":"a","exclude_document_ids":[1]}',400),('bad-json',400),
    (' '*1048577,413)],ids=['duplicate','NaN','array','unknown','query-type','blank','bool-revision','scope','exclude','json','oversize'])
def test_invalid_input_is_bounded_and_private(tmp_path,body,status):
    cfg=settings_at(tmp_path)
    with client_for(cfg) as client:
        response=client.post('/v1/query',content=body,headers={**auth(cfg),'Content-Type':'application/json'})
        assert response.status_code==status and set(response.json())=={'error'}
        assert 'secret' not in response.text
        assert client.post('/v1/query',content='{}',headers=auth(cfg)).status_code==415
        assert client.post('/v1/ingest',json={},headers=auth(cfg)).status_code==400


def test_http_real_runtime_chain_and_cleanup(runtime_job):
    runtime,seen,cfg=runtime_job
    with client_for(cfg,runtime_factory=lambda settings:runtime) as client:
        headers=auth(cfg)
        assert client.post('/v1/documents',json={},headers=headers).json()['documents']==[] and seen==[]
        first=client.post('/v1/ingest',json={'expected_revision':0},headers=headers)
        assert first.status_code==200 and first.json()['status']=='activated'
        assert client.post('/v1/ingest',json={'expected_revision':1},headers=headers).json()['status']=='unchanged'
        result=client.post('/v1/query',json={'query':'feature_x TC-01','expected_revision':1},headers=headers)
        assert result.status_code==200 and result.json()['schema_version']==2 and result.json()['evidence']
        conflict=client.post('/v1/ingest',json={'expected_revision':0},headers=headers)
        assert conflict.status_code==409 and conflict.json()['error']['activation_status']=='not_attempted'
    assert runtime._closed and runtime._provider.closed


def test_busy_and_safe_internal_error_keep_health_alive(runtime_job,monkeypatch,caplog):
    runtime,_,cfg=runtime_job;entered=threading.Event();release=threading.Event()
    original=runtime.manager.list_documents
    def blocked(**kwargs):entered.set();assert release.wait(10);return original(**kwargs)
    monkeypatch.setattr(runtime.manager,'list_documents',blocked)
    with client_for(cfg,runtime_factory=lambda settings:runtime) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(client.post,'/v1/documents',json={},headers=auth(cfg))
            try:
                assert entered.wait(10)
                assert client.get('/v1/health',headers=auth(cfg)).status_code==200
                assert client.post('/v1/documents',json={},headers=auth(cfg)).status_code==409
            finally:release.set()
            assert pending.result().status_code==200
        def fail(**kwargs):raise OSError('SYNTHETIC_PRIVATE_FAILURE')
        monkeypatch.setattr(runtime,'documents',fail)
        response=client.post('/v1/documents',json={},headers=auth(cfg))
        assert response.status_code==500 and response.json()=={'error':{'code':'service_internal_error'}}
        assert 'SYNTHETIC_PRIVATE_FAILURE' not in caplog.text


def test_registry_changes_invalidate_service_identity(tmp_path):
    from naiyue_rag.service_protocol import configuration_identity
    from pathlib import Path
    cfg=settings_at(tmp_path);before=configuration_identity(cfg)
    path=Path(cfg.models_file);raw=json.loads(path.read_text())
    raw['models']['embedding']['api_key']='SYNTHETIC_REPLACED_KEY';path.write_text(json.dumps(raw),encoding='utf-8')
    assert configuration_identity(cfg)!=before


def test_windows_break_requests_graceful_service_shutdown(tmp_path,monkeypatch):
    import signal
    import uvicorn
    from naiyue_rag.service import run_service
    from types import SimpleNamespace
    handlers={};original=object();servers=[]
    def register(number,handler):
        old=handlers.get(number,original);handlers[number]=handler;return old
    monkeypatch.setattr(signal,'SIGBREAK',123456,raising=False)
    monkeypatch.setattr(signal,'signal',register)
    class Server:
        def __init__(self,config):self.should_exit=False;servers.append(self)
        def run(self):
            handlers[signal.SIGBREAK](signal.SIGBREAK,None)
            assert self.should_exit
    monkeypatch.setattr(uvicorn,'Server',Server)
    monkeypatch.setattr(uvicorn,'Config',lambda *args,**kwargs:SimpleNamespace())
    run_service(settings_at(tmp_path))
    assert servers[0].should_exit and handlers[signal.SIGBREAK] is original
