"""Pinned OpenAI SDK over controlled HTTP; no service requests."""
import json
from dataclasses import replace
import pytest
import httpx
from test_openai_embedding import Body,Transport,safe_ambient

PRIVATE='SYNTHETIC_PRIVATE'
CANDIDATES=[{'passage_id':'a','text':'维度：开关\n完整用例 TC-01 | 0.5 | 不调用下游'},{'passage_id':'b','text':'旧需求：开关关闭仍保留校准'}]


def config(**changes):
    from naiyue_rag import LLMRerankSettings
    return LLMRerankSettings.from_dict(dict(model='synthetic-model',base_url='https://rerank.example.invalid/v1/',
        timeout_seconds=3,deadline_seconds=10,max_response_bytes=10000,max_output_tokens=1024,temperature=0,
        extra_body={'thinking':{'type':'disabled'}})|changes)


def payload(**changes):
    return dict(model='synthetic-model',choices=[dict(index=0,finish_reason='stop',message={'role':'assistant',
        'content':json.dumps({'scores':[dict(passage_id='b',score=2),dict(passage_id='a',score=1)]})})],
        usage={'prompt_tokens':12,'completion_tokens':8,'total_tokens':20})|changes


@pytest.fixture
def factory(monkeypatch):
    providers=[]
    def create(handler=None,cfg=None):
        from naiyue_rag.reranking.llm import LLMReranker
        seen=[]
        def capture(request):
            seen.append(request)
            return handler(request) if handler else httpx.Response(200,json=payload())
        transport=Transport(capture)
        monkeypatch.setattr(httpx,'HTTPTransport',lambda **kwargs:transport)
        provider=LLMReranker(cfg or config(),api_key=PRIVATE);providers.append(provider)
        return provider,seen,transport
    yield create
    for p in providers:
        if not p.closed:p.close()


def test_real_sdk_config_reaches_wire_and_usage(factory,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','WRONG');monkeypatch.setenv('OPENAI_BASE_URL','https://wrong.invalid')
    monkeypatch.setenv('OPENAI_ORG_ID',PRIVATE);monkeypatch.setenv('OPENAI_PROJECT_ID',PRIVATE)
    provider,seen,_=factory()
    scores,report=provider.score('这次如何回归？',CANDIDATES)
    assert scores==[dict(passage_id='b',score=2),dict(passage_id='a',score=1)]
    assert report['attempted_requests']==1 and report['http_status']==200 and report['usage']['total_tokens']==20
    req=seen[0];data=json.loads(req.content)
    assert str(req.url)=='https://rerank.example.invalid/v1/chat/completions'
    assert data['model']=='synthetic-model' and data['stream'] is False and data['max_tokens']==1024
    assert data['thinking']=={'type':'disabled'} and data['temperature']==0 and 'tools' not in data
    body=json.loads(data['messages'][1]['content']);assert body==dict(query='这次如何回归？',passages=CANDIDATES)
    assert data['messages'][0]['role']=='system' and 'JSON' in data['messages'][0]['content']
    assert 'openai-organization' not in req.headers and 'openai-project' not in req.headers
    assert req.headers['authorization']=='Bearer '+PRIVATE
    assert max(req.extensions['timeout'].values())<=3


@pytest.mark.parametrize('status',[302,401,429,500])
def test_http_fail_no_retry_no_raw_error(factory,status,caplog):
    from naiyue_rag import RerankError
    provider,seen,_=factory(lambda req:httpx.Response(status,json={'error':{'message':PRIVATE}}))
    with pytest.raises(RerankError,match=f'^rerank_http_{status}$') as caught:provider.score('q',CANDIDATES)
    assert len(seen)==1 and caught.value.report['attempted_requests']==1
    assert PRIVATE not in caplog.text+str(caught.value)+json.dumps(caught.value.to_dict())


@pytest.mark.parametrize('fault',['missing','unknown','duplicate','bool','nan','extra','fenced','length','tool','model','bad_json','usage'])
def test_bad_output_is_atomic_and_usage_is_preserved_when_known(factory,fault):
    from naiyue_rag import RerankError
    raw=payload();choice=raw['choices'][0]
    scores=json.loads(choice['message']['content'])['scores']
    if fault=='missing':scores.pop()
    elif fault=='unknown':scores[0]['passage_id']=PRIVATE
    elif fault=='duplicate':scores[-1]=scores[0].copy()
    elif fault=='bool':scores[0]['score']=True
    elif fault=='nan':scores[0]['score']=float('nan')
    elif fault=='extra':scores[0]['text']=PRIVATE
    elif fault=='length':choice['finish_reason']='length'
    elif fault=='tool':choice['message']['tool_calls']=[{'function':{'name':PRIVATE}}]
    elif fault=='model':raw['model']='WRONG'
    elif fault=='usage':raw['usage']['prompt_tokens']=True
    choice['message']['content']=json.dumps({'scores':scores})
    if fault=='fenced':choice['message']['content']='```json\n'+choice['message']['content']+'\n```'
    if fault=='bad_json':choice['message']['content']='{"scores":[],"scores":[]}'
    provider,_,_=factory(lambda req:httpx.Response(200,json=raw))
    with pytest.raises(RerankError,match='rerank_invalid_output') as caught:provider.score('q',CANDIDATES)
    if fault!='usage':assert caught.value.report['usage']['total_tokens']==20
    assert PRIVATE not in json.dumps(caught.value.to_dict())


def test_missing_usage_stays_unknown(factory):
    raw=payload();raw.pop('usage');p,_,_=factory(lambda req:httpx.Response(200,json=raw))
    assert p.score('q',CANDIDATES)[1]['usage'] is None


@pytest.mark.parametrize('status',[200,500])
def test_byte_limit_covers_error_and_success_streams(factory,status):
    from naiyue_rag import RerankError
    body=Body([b'a'*32,b'b'*32,b'c'*32])
    p,seen,_=factory(lambda req:httpx.Response(status,stream=body),config(max_response_bytes=48))
    with pytest.raises(RerankError,match='rerank_response_too_large') as caught:p.score('q',CANDIDATES)
    assert body.closed and body.reads==2 and len(seen)==1 and caught.value.report['response_bytes']==64


@pytest.mark.parametrize('headers,code',[({'content-length':'99999'},'rerank_response_too_large'),
    ({'content-length':'-1'},'rerank_invalid_response_headers'),({'content-encoding':'gzip'},'rerank_unsupported_content_encoding')])
def test_headers_are_checked_before_read(factory,headers,code):
    from naiyue_rag import RerankError
    body=Body([b'{}']);p,_,_=factory(lambda req:httpx.Response(200,headers=headers,stream=body))
    with pytest.raises(RerankError,match=code):p.score('q',CANDIDATES)
    assert body.closed and body.reads==0


def test_connection_failure_and_deadline_are_safe(factory,monkeypatch):
    from naiyue_rag import RerankError
    def fail(req):raise httpx.ConnectError(PRIVATE)
    p,seen,_=factory(fail)
    with pytest.raises(RerankError,match='rerank_connection_failed'):p.score('q',CANDIDATES)
    assert len(seen)==1
    import naiyue_rag.reranking.transport as transport
    import naiyue_rag.reranking.llm as llm
    class Clock:
        now=0
        def monotonic(self):return self.now
    clock=Clock();monkeypatch.setattr(llm,'time',clock);monkeypatch.setattr(transport,'time',clock)
    def late(req):clock.now=11;return httpx.Response(200,json=payload())
    p,_,_=factory(late)
    with pytest.raises(RerankError,match='rerank_deadline_exceeded'):p.score('q',CANDIDATES)


def test_response_close_failure_and_closed_provider(factory):
    from naiyue_rag import RerankError
    body=Body([json.dumps(payload()).encode()],close_error=True)
    p,_,_=factory(lambda req:httpx.Response(200,stream=body))
    with pytest.raises(RerankError,match='rerank_response_close_failed') as caught:p.score('q',CANDIDATES)
    assert caught.value.report['response_close_error_code']=='rerank_response_close_failed'
    p.close()
    with pytest.raises(RerankError,match='rerank_provider_closed'):p.score('q',CANDIDATES)


@pytest.mark.parametrize('change',[dict(extra_body={'model':'injected'}),dict(extra_body={'thinking':{'type':'other'}}),
    dict(base_url='https://user:secret@x.invalid'),dict(max_output_tokens=True),dict(temperature=float('nan'))])
def test_settings_reject_unsafe_or_ambiguous_config(change):
    from naiyue_rag.core.errors import SettingsError
    with pytest.raises(SettingsError):config(**change)


def test_client_close_failure_keeps_primary_error(factory):
    from naiyue_rag import RerankError
    p,_,transport=factory(lambda req:httpx.Response(500,json={'error':{'message':PRIVATE}}))
    transport.close_error=True
    with pytest.raises(RerankError,match='rerank_http_500') as caught:
        with p:p.score('q',CANDIDATES)
    assert caught.value.report['client_close_error_code']=='rerank_client_close_failed' and p.closed


def test_busy_and_unsafe_environment_fail_before_http(factory,monkeypatch):
    from naiyue_rag import RerankError
    p,seen,_=factory();p._lock.acquire()
    try:
        with pytest.raises(RerankError,match='rerank_provider_busy'):p.score('q',CANDIDATES)
    finally:p._lock.release()
    monkeypatch.setenv('OPENAI_CUSTOM_HEADERS',PRIVATE)
    with pytest.raises(RerankError,match='rerank_unsafe_sdk_environment'):p.score('q',CANDIDATES)
    assert seen==[]
