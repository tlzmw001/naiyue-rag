"""Actual source/view/layout preparation, deterministic batching, no provider calls."""
import copy
import hashlib
import json

import pytest

from naiyue_rag import DocumentChunker,prepare_document
from naiyue_rag.core.encoding_types import EncodingInput
from naiyue_rag.core.errors import EncodingError
from naiyue_rag.encoding import prepare_document_encoding_inputs,prepare_query_encoding_input,plan_encoding_batches
from test_document_chunker import document,settings,offline,HEADER,SEP,ROW
from test_encoding_settings import config


@pytest.mark.parametrize('layout',['view_only','contexts_then_view'])
@pytest.mark.parametrize('mode',['raw','labeled_case'])
def test_real_m2_to_encoding_preserves_source_and_layout(tmp_path,layout,mode):
    source=document(f'# 测试用例\n\n## 维度\n{HEADER}\n{SEP}\n{ROW}\n','L2/A_测试用例.md')
    chunks,_=prepare_document(source,DocumentChunker(settings(tmp_path)),text_mode=mode)
    before=[c.to_dict() for c in chunks]
    cfg=config(representation={'document_text_mode':mode,'text_layout':layout})
    inputs=prepare_document_encoding_inputs([source],chunks,cfg)
    assert len(inputs)==len(chunks)
    for item,chunk in zip(inputs,chunks):
        view=chunk.metadata['retrieval_view']['text']
        expected=view if layout=='view_only' else '\n'.join([c['text'] for c in chunk.metadata['contexts']]+[view])
        assert item.retrieval_text==expected and item.embedding_text=='passage: '+expected
        assert item.item_id==chunk.id and item.source_span==chunk.metadata['body_span']
        assert item.source_document_id==source.id and item.source_sha256==source.metadata['source_sha256']
        assert item.embedding_text_sha256==hashlib.sha256(item.embedding_text.encode()).hexdigest()
        assert EncodingInput.from_dict(json.loads(json.dumps(item.to_dict()))).to_dict()==item.to_dict()
    assert [c.to_dict() for c in chunks]==before


@pytest.mark.parametrize('fault',['body','context','view','hash','duplicate','missing-source','cross-library','unsafe-path'])
def test_invalid_document_input_never_becomes_encoding_text(tmp_path,fault,caplog):
    source=document('# A\n正文');chunks,_=prepare_document(source,DocumentChunker(settings(tmp_path)),text_mode='raw')
    if fault=='body':chunks[0].text='X'*len(chunks[0].text)
    elif fault=='context':chunks[0].metadata['contexts'][0]['text']='SYNTHETIC_PRIVATE'
    elif fault=='view':chunks[0].metadata['retrieval_view']['text']='SYNTHETIC_PRIVATE'
    elif fault=='hash':chunks[0].metadata['retrieval_view']['text_sha256']='0'*64
    elif fault=='duplicate':chunks.append(copy.deepcopy(chunks[0]))
    elif fault=='missing-source':source.id='other'
    elif fault=='cross-library':source.metadata['knowledge_base_id']='other'
    else:
        source.metadata['source_path']='../SYNTHETIC_PRIVATE.md'
        for chunk in chunks:chunk.metadata['source_path']=source.metadata['source_path']
    with pytest.raises(EncodingError,match='^invalid_encoding_input$'):
        prepare_document_encoding_inputs([source],chunks,config())
    assert 'SYNTHETIC_PRIVATE' not in caplog.text


def test_query_preserves_raw_text_and_empty_documents(tmp_path):
    query='  检查开关  ';item=prepare_query_encoding_input(query,config())
    assert item.retrieval_text==query and item.embedding_text=='query: '+query
    assert item.query_sha256==hashlib.sha256(query.encode()).hexdigest()
    assert item.source_span is None and item.source_document_id is None
    assert prepare_document_encoding_inputs([document('')],[],config())==[]
    assert plan_encoding_batches([],config())==[]
    with pytest.raises(EncodingError,match='^invalid_encoding_input$'):prepare_query_encoding_input('  ',config())


def test_batch_count_bytes_and_whole_job_limits():
    cfg=config(representation={'query_prefix':''},runtime={'batch_size':2,'max_batch_input_utf8_bytes':9})
    inputs=[prepare_query_encoding_input(q,cfg) for q in ['中文','a','字','bb']]
    batches=plan_encoding_batches(inputs,cfg)
    assert [[i.retrieval_text for i in b] for b in batches]==[['中文','a'],['字','bb']]
    smaller=config(representation={'query_prefix':''},runtime={'max_batch_input_utf8_bytes':6,'max_requests':2})
    with pytest.raises(EncodingError,match='^encoding_request_limit$'):plan_encoding_batches(inputs,smaller)
    with pytest.raises(EncodingError,match='^encoding_input_limit$'):
        prepare_query_encoding_input('中'*2,config(runtime={'max_input_utf8_bytes':5}))


def test_mutated_hash_or_profile_cannot_bypass_validation():
    cfg=config();item=prepare_query_encoding_input('original',cfg)
    item.embedding_text+='SYNTHETIC_PRIVATE'
    with pytest.raises(EncodingError,match='^invalid_encoding_input$'):plan_encoding_batches([item],cfg)
    other=prepare_query_encoding_input('original',config(embedding={'model_revision':'new'}))
    with pytest.raises(EncodingError,match='^encoding_identity_mismatch$'):plan_encoding_batches([other],cfg)
