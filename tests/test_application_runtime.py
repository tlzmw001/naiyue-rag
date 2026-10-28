"""One owned runtime connects unified settings to the existing actual RAG chain."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import httpx
import pytest
from naiyue_rag.core.errors import SettingsError
from test_model_registry import settings_at
from test_storage_bundle import ingredients
from test_chroma_index import FakeClient
from test_dense_retrieval import native_query
from test_openai_embedding import payload,safe_ambient
from test_settings import offline


@pytest.fixture
def runtime_job(tmp_path,monkeypatch,native_query):
    from naiyue_rag.runtime import ApplicationRuntime
    import naiyue_rag.storage.chroma_backend as chroma
    ingredients(tmp_path);cfg=settings_at(tmp_path);seen=[]
    monkeypatch.setenv('SYNTHETIC_RERANK_KEY','SYNTHETIC_SECOND_KEY')
    monkeypatch.setattr(chroma,'new_client',lambda path,root:FakeClient(path,[],{}))
    def respond(request):
        wire=json.loads(request.content);seen.append((request.url.path,request.headers['authorization']))
        if request.url.path.endswith('/embeddings'):
            raw=payload(len(wire['input']));raw['usage']={'prompt_tokens':7*len(wire['input']),'total_tokens':7*len(wire['input'])}
            return httpx.Response(200,json=raw)
        passages=json.loads(wire['messages'][1]['content'])['passages']
        return httpx.Response(200,json={'model':'synthetic-model','choices':[{'finish_reason':'stop','message':{'role':'assistant',
            'content':json.dumps({'scores':[{'passage_id':p['passage_id'],'score':i} for i,p in enumerate(passages)]})}}],
            'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
    monkeypatch.setattr(httpx,'HTTPTransport',lambda **kwargs:httpx.MockTransport(respond))
    runtime=ApplicationRuntime(cfg)
    yield runtime,seen,cfg
    runtime.close()


def test_unified_runtime_ingests_queries_and_reuses_sdk_clients(runtime_job):
    runtime,seen,cfg=runtime_job
    assert runtime.documents()['documents']==[] and seen==[]
    first=runtime.ingest(expected_revision=0)
    assert first['status']=='activated' and first['active']['revision']==1
    before=len(seen);again=runtime.ingest(expected_revision=1)
    assert again['status']=='unchanged' and len(seen)==before
    result=runtime.query('  feature_x threshold TC-01  ',expected_revision=1)
    assert result['schema_version']==2 and result['evidence']
    assert result['active']['revision']==1 and result['observations']['rerank']['usage']['total_tokens']==15
    assert seen[-1][1]=='Bearer SYNTHETIC_SECOND_KEY'
    assert all(key=='Bearer SYNTHETIC_PRIVATE_KEY' for path,key in seen if path.endswith('/embeddings'))
    assert runtime.documents()['active']['revision']==1
    provider=runtime._provider;runtime.close();assert provider.closed
    with pytest.raises(SettingsError,match='application_closed'):runtime.documents()


def test_document_management_does_not_resolve_model_credentials(runtime_job,monkeypatch):
    runtime,seen,_=runtime_job;monkeypatch.delenv('SYNTHETIC_RERANK_KEY')
    assert runtime.documents()['documents']==[] and seen==[]


def test_missing_selected_key_is_not_replaced_by_embedding_key(runtime_job,monkeypatch):
    runtime,seen,_=runtime_job;runtime.ingest(expected_revision=0)
    monkeypatch.delenv('SYNTHETIC_RERANK_KEY')
    with pytest.raises(SettingsError,match='model_credential_invalid'):runtime.query('feature_x')
    assert all(path.endswith('/embeddings') for path,_ in seen)


def test_busy_operations_and_close_do_not_interrupt_the_owner(runtime_job,monkeypatch):
    runtime,seen,_=runtime_job;entered=threading.Event();release=threading.Event()
    original=runtime.manager.list_documents
    def blocked(**kwargs):entered.set();assert release.wait(10);return original(**kwargs)
    monkeypatch.setattr(runtime.manager,'list_documents',blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(runtime.documents)
        try:
            assert entered.wait(10)
            with pytest.raises(SettingsError,match='application_busy'):runtime.documents()
            with pytest.raises(SettingsError,match='application_busy'):runtime.close()
        finally:release.set()
        assert pending.result()['documents']==[]
    assert seen==[]


def test_partial_encoder_initialization_closes_unpublished_provider(runtime_job,monkeypatch):
    import naiyue_rag.runtime as module
    runtime,_,_=runtime_job;created=[];provider_type=module.OpenAICompatibleEmbedding
    def tracked(*args,**kwargs):
        provider=provider_type(*args,**kwargs);created.append(provider);return provider
    def fail(*args,**kwargs):raise ValueError('SYNTHETIC_COMPONENT_FAILURE')
    monkeypatch.setattr(module,'OpenAICompatibleEmbedding',tracked)
    monkeypatch.setattr(module,'SparseEncoder',fail)
    with pytest.raises(ValueError,match='SYNTHETIC_COMPONENT_FAILURE'):runtime.ingest(expected_revision=0)
    assert created[0].closed and runtime._provider is None and runtime._sparse is None


@pytest.mark.parametrize('primary',[False,True])
def test_cleanup_errors_are_safe_and_do_not_mask_primary_failure(runtime_job,monkeypatch,caplog,primary):
    runtime,_,_=runtime_job;runtime._encoding()
    def fail():raise OSError('SYNTHETIC_PRIVATE_CLOSE')
    monkeypatch.setattr(runtime._provider,'close',fail)
    if primary:
        with pytest.raises(ValueError,match='PRIMARY'):
            with runtime:raise ValueError('PRIMARY')
    else:
        with pytest.raises(SettingsError,match='application_close_failed'):runtime.close()
    assert 'SYNTHETIC_PRIVATE_CLOSE' not in caplog.text
