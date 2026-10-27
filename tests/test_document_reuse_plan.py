"""Document work partitions distinguish semantic encoding from index settings."""
from dataclasses import replace
import pytest
from naiyue_rag import MarkdownLoader,IngestionSettings
from naiyue_rag.storage import ChromaSettings,BM25Settings
from test_storage_bundle import make_bundle,KB
from test_file_integrity import plan
from test_encoding_settings import config


def test_added_updated_retained_and_unchanged_are_partitioned(tmp_path):
    bundle=make_bundle(tmp_path);root=tmp_path/'source'
    (root/'L1_Module.md').write_text('# 修改\n\n新规则。\n')
    (root/'L2_D.md').write_text('# 新增\n\n新增规则。\n')
    loader=MarkdownLoader(root,KB,4096)
    incoming=[loader.load('L1_Module.md'),loader.load('L2_D.md')]
    result=plan(bundle,incoming)
    assert result.encode_document_ids==sorted(d.id for d in incoming)
    assert result.reuse_document_ids==sorted(result.retained_ids)
    assert result.encoding_profile_matches and result.index_profile_matches and not result.reuse_active
    assert set(result.encode_document_ids).isdisjoint(result.reuse_document_ids)
    assert set(result.encode_document_ids+result.reuse_document_ids)=={d.id for d in result.merged_documents}


@pytest.mark.parametrize('change',['k1','collection','runtime','force','size','model','tokenizer'])
def test_identity_matrix_has_explicit_encoding_and_index_decisions(tmp_path,change):
    bundle=make_bundle(tmp_path);kwargs={}
    if change=='k1':kwargs['bm25_settings']=BM25Settings(1.2,.75)
    elif change=='collection':kwargs['chroma_settings']=ChromaSettings('other_collection',2)
    elif change=='runtime':kwargs['encoding_settings']=config(runtime={'batch_size':1})
    elif change=='force':kwargs['force']=True
    elif change=='size':kwargs['ingestion_settings']=IngestionSettings(60,10)
    elif change=='model':kwargs['encoding_settings']=config(embedding={'model_revision':'changed'})
    else:kwargs['tokenizer_id']='b'*64
    result=plan(bundle,bundle.documents,**kwargs);ids=sorted(d.id for d in bundle.documents)
    if change in ('k1','collection','runtime'):
        assert result.encode_document_ids==[] and result.reuse_document_ids==ids
    else:assert result.encode_document_ids==ids and result.reuse_document_ids==[]
    assert result.reuse_active==(change=='runtime')
    assert result.index_profile_matches==(change not in ('k1','collection'))


def test_pipeline_consumes_and_rejects_incomplete_plan_partition(setup_job,monkeypatch):
    import naiyue_rag.ingestion.pipeline as module
    from naiyue_rag.core.errors import IngestionJobError
    job,dense,_=setup_job;job.run(expected_revision=0);before=dense.calls
    original=module.plan_ingestion
    def corrupt(*args,**kwargs):
        return replace(original(*args,**kwargs),reuse_document_ids=[])
    monkeypatch.setattr(module,'plan_ingestion',corrupt)
    with pytest.raises(IngestionJobError,match='ingestion_plan_failed'):job.run(expected_revision=1)
    assert dense.calls==before


from test_ingestion_pipeline import setup_job
