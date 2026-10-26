"""Formal M1/M2 input to actual jieba statistics; no model or index writes."""
import json
import pytest
from naiyue_rag import MarkdownLoader,DocumentChunker,IngestionSettings,prepare_knowledge_base
from naiyue_rag.encoding import prepare_document_encoding_inputs,plan_encoding_batches
from naiyue_rag.encoding.sparse_encoder import SparseEncoder
from test_encoding_settings import config
from test_sparse_encoding_settings import sparse_config
from test_document_chunker import offline

@pytest.mark.parametrize('mode',['raw','labeled_case'])
def test_m1_m2_to_real_sparse_binds_ids_hashes_and_preserves_originals(tmp_path,mode):
    documents=MarkdownLoader('examples/mock-v1/knowledge','structure-kb',1_048_576).load_all()
    chunks,relations,issues=prepare_knowledge_base(documents,DocumentChunker(IngestionSettings(1000,200)),text_mode=mode)
    cfg=config(representation={'document_text_mode':mode})
    inputs=prepare_document_encoding_inputs(documents,chunks,cfg)
    before=[c.to_dict() for c in chunks]
    enc=SparseEncoder(cfg,sparse_config(tmp_path));records=[]
    for batch in plan_encoding_batches(inputs,cfg):records.extend(enc.encode_batch(batch))
    assert len(records)==len(inputs)==72 and sum(c.metadata['kind']=='test_case' for c in chunks)==12
    assert [r.item_id for r in records]==[i.item_id for i in inputs]
    assert [r.retrieval_text_sha256 for r in records]==[i.retrieval_text_sha256 for i in inputs]
    assert all(r.tokenizer_id==enc.tokenizer_id and r.doc_length==sum(r.term_frequencies.values()) for r in records)
    assert [c.to_dict() for c in chunks]==before
    assert json.loads(json.dumps([r.to_dict() for r in records],ensure_ascii=False))==[r.to_dict() for r in records]
