"""Standalone YAML -> real M1/M2 -> SDK mock HTTP + real jieba -> paired JSON result."""
import json
import pytest
import httpx
import yaml
from naiyue_rag import MarkdownLoader,DocumentChunker,IngestionSettings,prepare_knowledge_base,load_encoding_settings
from naiyue_rag.core.sparse_encoding_settings import load_sparse_encoding_settings
from naiyue_rag.encoding import prepare_document_encoding_inputs,DenseEncoder,SparseEncoder
from naiyue_rag import BatchProcessor
from naiyue_rag.core.encoded_types import EncodingResult
from naiyue_rag.core.errors import EncodingJobError
from test_openai_embedding import factory,safe_ambient,payload,PRIVATE
from test_encoding_settings import config_data
from test_sparse_encoding_settings import sparse_config
from test_document_chunker import offline

@pytest.mark.parametrize('mode',['raw','labeled_case'])
def test_real_pipeline_produces_72_pairs_with_no_network(tmp_path,factory,mode):
    raw=config_data();raw['representation']['document_text_mode']=mode
    path=tmp_path/'encoding.yaml';path.write_text(yaml.safe_dump(raw));cfg=load_encoding_settings(path)
    spath=tmp_path/'sparse.yaml';sraw=sparse_config(tmp_path).to_dict();spath.write_text(yaml.safe_dump(sraw))
    scfg=load_sparse_encoding_settings(spath)
    docs=MarkdownLoader('examples/mock-v1/knowledge','batch-kb',1_048_576).load_all()
    chunks,relations,issues=prepare_knowledge_base(docs,DocumentChunker(IngestionSettings(1000,200)),text_mode=mode)
    items=prepare_document_encoding_inputs(docs,chunks,cfg);before=[c.to_dict() for c in chunks]
    def respond(req):
        body=json.loads(req.content);raw=payload(len(body['input']));raw['usage']=dict(prompt_tokens=2,total_tokens=2)
        return httpx.Response(200,json=raw)
    provider,transport=factory(respond,cfg);sparse=SparseEncoder(cfg,scfg)
    with provider:
        result=BatchProcessor(cfg,DenseEncoder(cfg,provider),sparse).process(items)
        assert not provider.closed
    assert provider.closed and transport.closed
    assert len(docs)==12 and len(result.records)==len(items)==72
    assert len(transport.requests)==36
    assert result.report.requests['attempted_requests']==36 and result.report.usage['total_tokens']==72
    assert [r.input.item_id for r in result.records]==[i.item_id for i in items]
    assert all(r.sparse.tokenizer_id==sparse.tokenizer_id for r in result.records)
    assert sum(c.metadata['kind']=='test_case' for c in chunks)==12
    assert [c.to_dict() for c in chunks]==before
    serialized=result.to_dict()
    assert EncodingResult.from_dict(json.loads(json.dumps(serialized,ensure_ascii=False))).to_dict()==serialized
    assert PRIVATE not in json.dumps(serialized)

@pytest.mark.parametrize('fault',['bad-vector','missing-usage','invalid-usage','network'])
def test_actual_dense_failure_or_unknown_usage_reports_request_facts(factory,fault,tmp_path,caplog):
    from test_batch_processor import inputs
    from test_sparse_encoding_settings import sparse_config
    from test_encoding_settings import config
    cfg=config();calls=[]
    def respond(req):
        calls.append(req)
        if fault=='network':raise httpx.ConnectError(PRIVATE,request=req)
        body=json.loads(req.content);raw=payload(len(body['input']))
        if fault=='bad-vector':raw['data'][0]['embedding']=[0.,0.,0.]
        elif fault=='invalid-usage':raw['usage']=dict(prompt_tokens=True,total_tokens=3)
        return httpx.Response(200,json=raw)
    provider,transport=factory(respond,cfg)
    job=BatchProcessor(cfg,DenseEncoder(cfg,provider),SparseEncoder(cfg,sparse_config(tmp_path)))
    if fault in ('bad-vector','network'):
        with pytest.raises(EncodingJobError) as caught:job.process(inputs(cfg))
        report=caught.value.report
        assert len(calls)==1 and report['completed_batch_count']==0
        assert report['requests']['http_responses_observed']==(0 if fault=='network' else 1)
    else:
        report=job.process(inputs(cfg)).report.to_dict()
        assert len(calls)==3 and report['completed_batch_count']==3
        assert all(b['usage_status']==('unknown_missing' if fault=='missing-usage' else 'unknown_invalid') for b in report['batches'])
    assert report['requests']['attempted_requests']==len(calls)
    assert report['usage']['status']=='unknown' and report['usage']['total_tokens'] is None
    assert PRIVATE not in json.dumps(report)+caplog.text

@pytest.mark.parametrize('status',[400,429,503])
def test_actual_http_status_error_preserves_status_and_attempt(factory,tmp_path,status):
    from test_batch_processor import inputs
    from test_encoding_settings import config
    cfg=config();provider,transport=factory(lambda req:httpx.Response(status,json={'error':{'message':PRIVATE}}),cfg)
    job=BatchProcessor(cfg,DenseEncoder(cfg,provider),SparseEncoder(cfg,sparse_config(tmp_path)))
    with pytest.raises(EncodingJobError,match=f'^embedding_http_{status}$') as caught:job.process(inputs(cfg))
    report=caught.value.report
    assert len(transport.requests)==1 and report['requests']['attempted_requests']==1
    assert report['batches'][0]['request_report']['http_status']==status
    assert report['usage']['unknown_usage_requests']==1
    assert PRIVATE not in json.dumps(report)
