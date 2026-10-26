"""Pinned real SDK over mock HTTP; never invokes a model service."""
import json
import logging
from types import SimpleNamespace
import pytest
import httpx

from naiyue_rag.encoding.openai_embedding import OpenAICompatibleEmbedding
from naiyue_rag.core.errors import EmbeddingExecutionError
from test_encoding_settings import config
from test_document_chunker import offline

PRIVATE='SYNTHETIC_PRIVATE'

class Body(httpx.SyncByteStream):
    def __init__(self,chunks,close_error=False):
        self.chunks=chunks;self.reads=0;self.closed=False;self.close_error=close_error
    def __iter__(self):
        for chunk in self.chunks:
            self.reads+=1
            if isinstance(chunk,Exception):raise chunk
            yield chunk
    def close(self):
        self.closed=True
        if self.close_error:raise OSError(PRIVATE)

class Transport(httpx.MockTransport):
    def __init__(self,handler):
        super().__init__(handler);self.closed=False;self.close_error=False
    def close(self):
        self.closed=True
        if self.close_error:raise OSError(PRIVATE)

def payload(count=1):
    return {'model':'synthetic-model','data':[{'index':i,'embedding':[float(i+1),2.,3.]}
                                            for i in reversed(range(count))]}

@pytest.fixture(autouse=True)
def safe_ambient(monkeypatch):
    for name in ['OPENAI_LOG','OPENAI_CUSTOM_HEADERS']:
        monkeypatch.delenv(name,raising=False)
    loggers=[logging.getLogger(name) for name in ['openai','openai._base_client','openai._response','httpx','httpcore.connection','httpcore.http11','httpcore.http2','httpcore.proxy']]
    levels=[logger.level for logger in loggers]
    for logger in loggers:logger.setLevel(logging.WARNING)
    yield
    for logger,level in zip(loggers,levels):logger.setLevel(level)

@pytest.fixture
def factory(monkeypatch):
    import naiyue_rag.encoding.openai_embedding as provider_module
    import naiyue_rag.encoding.bounded_transport as transport_module
    import naiyue_rag.encoding.dense_encoder as dense_module
    # Fixed production-boundary clock makes timeout assertions exact, without sleeps.
    clock=SimpleNamespace(monotonic=lambda:0.)
    for module in [provider_module,transport_module,dense_module]:monkeypatch.setattr(module,'time',clock)
    providers=[]
    def create(handler,cfg=None):
        seen=[]
        def capture(req):seen.append(req);return handler(req)
        transport=Transport(capture)
        def construct(**kwargs):
            assert kwargs=={'retries':0,'trust_env':False}
            return transport
        monkeypatch.setattr(httpx,'HTTPTransport',construct)
        provider=OpenAICompatibleEmbedding(cfg or config(),api_key=PRIVATE)
        providers.append(provider)
        transport.requests=seen
        return provider,transport
    yield create
    for provider in providers:
        if not provider.closed:provider.close()

@pytest.mark.parametrize('dimensions',[None,3])
def test_real_sdk_wire_parameters_and_reusable_client(factory,dimensions,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','WRONG_SYNTHETIC_KEY')
    monkeypatch.setenv('OPENAI_BASE_URL','https://wrong.example.invalid')
    monkeypatch.setenv('OPENAI_ORG_ID',PRIVATE)
    monkeypatch.setenv('OPENAI_PROJECT_ID',PRIVATE)
    monkeypatch.setenv('OPENAI_ADMIN_KEY',PRIVATE)
    bodies=[]
    def handler(req):
        body=Body([json.dumps(payload()).encode()]);bodies.append(body)
        return httpx.Response(200,headers={'content-type':'application/json'},stream=body)
    provider,transport=factory(handler,config(embedding={'request_dimensions':dimensions}))
    for _ in range(2):
        result,report=provider.embed(['query: 开关'],timeout_seconds=3)
        assert result==payload() and report['attempted_requests']==1 and report['http_status']==200
        assert report['error_code'] is None and report['response_close_error_code'] is None
        assert bodies[-1].closed and not transport.closed
    request=transport.requests[0];data=json.loads(request.content)
    assert data['encoding_format']=='float' and data['input']==['query: 开关']
    assert ('dimensions' in data)==(dimensions is not None)
    if dimensions is not None:assert data['dimensions']==3
    assert request.headers['authorization']=='Bearer '+PRIVATE
    assert request.headers['accept-encoding']=='identity'
    assert 'openai-organization' not in request.headers and 'openai-project' not in request.headers
    assert str(request.url)=='https://embedding.example.invalid/v1/embeddings'
    assert all(v==3 for v in request.extensions['timeout'].values())
    provider.close();assert transport.closed

@pytest.mark.parametrize('status',[401,429,500,302])
def test_http_failure_single_attempt_safe_report(factory,status,caplog):
    body=Body([json.dumps({'error':{'message':PRIVATE}}).encode()])
    provider,transport=factory(lambda req:httpx.Response(status,headers={'location':'https://wrong.example.invalid'},stream=body))
    with pytest.raises(EmbeddingExecutionError,match=f'^embedding_http_{status}$') as caught:
        provider.embed(['query: '+PRIVATE],timeout_seconds=3)
    assert len(transport.requests)==1 and body.closed
    report=caught.value.report
    assert report['http_status']==status and report['attempted_requests']==1
    assert PRIVATE not in str(caught.value) and PRIVATE not in json.dumps(report) and PRIVATE not in caplog.text

@pytest.mark.parametrize('status',[200,500])
@pytest.mark.parametrize('declared',['absent','small','large'])
def test_actual_byte_limit_covers_success_and_error(factory,status,declared):
    body=Body([b'a'*32,b'b'*32,b'c'*32])
    headers={} if declared=='absent' else {'content-length':'2' if declared=='small' else '96'}
    provider,transport=factory(lambda req:httpx.Response(status,headers=headers,stream=body),config(runtime={'max_response_bytes':48}))
    with pytest.raises(EmbeddingExecutionError,match='^embedding_response_too_large$') as caught:
        provider.embed(['query: synthetic'],timeout_seconds=3)
    assert body.closed and body.reads==(0 if declared=='large' else 2)
    assert caught.value.report['http_status']==status and len(transport.requests)==1

@pytest.mark.parametrize('headers,code',[
    ({'content-encoding':'gzip'},'embedding_unsupported_content_encoding'),
    ({'content-length':'wrong'},'embedding_invalid_response_headers'),
    ({'content-length':'-1'},'embedding_invalid_response_headers')])
def test_header_failure_before_body_read(factory,headers,code):
    body=Body([b'{}'])
    provider,_=factory(lambda req:httpx.Response(200,headers=headers,stream=body))
    with pytest.raises(EmbeddingExecutionError,match='^'+code+'$'):provider.embed(['synthetic'],timeout_seconds=3)
    assert body.closed and body.reads==0

@pytest.mark.parametrize('raw',[b'\xff',b'{"a":1,"a":2}',b'{"x":NaN}',b'{"x":Infinity}',b'{',b'[]'])
def test_strict_json_no_raw_error_leak(factory,raw,caplog):
    body=Body([raw])
    provider,_=factory(lambda req:httpx.Response(200,stream=body))
    with pytest.raises(EmbeddingExecutionError,match='^embedding_invalid_json$'):
        provider.embed(['query: '+PRIVATE],timeout_seconds=3)
    assert body.closed and PRIVATE not in caplog.text

@pytest.mark.parametrize('stage',['send','read'])
def test_timeout_single_attempt_and_unknown_status_when_no_headers(factory,stage):
    body=Body([httpx.ReadTimeout(PRIVATE)])
    def handler(req):
        if stage=='send':raise httpx.ReadTimeout(PRIVATE,request=req)
        return httpx.Response(200,stream=body)
    provider,transport=factory(handler)
    with pytest.raises(EmbeddingExecutionError,match='^embedding_timeout$') as caught:
        provider.embed(['query: synthetic'],timeout_seconds=3)
    assert len(transport.requests)==1
    assert caught.value.report['http_status']==(None if stage=='send' else 200)
    if stage=='read':assert body.closed

@pytest.mark.parametrize('texts,seconds',[
    ([],3),(['a','b','c'],3),([''],3),(['\ud800'],3),(['x'*4097],3),
    (['a'],0),(['a'],True),(['a'],float('inf')),(['a'],10**1000)])
def test_provider_preflight_has_zero_http_requests(factory,texts,seconds):
    provider,transport=factory(lambda req:httpx.Response(200,json=payload()))
    with pytest.raises(EmbeddingExecutionError) as caught:provider.embed(texts,timeout_seconds=seconds)
    assert caught.value.report['attempted_requests']==0 and transport.requests==[]

@pytest.mark.parametrize('kind',['custom-headers','sdk-log-env','sdk-debug','httpx-info'])
def test_unsafe_ambient_configuration_rejected_before_request(factory,monkeypatch,kind,caplog):
    provider,transport=factory(lambda req:httpx.Response(200,json=payload()))
    if kind=='custom-headers':monkeypatch.setenv('OPENAI_CUSTOM_HEADERS',PRIVATE)
    elif kind=='sdk-log-env':monkeypatch.setenv('OPENAI_LOG','debug')
    else:logging.getLogger('openai._base_client' if kind=='sdk-debug' else 'httpx').setLevel(logging.DEBUG if kind=='sdk-debug' else logging.INFO)
    with pytest.raises(EmbeddingExecutionError,match='^embedding_unsafe_sdk_environment$'):
        provider.embed(['query: '+PRIVATE],timeout_seconds=3)
    assert transport.requests==[] and PRIVATE not in caplog.text

def test_missing_key_and_closed_provider_are_explicit(factory):
    with pytest.raises(EmbeddingExecutionError,match='^embedding_invalid_credential$'):
        OpenAICompatibleEmbedding(config(),api_key='')
    provider,transport=factory(lambda req:httpx.Response(200,json=payload()))
    provider.close();provider.close()
    with pytest.raises(EmbeddingExecutionError,match='^embedding_provider_closed$'):provider.embed(['a'],timeout_seconds=3)
    assert transport.closed and transport.requests==[]

@pytest.mark.parametrize('status',[200,500])
def test_response_close_failure_observed_without_masking_http_failure(factory,status,caplog):
    body=Body([json.dumps(payload() if status==200 else {'error':{'message':PRIVATE}}).encode()],close_error=True)
    provider,_=factory(lambda req:httpx.Response(status,stream=body))
    code='embedding_response_close_failed' if status==200 else 'embedding_http_500'
    with pytest.raises(EmbeddingExecutionError,match='^'+code+'$') as caught:provider.embed(['a'],timeout_seconds=3)
    assert body.closed and caught.value.report['response_close_error_code']=='embedding_response_close_failed'
    assert PRIVATE not in caplog.text

def test_client_close_failure_and_primary_exception(factory,caplog):
    provider,transport=factory(lambda req:httpx.Response(500,json={'error':{'message':PRIVATE}}))
    transport.close_error=True
    with pytest.raises(EmbeddingExecutionError,match='^embedding_http_500$') as caught:
        with provider:provider.embed(['a'],timeout_seconds=3)
    assert transport.closed and caught.value.report['client_close_error_code']=='embedding_client_close_failed'
    assert PRIVATE not in caplog.text
    provider,transport=factory(lambda req:httpx.Response(200,json=payload()))
    transport.close_error=True
    with pytest.raises(EmbeddingExecutionError,match='^embedding_client_close_failed$'):provider.close()

def test_cooperative_deadline_checked_after_headers(factory,monkeypatch):
    import naiyue_rag.encoding.openai_embedding as module
    clock=[0.]
    monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    body=Body([json.dumps(payload()).encode()])
    def handler(req):clock[0]=4.;return httpx.Response(200,stream=body)
    provider,transport=factory(handler)
    with pytest.raises(EmbeddingExecutionError,match='^embedding_deadline_exceeded$'):
        provider.embed(['a'],timeout_seconds=3)
    assert body.closed and body.reads==0 and len(transport.requests)==1


def test_initialization_failure_closes_created_transport(monkeypatch,caplog):
    # Load real SDK before replacing Client; otherwise its class declarations fail first.
    import openai
    transport=Transport(lambda req:httpx.Response(200,json=payload()))
    monkeypatch.setattr(httpx,'HTTPTransport',lambda **kwargs:transport)
    def fail_client(**kwargs):raise OSError(PRIVATE)
    monkeypatch.setattr(httpx,'Client',fail_client)
    with pytest.raises(EmbeddingExecutionError,match='^embedding_initialization_failed$'):
        OpenAICompatibleEmbedding(config(),api_key=PRIVATE)
    assert transport.closed and PRIVATE not in caplog.text


def test_reentrant_provider_call_fails_without_extra_transport_request(factory):
    holder=[]
    def handler(req):
        with pytest.raises(EmbeddingExecutionError,match='^embedding_provider_busy$') as caught:
            holder[0].embed(['nested'],timeout_seconds=3)
        assert caught.value.report['attempted_requests']==0
        return httpx.Response(200,json=payload())
    provider,transport=factory(handler);holder.append(provider)
    result,report=provider.embed(['outer'],timeout_seconds=3)
    assert result==payload() and len(transport.requests)==1 and report['attempted_requests']==1


def test_keyboard_interrupt_not_converted_or_masked_by_close_failure(factory,caplog):
    class InterruptedBody(Body):
        def __iter__(self):raise KeyboardInterrupt()
    body=InterruptedBody([],close_error=True)
    provider,transport=factory(lambda req:httpx.Response(200,stream=body))
    with pytest.raises(KeyboardInterrupt):provider.embed(['a'],timeout_seconds=3)
    assert body.closed and len(transport.requests)==1
    assert 'embedding_response_close_failed' in caplog.text and PRIVATE not in caplog.text
    provider.close();assert transport.closed
