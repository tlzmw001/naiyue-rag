"""Real library preparation calls relations plus the existing single-doc pipeline."""
from pathlib import Path

import pytest

from naiyue_rag import MarkdownLoader,DocumentChunker,prepare_knowledge_base
from naiyue_rag.core.errors import RelationError,PreparationError
from naiyue_rag.ingestion import knowledge_preparation as module
from test_document_chunker import settings,assert_bound,offline


def test_mock_library_calls_real_stages_and_keeps_relation_quotes(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1]/'examples/mock-v1/knowledge'
    docs=MarkdownLoader(root,'structure-kb',1_048_576).load_all()
    chunker=DocumentChunker(settings(tmp_path,1000,200));visited=[]
    original_relations=module.build_document_relations;original_document=module.prepare_document
    def relations(values):visited.append('relations');return original_relations(values)
    def prepare(value,*args,**kwargs):visited.append(value.id);return original_document(value,*args,**kwargs)
    monkeypatch.setattr(module,'build_document_relations',relations)
    monkeypatch.setattr(module,'prepare_document',prepare)
    chunks,result,issues=prepare_knowledge_base(docs,chunker,text_mode='labeled_case')
    assert visited==['relations']+sorted(d.id for d in docs)
    sources={d.id:d for d in docs}
    assert len(result['nodes'])==12 and sum(c.metadata['kind']=='test_case' for c in chunks)==12
    assert len([e for e in result['edges'] if e['kind']=='filename_pair'])==3
    for chunk in chunks:assert_bound(sources[chunk.source_ref],[chunk])
    for edge in result['edges']:
        if edge['source_span']:
            span=edge['source_span'];text=sources[edge['from_document_id']].text
            assert text[span['start_char']:span['end_char']]==edge['quote']
    assert all('retrieval_view' in c.metadata and 'document_info' in c.metadata for c in chunks)
    assert any(i['category']=='stale_header_line_range' for i in issues)


@pytest.mark.parametrize('stage',['relations','document'])
def test_unexpected_stage_fault_is_safe_no_partial_return(tmp_path,monkeypatch,caplog,stage):
    root=tmp_path/'kb';root.mkdir();(root/'a.md').write_text('# A');(root/'b.md').write_text('# B')
    docs=MarkdownLoader(root,'kb',4096).load_all();calls=[]
    original=module.prepare_document
    def fail_relations(*args):raise RuntimeError('SYNTHETIC_PRIVATE')
    def fail_second(doc,*args,**kwargs):
        calls.append(doc.id)
        if len(calls)==2:raise RuntimeError('SYNTHETIC_PRIVATE')
        return original(doc,*args,**kwargs)
    if stage=='relations':monkeypatch.setattr(module,'build_document_relations',fail_relations)
    else:monkeypatch.setattr(module,'prepare_document',fail_second)
    code='relation_build_failed' if stage=='relations' else 'knowledge_preparation_failed'
    with pytest.raises(RelationError,match=f'^{code}$'):
        prepare_knowledge_base(docs,DocumentChunker(settings(tmp_path)),text_mode='raw')
    assert 'SYNTHETIC_PRIVATE' not in caplog.text
    if stage=='document':assert len(calls)==2


def test_known_document_error_preserves_original_identity(tmp_path,monkeypatch):
    root=tmp_path/'kb';root.mkdir();(root/'a.md').write_text('# A')
    docs=MarkdownLoader(root,'kb',4096).load_all();error=PreparationError('invalid_preparation_input')
    def failure(*args,**kwargs):raise error
    monkeypatch.setattr(module,'prepare_document',failure)
    with pytest.raises(PreparationError) as caught:
        prepare_knowledge_base(docs,DocumentChunker(settings(tmp_path)),text_mode='raw')
    assert caught.value is error


def test_empty_library_and_invalid_mode(tmp_path):
    chunks,relations,issues=prepare_knowledge_base([],DocumentChunker(settings(tmp_path)),text_mode='raw')
    assert chunks==[] and relations['nodes']==[] and issues==[]
    with pytest.raises(PreparationError,match='^invalid_text_mode$'):
        prepare_knowledge_base([],DocumentChunker(settings(tmp_path)),text_mode='guess')
