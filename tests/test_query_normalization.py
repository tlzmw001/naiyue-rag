"""Actual query identity, raw-input audit and legacy result compatibility."""
import copy
import hashlib
import json
import pytest
from test_query_encoding import setup
from test_query_processor import processor
from test_query_preparation import job
from test_document_manager import prepared
from test_dense_retrieval import native_query
from test_evidence_response import build


def sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()


@pytest.mark.parametrize('padding',['','  ','\n\t','\u3000\u00a0'])
def test_actual_query_and_pair_fingerprints_ignore_only_outer_whitespace(padding):
    actual='检查 cvr_ltv  0.5\nTC-01 https://example.invalid/a:b'
    raw=padding+actual+padding
    processed=processor().process(raw)
    assert processed.query==actual and processed.raw_query==raw
    encoder,dense,sparse=setup()
    result=encoder.encode(raw);reference=encoder.encode(actual)
    assert result.input.to_dict()==reference.input.to_dict()
    assert result.input.query_sha256==sha(actual)
    assert result.raw_query_sha256==sha(raw)
    assert result.input.embedding_text=='query: '+actual
    assert result.report.input_fingerprint==reference.report.input_fingerprint
    assert dense.calls[0][0][0]['retrieval_text']==actual
    assert sparse.calls[0][0]['retrieval_text']==actual
    assert raw not in json.dumps(result.report.to_dict(),ensure_ascii=False)


def test_input_limits_count_the_actual_prefixed_query():
    encoder,dense,_=setup()
    raw=' '*10000+'检查'+' '*10000
    result=encoder.encode(raw)
    assert result.input.embedding_text=='query: 检查' and len(dense.calls)==1
    assert result.raw_query_sha256==sha(raw)


def test_query_result_legacy_shape_and_unknown_fields_are_strict():
    from naiyue_rag import QueryEncodingResult
    from naiyue_rag.core.errors import EncodingError
    result=setup()[0].encode('  检查  ')
    modern=result.to_dict()
    assert QueryEncodingResult.from_dict(json.loads(json.dumps(modern))).to_dict()==modern
    legacy=copy.deepcopy(modern);legacy.pop('raw_query_sha256')
    restored=QueryEncodingResult.from_dict(legacy)
    assert restored.raw_query_sha256==restored.input.query_sha256
    for value in ('bad',True,123,None):
        with pytest.raises(EncodingError):QueryEncodingResult.from_dict(modern|{'raw_query_sha256':value})
    with pytest.raises(EncodingError):QueryEncodingResult.from_dict(modern|{'unknown':1})


def test_pipeline_raw_binding_empty_scope_and_legacy_prepared(job):
    from naiyue_rag import PreparedQuery
    from naiyue_rag.core.errors import QueryJobError
    pipeline,_,_,dense,_=job;raw=' \n检查 cvr_ltv  0.5\t'
    result=pipeline.prepare(raw)
    assert result.query_sha256==sha(raw.strip())
    assert result.raw_query_sha256==result.encoding.raw_query_sha256==sha(raw)
    assert result.encoding.input.retrieval_text==raw.strip()
    modern=result.to_dict()
    assert PreparedQuery.from_dict(json.loads(json.dumps(modern))).to_dict()==modern
    legacy=copy.deepcopy(modern);legacy.pop('raw_query_sha256');legacy['encoding'].pop('raw_query_sha256')
    restored=PreparedQuery.from_dict(legacy)
    assert restored.raw_query_sha256==restored.query_sha256
    tampered=copy.deepcopy(modern);tampered['raw_query_sha256']='0'*64
    with pytest.raises(QueryJobError):PreparedQuery.from_dict(tampered)
    before=len(dense.calls);empty=pipeline.prepare(raw,scope_document_ids=[])
    assert empty.status=='empty_scope' and empty.raw_query_sha256==sha(raw)
    assert empty.query_sha256==sha(raw.strip()) and len(dense.calls)==before


def test_final_evidence_and_reranker_use_actual_query(job,native_query):
    builder,ranked=build(job)
    response=builder.build(ranked);prepared_query=ranked.hybrid.prepared
    assert response['schema_version']==2
    assert response['query_sha256']==prepared_query.encoding.input.query_sha256
    assert response['raw_query_sha256']==prepared_query.raw_query_sha256
    assert prepared_query.encoding.input.retrieval_text==prepared_query.encoding.input.retrieval_text.strip()
    assert 'raw_query' not in response


def test_legacy_untrimmed_query_result_is_not_reencoded_or_rewritten():
    from naiyue_rag import QueryEncodingResult
    from naiyue_rag.core.encoding_report import input_fingerprint
    from naiyue_rag.core.encoding_types import EncodingInput
    raw=setup()[0].encode('检查').to_dict();raw.pop('raw_query_sha256')
    text='  检查  ';item=raw['input'];actual_hash=sha(text)
    item.update(item_id='query-'+actual_hash,retrieval_text=text,retrieval_text_sha256=actual_hash,
        embedding_text='query: '+text,embedding_text_sha256=sha('query: '+text),query_sha256=actual_hash)
    raw['sparse'].update(item_id=item['item_id'],retrieval_text_sha256=actual_hash)
    fingerprint=input_fingerprint([EncodingInput.from_dict(item)])
    raw['report']['input_fingerprint']=fingerprint
    raw['report']['batches'][0]['input_fingerprint']=fingerprint
    restored=QueryEncodingResult.from_dict(json.loads(json.dumps(raw)))
    assert restored.input.to_dict()==item
    assert restored.raw_query_sha256==actual_hash and restored.report.to_dict()==raw['report']
    assert restored.dense_vector==raw['dense_vector']


def test_unactivated_keeps_both_hashes_without_encoding(tmp_path):
    from naiyue_rag import QueryPipeline
    from naiyue_rag.storage import DocumentManager,ChromaSettings,BM25Settings
    from test_storage_bundle import storage_settings
    encoder,dense,sparse=setup()
    manager=DocumentManager(storage_settings(tmp_path),ChromaSettings('knowledge_hub',2),BM25Settings(1.5,.75),project_root=tmp_path)
    raw=' \n检查\t';result=QueryPipeline(manager,encoder).prepare(raw)
    assert result.status=='unactivated' and result.query_sha256==sha(raw.strip())
    assert result.raw_query_sha256==sha(raw) and dense.calls==sparse.calls==[]
