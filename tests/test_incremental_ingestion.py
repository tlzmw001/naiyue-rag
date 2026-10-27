"""Only changed documents encode; complete new versions preserve paired sources."""
from dataclasses import replace
import pytest
from naiyue_rag import IngestionSettings
from naiyue_rag.storage import BM25Settings
from naiyue_rag.storage.bundle_encoding import bundle_encoding
from test_ingestion_pipeline import setup_job,job_for
from test_encoding_settings import config


def pair(record):
    return dict(input=record.input.to_dict(),vector=record.dense_vector,sparse=record.sparse.to_dict())


def test_update_and_add_only_prepare_encode_changed_documents(setup_job,tmp_path,monkeypatch):
    job,_,_=setup_job;first=job.run(expected_revision=0)
    old=job.manager.bundles.load(first.active.version.bundle_id);old_wire=old.to_dict()
    paths={d.metadata['source_path']:d.id for d in old.documents}
    (tmp_path/'source/L1_Module.md').write_text('# 修改模块\n\n新规则threshold=0.7。\n')
    (tmp_path/'source/L2_D.md').write_text('# 新需求D\n\n新规则feature_x=2。\n')
    seen=[];prepared=[];process=job.batch_processor.process;split=job.chunker.split_document
    def counted(inputs):seen.extend(inputs);return process(inputs)
    def scanned(document):prepared.append(document.id);return split(document)
    monkeypatch.setattr(job.batch_processor,'process',counted);monkeypatch.setattr(job.chunker,'split_document',scanned)
    receipt=job.run(expected_revision=1);new=job.manager.bundles.load(receipt.active.version.bundle_id)
    changed={d.id for d in new.documents if d.metadata['source_path'] in ('L1_Module.md','L2_D.md')}
    assert set(prepared)=={i.source_document_id for i in seen}==changed
    assert receipt.encoding_summary.encoded_chunk_count==receipt.encoding_report.input_count==len(seen)
    assert receipt.encoding_summary.reused_chunk_count>0
    assert receipt.encoding_summary.total_chunk_count==len(new.chunks)
    old_records={r.input.item_id:r for r in bundle_encoding(old).records}
    new_records={r.input.item_id:r for r in bundle_encoding(new).records}
    for uid,record in old_records.items():
        if record.input.source_document_id!=paths['L1_Module.md']:assert pair(new_records[uid])==pair(record)
        else:assert uid not in new_records
    assert job.manager.bundles.load(first.active.version.bundle_id).to_dict()==old_wire
    assert receipt.encoding_report.to_dict()==new.encoding_summary.job_report.to_dict()
    assert {o['source_bundle_id'] for o in new.encoding_snapshot.origins if o['kind']=='reused'}=={first.active.version.bundle_id}


def test_index_only_change_reuses_all_encoding_and_has_no_current_job(setup_job,tmp_path,monkeypatch):
    job,*_=setup_job;first=job.run(expected_revision=0)
    changed,dense,_=job_for(tmp_path,bm25=BM25Settings(1.2,.5))
    monkeypatch.setattr(changed.batch_processor,'process',lambda *a:pytest.fail('index-only changes must not encode'))
    receipt=changed.run(expected_revision=1)
    assert receipt.active.revision==2 and receipt.active.version.bm25_k1==1.2
    assert receipt.encoding_report is None and dense.calls==0
    assert receipt.encoding_summary.encoded_chunk_count==0
    assert receipt.encoding_summary.reused_chunk_count==first.active.version.chunk_count


@pytest.mark.parametrize('change',['model','policy','force'])
def test_semantic_profile_change_and_force_encode_whole_documents(setup_job,tmp_path,change):
    job,*_=setup_job;job.run(expected_revision=0);kwargs={}
    if change=='model':kwargs['cfg']=config(embedding={'model_revision':'new'})
    elif change=='policy':kwargs['ingestion']=IngestionSettings(40,10,chunking_policy='markdown-source-v1')
    updated,dense,_=job_for(tmp_path,**kwargs)
    receipt=updated.run(expected_revision=1,force=change=='force')
    assert receipt.encoding_summary.reused_chunk_count==0 and dense.calls>0
    assert receipt.encoding_report.input_count==receipt.active.version.chunk_count


def test_adding_blank_source_creates_new_version_without_encoding(setup_job,tmp_path,monkeypatch):
    job,*_=setup_job;first=job.run(expected_revision=0)
    (tmp_path/'source/blank.md').write_text('')
    monkeypatch.setattr(job.batch_processor,'process',lambda *a:pytest.fail('blank addition has no encoding inputs'))
    receipt=job.run(expected_revision=1)
    assert receipt.added_document_count==1 and receipt.active.version.document_count==first.active.version.document_count+1
    assert receipt.encoding_report is None and receipt.encoding_summary.encoded_chunk_count==0
    assert receipt.encoding_summary.reused_chunk_count==first.active.version.chunk_count


def test_current_job_limits_count_only_changed_input_while_snapshot_stays_complete(setup_job,tmp_path):
    job,*_=setup_job;first=job.run(expected_revision=0)
    (tmp_path/'source/L1_Module.md').write_text('一条新的规则。')
    changed,dense,_=job_for(tmp_path,cfg=config(runtime={'max_inputs':1,'max_requests':1}))
    receipt=changed.run(expected_revision=1)
    assert dense.calls==1 and receipt.encoding_report.input_count==1
    assert receipt.encoding_summary.reused_chunk_count>0
    assert receipt.active.version.chunk_count>1 and receipt.active.revision==first.active.revision+1


@pytest.mark.parametrize('action',['repeat','missing-removal'])
def test_zero_encoding_paths_preserve_limited_incremental_snapshot(setup_job,tmp_path,monkeypatch,action):
    job,*_=setup_job;job.run(expected_revision=0)
    (tmp_path/'source/L1_Module.md').write_text('一条新的规则。')
    limited,dense,_=job_for(tmp_path,cfg=config(runtime={'max_inputs':1,'max_requests':1}))
    updated=limited.run(expected_revision=1)
    assert updated.encoding_summary.encoded_chunk_count==1 and updated.active.version.chunk_count>1
    calls=dense.calls
    def deny(*args,**kwargs):pytest.fail('zero-encoding paths must not encode or publish artifacts')
    monkeypatch.setattr(limited.batch_processor,'process',deny)
    monkeypatch.setattr(limited.manager.bundles,'save',deny)
    if action=='repeat':
        receipt=limited.run(expected_revision=updated.active.revision)
        assert receipt.status=='unchanged' and receipt.encoding_report is None
        assert receipt.encoding_summary.encoded_chunk_count==0
        assert receipt.encoding_summary.reused_chunk_count==updated.active.version.chunk_count
    else:
        receipt=limited.remove_document('doc-'+'0'*64,expected_revision=updated.active.revision)
        assert receipt.status=='not_found' and receipt.previous_active==updated.active
        assert receipt.encoding_report is None and receipt.encoding_summary is None
    assert receipt.active==updated.active==limited.manager.open_active() and dense.calls==calls
