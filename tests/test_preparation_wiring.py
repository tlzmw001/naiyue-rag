"""Actual config -> loader -> chunker -> rule stages, with explicit failures."""
from pathlib import Path

import pytest

from naiyue_rag import MarkdownLoader, DocumentChunker, prepare_document
from naiyue_rag.core.errors import PreparationError
from naiyue_rag.ingestion.chunk_preparation import ChunkRefiner, MetadataEnricher
from test_document_chunker import settings, assert_bound, offline


def test_existing_mock_both_views_preserve_twelve_cases_and_source_spans(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1]/'examples/mock-v1/knowledge'
    docs=MarkdownLoader(root,'structure-kb',1_048_576).load_all()
    chunker=DocumentChunker(settings(tmp_path,1000,200));calls=[]
    refiner=ChunkRefiner.transform;enricher=MetadataEnricher.transform
    def refine(self,*args,**kwargs):calls.append('refiner');return refiner(self,*args,**kwargs)
    def enrich(self,*args,**kwargs):calls.append('enricher');return enricher(self,*args,**kwargs)
    monkeypatch.setattr(ChunkRefiner,'transform',refine)
    monkeypatch.setattr(MetadataEnricher,'transform',enrich)
    totals={}
    for mode in ['raw','labeled_case']:
        total=0
        for doc in docs:
            output,issues=prepare_document(doc,chunker,text_mode=mode)
            original,expected=chunker.split_document(doc)
            assert issues==expected and [c.id for c in output]==[c.id for c in original]
            assert_bound(doc,output)
            total+=sum(c.metadata['kind']=='test_case' for c in output)
            assert all('retrieval_view' in c.metadata and 'document_info' in c.metadata for c in output)
        totals[mode]=total
    assert totals=={'raw':12,'labeled_case':12}
    assert calls==['refiner','enricher']*len(docs)*2


@pytest.mark.parametrize('stage,code',[
    ('split_document','preparation_chunking_failed'),
    ('refiner','refinement_failed'),('enricher','enrichment_failed'),
])
def test_stage_failures_return_no_partial_result_and_safe_error(tmp_path,monkeypatch,caplog,stage,code):
    root=tmp_path/'kb';root.mkdir();(root/'L1_A.md').write_text('# L1 A\n正文')
    doc=MarkdownLoader(root,'kb',4096).load('L1_A.md')
    chunker=DocumentChunker(settings(tmp_path));visited=[]
    def failure(*args,**kwargs):visited.append(stage);raise RuntimeError('SYNTHETIC_PRIVATE_ERROR')
    if stage=='split_document':monkeypatch.setattr(chunker,'split_document',failure)
    elif stage=='refiner':monkeypatch.setattr(ChunkRefiner,'transform',failure)
    else:monkeypatch.setattr(MetadataEnricher,'transform',failure)
    with pytest.raises(PreparationError,match=f'^{code}$'):
        prepare_document(doc,chunker,text_mode='raw')
    assert visited==[stage] and 'SYNTHETIC_PRIVATE' not in caplog.text
    assert f'code={code}' in caplog.text


def test_empty_source_is_successful_terminal_state(tmp_path):
    root=tmp_path/'kb';root.mkdir();(root/'empty.md').write_text('')
    doc=MarkdownLoader(root,'kb',4096).load('empty.md')
    result,issues=prepare_document(doc,DocumentChunker(settings(tmp_path)),text_mode='raw')
    assert result==[] and issues==[{'category':'empty_source','severity':'info','document_id':doc.id}]
