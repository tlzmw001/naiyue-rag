"""Single batch identity binding through real Provider/SDK using mock transport."""
import json
import pytest
import httpx
from naiyue_rag.encoding.dense_encoder import DenseEncoder
from naiyue_rag.encoding import prepare_document_encoding_inputs,prepare_query_encoding_input
from naiyue_rag import DocumentChunker,IngestionSettings,prepare_document
from naiyue_rag.core.errors import EmbeddingExecutionError
from test_openai_embedding import factory,safe_ambient,payload,Body,PRIVATE
from test_document_chunker import document,offline
from test_encoding_settings import config

@pytest.mark.parametrize('kind',['document','query'])
def test_actual_dense_path_preserves_source_and_reorders_indices(factory,kind):
    cfg=config()
    if kind=='document':
        doc=document('# 功能\n\n开关开启时执行。\n\n## 异常\n\n错误时拒绝。')
        chunks,_=prepare_document(doc,DocumentChunker(IngestionSettings(1000,0)),text_mode='raw')
        items=prepare_document_encoding_inputs([doc],chunks,cfg)
    else:items=[prepare_query_encoding_input(q,cfg) for q in ['开关正常','异常条件']]
    raw=payload(len(items));raw['usage']={'prompt_tokens':7,'total_tokens':7}
    provider,transport=factory(lambda req:httpx.Response(200,json=raw),cfg)
    result,report=DenseEncoder(cfg,provider).encode_batch(items,remaining_seconds=2)
    assert result.input_ids==[i.item_id for i in items] and result.input_hashes==[i.embedding_text_sha256 for i in items]
    assert [v[0] for v in result.vectors]==list(range(1,len(items)+1))
    assert result.usage=={'prompt_tokens':7,'total_tokens':7} and result.source_kind=='service'
    assert report['attempted_requests']==1 and report['http_status']==200
    wire=json.loads(transport.requests[0].content)
    assert wire['input']==[i.embedding_text for i in items]
    assert all(v==2 for v in transport.requests[0].extensions['timeout'].values())
    if kind=='document':assert all(i.source_span is not None for i in items)

@pytest.mark.parametrize('fault',['empty','multi-batch','mutated-hash','wrong-settings','zero','bool'])
def test_dense_preflight_no_requests(factory,fault):
    cfg=config();provider,transport=factory(lambda req:httpx.Response(200,json=payload()),cfg)
    encoder=DenseEncoder(cfg,provider);items=[prepare_query_encoding_input('a',cfg)];seconds=3
    if fault=='empty':items=[]
    elif fault=='multi-batch':items=[prepare_query_encoding_input(q,cfg) for q in ['a','b','c']]
    elif fault=='mutated-hash':items[0].embedding_text=PRIVATE
    elif fault=='wrong-settings':items=[prepare_query_encoding_input('a',config(representation={'query_prefix':'different: '}))]
    elif fault=='zero':seconds=0
    else:seconds=True
    with pytest.raises(EmbeddingExecutionError) as caught:encoder.encode_batch(items,remaining_seconds=seconds)
    assert transport.requests==[] and caught.value.report['attempted_requests']==0

def test_dense_constructor_rejects_mismatched_provider_config(factory):
    provider,transport=factory(lambda req:httpx.Response(200,json=payload()))
    with pytest.raises(EmbeddingExecutionError,match='^embedding_provider_settings_mismatch$'):
        DenseEncoder(config(runtime={'max_response_bytes':400}),provider)
    assert transport.requests==[]

@pytest.mark.parametrize('fault',['dimension','index','model','zero'])
def test_bad_vectors_keep_transport_observation_without_result(factory,fault,caplog):
    cfg=config();raw=payload()
    if fault=='dimension':raw['data'][0]['embedding']=[1.]
    elif fault=='index':raw['data'][0]['index']=True
    elif fault=='model':raw['model']=PRIVATE
    else:raw['data'][0]['embedding']=[0.,0.,0.]
    provider,transport=factory(lambda req:httpx.Response(200,json=raw),cfg)
    with pytest.raises(EmbeddingExecutionError,match='^invalid_embedding_response$') as caught:
        DenseEncoder(cfg,provider).encode_batch([prepare_query_encoding_input('a',cfg)],remaining_seconds=3)
    assert caught.value.report['attempted_requests']==1 and caught.value.report['http_status']==200
    assert len(transport.requests)==1 and PRIVATE not in caplog.text

def test_unknown_usage_and_client_context(factory):
    cfg=config();provider,transport=factory(lambda req:httpx.Response(200,json=payload()),cfg)
    with provider:
        result,report=DenseEncoder(cfg,provider).encode_batch([prepare_query_encoding_input('a',cfg)],remaining_seconds=100)
    assert result.usage is None and result.usage_status=='unknown_missing'
    assert transport.closed and all(v==10 for v in transport.requests[0].extensions['timeout'].values())
    assert set(report)=={'attempted_requests','http_status','response_bytes','elapsed_seconds','error_code',
                         'response_close_error_code','client_close_error_code'}


def test_unexpected_normalization_failure_preserves_safe_request_report(factory,monkeypatch,caplog):
    import naiyue_rag.encoding.dense_encoder as module
    cfg=config();provider,transport=factory(lambda req:httpx.Response(200,json=payload()),cfg)
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    monkeypatch.setattr(module,'normalize_embedding_response',fail)
    with pytest.raises(EmbeddingExecutionError,match='^embedding_encoding_failed$') as caught:
        DenseEncoder(cfg,provider).encode_batch([prepare_query_encoding_input('a',cfg)],remaining_seconds=3)
    assert caught.value.report['attempted_requests']==1 and caught.value.report['http_status']==200
    assert len(transport.requests)==1 and PRIVATE not in caplog.text


def test_deadline_checked_after_normalization(factory,monkeypatch):
    import naiyue_rag.encoding.dense_encoder as module
    cfg=config();provider,_=factory(lambda req:httpx.Response(200,json=payload()),cfg)
    original=module.normalize_embedding_response
    def slow(*args,**kwargs):
        result=original(*args,**kwargs)
        monkeypatch.setattr(module.time,'monotonic',lambda:4.)
        return result
    monkeypatch.setattr(module,'normalize_embedding_response',slow)
    with pytest.raises(EmbeddingExecutionError,match='^embedding_deadline_exceeded$') as caught:
        DenseEncoder(cfg,provider).encode_batch([prepare_query_encoding_input('a',cfg)],remaining_seconds=3)
    assert caught.value.report['http_status']==200 and caught.value.report['elapsed_seconds']==4
