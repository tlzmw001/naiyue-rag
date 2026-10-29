import json
import pytest
from test_model_registry import settings_at


@pytest.mark.parametrize('args,operation,data', [
    (['query','feature_x','--scope-document-id','doc-'+'a'*64,'--exclude-document-id','doc-'+'b'*64],
        'query',{'query':'feature_x','expected_revision':None,'scope_document_ids':['doc-'+'a'*64],
                 'exclude_document_ids':['doc-'+'b'*64]}),
    (['document','doc-'+'a'*64,'--expected-revision','1'],'document',{'document_id':'doc-'+'a'*64,'expected_revision':1}),
    (['remove','doc-'+'a'*64,'--expected-revision','2'],'remove',{'document_id':'doc-'+'a'*64,'expected_revision':2}),
])
def test_cli_routes_existing_core_operations(tmp_path,monkeypatch,capsys,args,operation,data):
    import naiyue_rag.cli as cli
    cfg=settings_at(tmp_path);seen=[]
    class Connection:
        def __init__(self,settings):self.client=self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def request(self,op,body):seen.append((op,body));return {'status':'synthetic_routed'}
    monkeypatch.setattr(cli,'ManagedConnection',Connection)
    assert cli.main(['--config',cfg.config_path,*args])==0
    assert seen==[(operation,data)]
    assert json.loads(capsys.readouterr().out)['status']=='synthetic_routed'


def test_cli_status_routes_to_shared_instance(tmp_path,monkeypatch,capsys):
    import naiyue_rag.cli as cli
    cfg=settings_at(tmp_path)
    class Connection:
        def __init__(self,settings):self.client=self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def status(self):return {'closed':False,'executing':2,'queued':3,'draining':1}
    monkeypatch.setattr(cli,'ManagedConnection',Connection)
    assert cli.main(['status','--config',cfg.config_path])==0
    assert json.loads(capsys.readouterr().out)['queued']==3


def test_remove_requires_explicit_revision():
    from naiyue_rag.cli import parser
    with pytest.raises(SystemExit):parser().parse_args(['remove','doc-'+'a'*64])


def test_new_service_identity_rejects_old_execution_contract(tmp_path):
    import hashlib
    from naiyue_rag.service_protocol import configuration_identity
    from naiyue_rag.core.model_registry import load_model_registry
    cfg=settings_at(tmp_path);registry=load_model_registry(cfg)
    old=hashlib.sha256(json.dumps({'settings':cfg.to_dict(),'models_identity':registry.identity},
        sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    assert configuration_identity(cfg,registry)!=old


def test_query_http_read_budget_includes_server_deadline_and_network_window(tmp_path):
    from dataclasses import replace
    import httpx
    from naiyue_rag.local_client import LocalClient
    cfg=settings_at(tmp_path)
    cfg=replace(cfg,service=replace(cfg.service,request_timeout_seconds=3),
        retrieval=replace(cfg.retrieval,request_timeout_seconds=7))
    seen=[]
    def respond(request):
        seen.append(request.extensions['timeout'])
        return httpx.Response(200,json={'status':'synthetic'})
    with LocalClient(cfg) as client:
        client._client.close();client._client=httpx.Client(transport=httpx.MockTransport(respond),
            base_url='http://127.0.0.1')
        client.request('query',{'query':'synthetic'})
        client.request('documents',{})
    assert seen[0]['read']==10 and seen[0]['connect']==3
    assert seen[1]['read']==3
