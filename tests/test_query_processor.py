"""Pure query preflight, retaining text and explicit scope semantics."""
import pytest
from test_encoding_settings import config

DOC='doc-'+'a'*64
QUERY='  不开启 cvr_ltv 0 1 0.5 TC-01 source:L2_A.md https://example.invalid/a:b  '


def processor(**changes):
    from naiyue_rag.query.query_processor import QueryProcessor
    return QueryProcessor(config(**changes),max_scope_documents=2)


def test_preflight_preserves_text_and_copies_scope():
    job=processor();scope=[DOC];excluded=[]
    result=job.process(QUERY,scope_document_ids=scope,exclude_document_ids=excluded,expected_revision=0)
    scope.clear();excluded.append(DOC)
    assert result.query==QUERY.strip() and result.raw_query==QUERY
    assert result.scope_document_ids==(DOC,) and result.exclude_document_ids==()
    assert result.expected_revision==0 and QUERY not in repr(result)
    assert job.process(QUERY).scope_document_ids is None
    assert job.process(QUERY,scope_document_ids=[]).scope_document_ids==()


@pytest.mark.parametrize('query',['',' \n ',None,True,[],123,'\ud800'])
def test_invalid_text_rejected(query):
    from naiyue_rag.core.errors import QueryJobError
    with pytest.raises(QueryJobError) as caught:processor().process(query)
    assert caught.value.stage=='request' and caught.value.code=='query_invalid_request'


@pytest.mark.parametrize('field,value',[
    ('scope_document_ids',DOC),('scope_document_ids',(DOC,)),('scope_document_ids',True),
    ('scope_document_ids',[DOC,DOC]),('scope_document_ids',['../A']),('scope_document_ids',['doc-'+'A'*64]),
    ('scope_document_ids',[None]),('exclude_document_ids',{}),('exclude_document_ids',[DOC,DOC]),
    ('exclude_document_ids',['unit-'+'a'*64]),('exclude_document_ids',[DOC,'doc-'+'b'*64,'doc-'+'c'*64]),
    ('expected_revision',True),('expected_revision',-1),('expected_revision',2**63),('expected_revision','1')])
def test_invalid_scope_or_revision_is_rejected(field,value):
    from naiyue_rag.core.errors import QueryJobError
    with pytest.raises(QueryJobError) as caught:processor().process(QUERY,**{field:value})
    assert caught.value.stage=='request'
    assert caught.value.code==('query_invalid_request' if field=='expected_revision' else 'query_invalid_scope')


@pytest.mark.parametrize('runtime',[{'max_input_utf8_bytes':10},{'max_batch_input_utf8_bytes':10}])
def test_model_input_limits_include_query_prefix(runtime):
    from naiyue_rag.core.errors import QueryJobError
    with pytest.raises(QueryJobError) as caught:processor(runtime=runtime).process(QUERY)
    assert caught.value.stage=='request' and caught.value.code=='encoding_input_limit'


@pytest.mark.parametrize('limit',[True,0,-1,1.5])
def test_processor_configuration_is_strict(limit):
    from naiyue_rag.query.query_processor import QueryProcessor
    from naiyue_rag.core.errors import QueryJobError
    with pytest.raises(QueryJobError):QueryProcessor(config(),max_scope_documents=limit)
