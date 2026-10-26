"""Domain contracts preserve real synthetic source/candidate data without network."""
import copy
from dataclasses import is_dataclass
import json

import pytest

from naiyue_rag.core.errors import ContractError, RetrievalError
from naiyue_rag.core.types import SourceSpan, Document, Chunk, QueryRequest, RetrievalResult
from experiments.vector_index import load_corpus
from vector_fixtures import CORPUS


@pytest.fixture(scope='module')
def corpus():
    return load_corpus(CORPUS,'examples/mock-v1')


def request():
    return {'query':'查询历史边界','scope_document_ids':None,'exclude_document_ids':[],
            'candidate_k':20,'max_context_chars':8000}


def test_reference_dataclass_shape_and_real_units_roundtrip(corpus):
    assert all(is_dataclass(cls) for cls in [SourceSpan,Document,Chunk,QueryRequest,RetrievalResult])
    for source in corpus['sources'].values():
        document=Document.from_source_record(source)
        assert document.id==source['document_id'] and document.text==source['text']
        assert document.metadata['source_path']==source['relative_path']
        assert document.metadata['source_sha256']==source['source_sha256']
        assert Document.from_dict(document.to_dict()).to_dict()==document.to_dict()
        json.dumps(document.to_dict(),allow_nan=False)
    for old in corpus['units']:
        span=SourceSpan.from_dict(old['body_span'])
        assert span.to_dict()==old['body_span']
        chunk=Chunk.from_legacy_unit(old)
        assert chunk.id==old['unit_id'] and chunk.text==old['body'] and chunk.source_ref==old['document_id']
        assert chunk.start_offset==old['body_span']['start_char']
        assert chunk.end_offset==old['body_span']['end_char']
        assert chunk.to_legacy_unit()==old
        assert Chunk.from_dict(chunk.to_dict()).to_legacy_unit()==old
        json.dumps(chunk.to_dict(),allow_nan=False)


def test_empty_document_kept_and_metadata_extensions_retained():
    doc=Document('id','',{'source_path':'empty.md','source_sha256':'a'*64,'extra':{'values':[1,True,None]}})
    assert Document.from_dict(doc.to_dict()).to_dict()==doc.to_dict()


@pytest.mark.parametrize('change', [
    {'start_char':True}, {'start_char':-1}, {'end_char':0}, {'line_start':0},
    {'line_start':True}, {'line_end':0}, {'source_sha256':'wrong'}, {'extra':'not allowed'},
])
def test_invalid_span_is_explicit(corpus,change):
    with pytest.raises(ContractError,match='invalid_span'):
        SourceSpan.from_dict(corpus['units'][0]['body_span']|change)


@pytest.mark.parametrize('field', ['source_path','source_sha256'])
def test_document_missing_source_metadata_is_explicit(field):
    meta={'source_path':'x.md','source_sha256':'a'*64};del meta[field]
    with pytest.raises(ContractError,match='invalid_document'):
        Document('id','正文',meta)


@pytest.mark.parametrize('fault', ['id','body','span','hash','json','missing','offset','reference'])
def test_chunk_invalid_or_inconsistent_fields_rejected(corpus,fault):
    unit=copy.deepcopy(corpus['units'][0])
    if fault=='id':unit['unit_id']=''
    elif fault=='body':unit['body']=None
    elif fault=='span':unit['body_span']['end_char']=unit['body_span']['start_char']
    elif fault=='hash':unit['body_span']['source_sha256']='b'*64
    elif fault=='json':unit['component_metadata']['bad']=float('nan')
    elif fault=='missing':del unit['contexts']
    elif fault=='reference':unit['document_id']=''
    if fault=='offset':
        value=Chunk.from_legacy_unit(unit);value.end_offset+=1
        with pytest.raises(ContractError):value.to_legacy_unit()
    else:
        with pytest.raises(ContractError):Chunk.from_legacy_unit(unit)


@pytest.mark.parametrize('change,code', [
    ({'query':''},'invalid_query'), ({'query':'\ud800'},'invalid_query'),
    ({'query':'汉'*1025},'invalid_query'), ({'extra':'x'},'invalid_request'),
    ({'scope_document_ids':[]},'invalid_scope'), ({'scope_document_ids':['a','a']},'invalid_scope'),
    ({'exclude_document_ids':None},'invalid_scope'), ({'candidate_k':True},'invalid_candidate_k'),
    ({'candidate_k':21},'invalid_candidate_k'), ({'max_context_chars':0},'invalid_context_budget'),
])
def test_request_same_legacy_limits_and_codes(change,code):
    with pytest.raises(RetrievalError,match=code) as error:
        QueryRequest.from_dict(request()|change)
    assert error.value.stage=='request' and error.value.code==code


def test_request_copy_and_roundtrip():
    raw=request()|{'scope_document_ids':['a'],'exclude_document_ids':['b']}
    value=QueryRequest.from_dict(raw);raw['scope_document_ids'].append('c')
    output=value.to_dict();output['exclude_document_ids'].append('d')
    assert value.to_dict()==request()|{'scope_document_ids':['a'],'exclude_document_ids':['b']}


@pytest.mark.parametrize('method,kind,score', [('vector',None,-.5),('sparse','bm25',18.),('hybrid','rrf',.03)])
def test_candidate_exact_fields_and_scales(corpus,method,kind,score):
    row=copy.deepcopy(corpus['units'][0])|{'score':score,'rank':1,'retrieval_method':method,
         'retrieval_info':{'dense_rank':1,'cosine':-.5},'distance':1.5,'reference_similarity':.25,
         'reason':'budget_excluded','extension':{'x':[1,2]}}
    if kind is not None:row['score_kind']=kind
    value=RetrievalResult.from_candidate(row)
    assert value.chunk_id==row['unit_id'] and value.text==row['body'] and value.score==score
    assert value.to_candidate()==row
    assert RetrievalResult.from_dict(value.to_dict()).to_candidate()==row
    assert ('score_kind' in value.to_candidate())==('score_kind' in row)
    json.dumps(value.to_dict(),allow_nan=False)


@pytest.mark.parametrize('score', [True,float('nan'),float('inf'),None,'0.8'])
def test_invalid_candidate_score(corpus,score):
    row=corpus['units'][0]|{'score':score,'rank':1,'retrieval_method':'vector'}
    with pytest.raises(ContractError,match='invalid_result'):RetrievalResult.from_candidate(row)


def test_source_chunk_candidate_copies_do_not_alias(corpus):
    source=copy.deepcopy(next(iter(corpus['sources'].values())))
    document=Document.from_source_record(source);source['line_starts'].clear()
    assert document.metadata['line_starts']
    out=document.to_dict();out['metadata']['line_starts'].clear()
    assert document.metadata['line_starts']
    unit=copy.deepcopy(next(u for u in corpus['units'] if u['kind']=='test_case'))
    chunk=Chunk.from_legacy_unit(unit);original=copy.deepcopy(unit)
    unit['contexts'].clear();out=chunk.to_legacy_unit();out['case_fields'].clear()
    assert chunk.to_legacy_unit()==original
    row=original|{'score':.7,'rank':1,'retrieval_method':'vector'}
    value=RetrievalResult.from_candidate(row);row['contexts'].clear()
    out=value.to_candidate();out['case_fields'].clear()
    assert value.to_candidate()['contexts'] and value.to_candidate()['case_fields']


def test_repr_and_errors_never_echo_payload(corpus):
    sentinel='private-payload-marker'
    doc=Document('id',sentinel,{'source_path':'x.md','source_sha256':'a'*64,'note':sentinel})
    unit=copy.deepcopy(corpus['units'][0]);unit['component_metadata']['private']=sentinel
    chunk=Chunk.from_legacy_unit(unit)
    candidate=unit|{'score':.2,'rank':1,'retrieval_method':'vector'}
    values=[doc,chunk,QueryRequest.from_dict(request()|{'query':sentinel}),RetrievalResult.from_candidate(candidate)]
    assert all(sentinel not in repr(v) for v in values)
    with pytest.raises(ContractError) as error:Document('id',sentinel,{'source_path':sentinel})
    assert sentinel not in str(error.value)


def test_serialization_bridge_order_is_not_domain_equality(corpus):
    unit=corpus['units'][0]
    chunk=Chunk.from_legacy_unit(unit)
    assert Chunk.from_dict(chunk.to_dict())==chunk
    candidate=unit|{'score':.5,'rank':1,'retrieval_method':'vector'}
    result=RetrievalResult.from_candidate(candidate)
    assert RetrievalResult.from_dict(result.to_dict())==result


def test_reserved_aliases_in_metadata_cannot_be_silently_overwritten(corpus):
    unit=corpus['units'][0]
    for key in ['unit_id','body','document_id']:
        value=Chunk.from_legacy_unit(unit).to_dict()
        value['metadata'][key]='conflicting-value'
        with pytest.raises(ContractError,match='invalid_chunk'):Chunk.from_dict(value)
    row=unit|{'score':.5,'rank':1,'retrieval_method':'vector'}
    for key in ['unit_id','body','score']:
        value=RetrievalResult.from_candidate(row).to_dict()
        value['metadata'][key]='conflicting-value'
        with pytest.raises(ContractError,match='invalid_result'):RetrievalResult.from_dict(value)
