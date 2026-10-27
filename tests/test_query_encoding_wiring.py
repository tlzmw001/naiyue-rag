"""Formal query encoding through pinned SDK/mock HTTP and real lexical Sparse."""
import json
import httpx
import pytest
import yaml
from naiyue_rag import (QueryEncoder,QueryEncodingResult,BatchProcessor,DenseEncoder,SparseEncoder,
    load_encoding_settings,load_sparse_encoding_settings,MarkdownLoader,DocumentChunker,IngestionSettings,
    prepare_knowledge_base,prepare_document_encoding_inputs)
from naiyue_rag.core.errors import EncodingJobError
from test_openai_embedding import factory,safe_ambient,payload,PRIVATE
from test_encoding_settings import config_data
from test_sparse_encoding_settings import sparse_config
from test_document_chunker import offline

QUERY='  开关 关 开关 TC-01 cvr_ltv 0.5  '


def settings(tmp_path,**sparse_changes):
    path=tmp_path/'encoding.yaml';path.write_text(yaml.safe_dump(config_data()))
    spath=tmp_path/'sparse.yaml';raw=sparse_config(tmp_path,**sparse_changes).to_dict();raw['cache_dir']='./cache'
    spath.write_text(yaml.safe_dump(raw))
    return load_encoding_settings(path),load_sparse_encoding_settings(spath)


def test_yaml_sdk_sparse_result_shares_document_identities_and_client(tmp_path,factory):
    cfg,scfg=settings(tmp_path)
    root=tmp_path/'knowledge';root.mkdir();(root/'example.md').write_text('# 开关\n\n开关开启时执行 cvr_ltv。')
    docs=MarkdownLoader(root,'query-demo-kb',1_048_576).load_all()
    chunks,relations,issues=prepare_knowledge_base(docs,DocumentChunker(IngestionSettings(1000,200)),text_mode='raw')
    inputs=prepare_document_encoding_inputs(docs,chunks,cfg)
    def respond(req):
        raw=payload(len(json.loads(req.content)['input']));raw['usage']=dict(prompt_tokens=7,total_tokens=7)
        return httpx.Response(200,json=raw)
    provider,transport=factory(respond,cfg);dense=DenseEncoder(cfg,provider);sparse=SparseEncoder(cfg,scfg)
    with provider:
        documents=BatchProcessor(cfg,dense,sparse).process(inputs)
        query=QueryEncoder(cfg,dense,sparse).encode(QUERY)
        assert not provider.closed
    assert provider.closed and transport.closed
    assert query.input.model_space_id==documents.model_space_id
    assert query.input.representation_id==documents.representation_id
    assert query.tokenizer_id==documents.tokenizer_id and query.dimensions==documents.dimensions
    assert query.query_terms==['开关','tc-01','cvr_ltv','0.5']
    assert query.sparse.term_frequencies['开关']==2 and query.sparse.doc_length==5
    assert len(transport.requests)==len(documents.report.batches)+1
    wire=json.loads(transport.requests[-1].content)
    assert wire['input']==['query: '+QUERY.strip()] and wire['encoding_format']=='float'
    assert query.input.retrieval_text==QUERY.strip() and query.input.source_span is None
    assert query.report.requests['attempted_requests']==1 and query.report.usage['total_tokens']==7
    assert QueryEncodingResult.from_dict(json.loads(json.dumps(query.to_dict()))).to_dict()==query.to_dict()
    assert PRIVATE not in json.dumps(query.to_dict())

@pytest.mark.parametrize('minimum,terms',[(2,[]),(1,['关'])])
def test_actual_empty_terms_and_configurable_chinese_length(tmp_path,factory,minimum,terms):
    cfg,scfg=settings(tmp_path,min_chinese_term_length=minimum)
    provider,_=factory(lambda req:httpx.Response(200,json=payload()),cfg)
    result=QueryEncoder(cfg,DenseEncoder(cfg,provider),SparseEncoder(cfg,scfg)).encode('关')
    assert result.query_terms==terms and result.report.status=='success'
    assert result.report.usage['status']=='unknown' and result.report.usage['total_tokens'] is None

@pytest.mark.parametrize('fault',['400','429','503','network','dimension','missing-usage','invalid-usage','sparse-limit'])
def test_actual_failure_or_unknown_usage_preserves_observation(tmp_path,factory,fault,caplog):
    cfg,scfg=settings(tmp_path,max_terms_per_input=1 if fault=='sparse-limit' else 10000)
    def respond(req):
        if fault=='network':raise httpx.ConnectError(PRIVATE,request=req)
        if fault.isdigit():return httpx.Response(int(fault),json={'error':{'message':PRIVATE}})
        raw=payload()
        if fault=='dimension':raw['data'][0]['embedding']=[1.]
        elif fault=='invalid-usage':raw['usage']=dict(prompt_tokens=True,total_tokens=3)
        elif fault=='sparse-limit':raw['usage']=dict(prompt_tokens=7,total_tokens=7)
        return httpx.Response(200,json=raw)
    provider,transport=factory(respond,cfg)
    encoder=QueryEncoder(cfg,DenseEncoder(cfg,provider),SparseEncoder(cfg,scfg))
    if fault in ('missing-usage','invalid-usage'):
        result=encoder.encode(QUERY);report=result.report.to_dict()
        assert report['status']=='success' and report['usage']['status']=='unknown'
        assert report['batches'][0]['usage_status']==('unknown_missing' if fault=='missing-usage' else 'unknown_invalid')
    else:
        with pytest.raises(EncodingJobError) as caught:encoder.encode(QUERY)
        report=caught.value.report
        assert report['error']['stage']==('sparse' if fault=='sparse-limit' else 'dense')
        assert caught.value.code==('sparse_term_limit' if fault=='sparse-limit' else
            'embedding_connection_failed' if fault=='network' else 'invalid_embedding_response' if fault=='dimension' else f'embedding_http_{fault}')
    assert len(transport.requests)==1 and report['requests']['attempted_requests']==1
    assert report['requests']['http_responses_observed']==(0 if fault=='network' else 1)
    assert report['usage']['total_tokens']==(7 if fault=='sparse-limit' else None)
    assert PRIVATE not in json.dumps(report)+caplog.text


def test_bad_query_never_issues_http_request(tmp_path,factory):
    cfg,scfg=settings(tmp_path);provider,transport=factory(lambda req:httpx.Response(200,json=payload()),cfg)
    encoder=QueryEncoder(cfg,DenseEncoder(cfg,provider),SparseEncoder(cfg,scfg))
    with pytest.raises(EncodingJobError):encoder.encode(' \n ')
    assert transport.requests==[]
