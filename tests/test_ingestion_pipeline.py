"""Formal whole-library ingestion: source snapshots, request use and commit boundaries."""
from dataclasses import replace
import json
from pathlib import Path
import pytest
from naiyue_rag import IngestionPipeline,IngestionReceipt,BatchProcessor,IngestionSettings
from naiyue_rag.core.errors import IngestionJobError,StorageError,EmbeddingExecutionError
from naiyue_rag.encoding.execution_report import new_report
from naiyue_rag.storage import BundleStore,ChromaSettings,BM25Settings,VectorUpserter,BM25Indexer
from test_storage_bundle import ingredients,storage_settings,Dense,PRIVATE
from test_batch_processor import Sparse
from test_chroma_index import FakeClient
from test_encoding_settings import config


def job_for(root,*,cfg=None,ingestion=None,storage=None,chroma=None,bm25=None):
    cfg=cfg or config();dense=Dense(cfg);sparse=Sparse(cfg)
    job=IngestionPipeline(storage or storage_settings(root),ingestion or IngestionSettings(40,10),
        BatchProcessor(cfg,dense,sparse),chroma or ChromaSettings('knowledge_hub',2),
        bm25 or BM25Settings(1.5,.75),knowledge_base_root=root/'source',project_root=root)
    return job,dense,sparse


@pytest.fixture
def setup_job(tmp_path,monkeypatch):
    ingredients(tmp_path);events=[];fault={}
    import naiyue_rag.storage.chroma_backend as backend
    monkeypatch.setattr(backend,'new_client',lambda path,root:FakeClient(path,events,fault))
    job,dense,sparse=job_for(tmp_path)
    return job,dense,sparse


def test_first_ingestion_and_repeat_skip_encoding_and_builds(setup_job,monkeypatch):
    job,dense,sparse=setup_job;first=job.run(expected_revision=0)
    assert isinstance(first,IngestionReceipt) and first.status=='activated' and first.added_document_count==3
    assert first.active==job.manager.open_active() and first.encoding_report.paired_input_count>0
    assert dense.calls==first.encoding_report.requests['attempted_requests']
    before=dense.calls;audits=[];audit=job.manager._audit
    def checked(*args):audits.append(args[0]);return audit(*args)
    monkeypatch.setattr(job.manager,'_audit',checked)
    def forbidden(*args,**kwargs):pytest.fail('repeat must not encode or build')
    monkeypatch.setattr(job.batch_processor,'process',forbidden)
    monkeypatch.setattr(job.manager.bundles,'save',forbidden)
    monkeypatch.setattr(VectorUpserter,'build',forbidden);monkeypatch.setattr(BM25Indexer,'build',forbidden)
    again=job.run(expected_revision=1)
    assert again.status=='unchanged' and again.active==first.active and again.encoding_report is None
    assert again.unchanged_document_count==3 and dense.calls==before and audits==[first.active.version.bundle_id]


def test_update_merges_history_and_replaces_current_l1(setup_job,tmp_path):
    job,dense,_=setup_job;first=job.run(expected_revision=0);old=job.manager.list_documents()
    source=tmp_path/'source';(source/'L1_Module.md').write_text('# 模块v2\n\n[历史](L2_A.md)\n\n新规则。\n')
    (source/'L2_A.md').rename(tmp_path/'old-A.md');(source/'L2_A_测试用例.md').rename(tmp_path/'old-cases.md')
    (source/'L2_B.md').write_text('# 新需求B\n\n[模块](L1_Module.md)\n')
    (source/'L2_B_测试用例.md').write_text((tmp_path/'old-cases.md').read_text().replace('A测试用例','B测试用例'))
    before=dense.calls;second=job.run(expected_revision=1)
    assert second.active.revision==2 and second.added_document_count==2 and second.updated_document_count==1
    assert second.retained_document_count==2 and second.unchanged_document_count==0
    assert dense.calls-before==second.encoding_report.requests['attempted_requests']
    current=job.manager.list_documents();assert len(current.documents)==5
    old_l1=next(d for d in old.documents if d.source_path=='L1_Module.md')
    new_l1=next(d for d in current.documents if d.document_id==old_l1.document_id)
    assert new_l1.source_sha256!=old_l1.source_sha256
    bundle=job.manager.bundles.load(second.active.version.bundle_id)
    assert second.encoding_report.paired_input_count==second.encoding_summary.encoded_chunk_count<len(bundle.chunks)
    assert second.encoding_summary.encoded_chunk_count+second.encoding_summary.reused_chunk_count==len(bundle.chunks)
    assert len(job.manager.bundles.load(first.active.version.bundle_id).documents)==3
    assert all(c.metadata['source_sha256']==new_l1.source_sha256 for c in bundle.chunks if c.source_ref==new_l1.document_id)
    assert bundle.relations['edges']


@pytest.mark.parametrize('mode',['empty','blank'])
def test_valid_zero_chunk_ingestion(tmp_path,monkeypatch,mode):
    source=tmp_path/'source';source.mkdir()
    if mode=='blank':(source/'blank.md').write_text('')
    import naiyue_rag.storage.chroma_backend as backend
    monkeypatch.setattr(backend,'new_client',lambda path,root:FakeClient(path,[],{}))
    job,dense,_=job_for(tmp_path);receipt=job.run(expected_revision=0)
    assert receipt.encoding_report is None and dense.calls==0
    assert receipt.encoding_summary.total_chunk_count==receipt.encoding_summary.encoded_chunk_count==0
    assert receipt.active.version.document_count==(mode=='blank') and receipt.active.version.chunk_count==0
    assert job.run(expected_revision=1).encoding_report is None


def test_empty_input_retains_saved_sources(setup_job,tmp_path):
    job,dense,_=setup_job;first=job.run(expected_revision=0)
    for p in (tmp_path/'source').iterdir():p.rename(tmp_path/p.name)
    again=job.run(expected_revision=1)
    assert again.active==first.active and again.retained_document_count==3 and again.unchanged_document_count==0


@pytest.mark.parametrize('revision,force',[(True,False),(-1,False),(2**63,False),(0,1),(0,None)])
def test_invalid_request_fails_before_scan_or_catalog(setup_job,monkeypatch,revision,force):
    job,*_=setup_job
    def forbidden(*args,**kwargs):pytest.fail('invalid request must fail before IO')
    monkeypatch.setattr(job.loader,'load_all',forbidden);monkeypatch.setattr(job.manager.catalog,'read',forbidden)
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=revision,force=force)
    assert caught.value.stage=='validate' and caught.value.code=='ingestion_invalid_request'


def test_known_stale_revision_rejects_before_source_scan(setup_job,monkeypatch):
    job,*_=setup_job;job.run(expected_revision=0)
    monkeypatch.setattr(job.loader,'load_all',lambda:pytest.fail('stale request must not scan'))
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=0)
    assert caught.value.code=='catalog_revision_conflict' and caught.value.activation_status=='not_attempted'


@pytest.mark.parametrize('fault',['load','plan','prepare','encode','bundle','vector','bm25'])
def test_failure_stops_pipeline_and_retains_real_observations(setup_job,tmp_path,monkeypatch,fault,caplog):
    import naiyue_rag.ingestion.pipeline as module
    job,*_=setup_job;first=job.run(expected_revision=0)
    (tmp_path/'source/L1_Module.md').write_text('# 改动\n\n新内容。\n')
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    targets={'load':(job.loader,'load_all'),'plan':(module,'plan_ingestion'),
        'prepare':(module,'prepare_knowledge_base'),'encode':(job.batch_processor,'process'),
        'bundle':(job.manager.bundles,'save'),'vector':(module.VectorUpserter,'build'),
        'bm25':(module.BM25Indexer,'build')}
    monkeypatch.setattr(*targets[fault],fail)
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=1)
    error=caught.value;assert error.stage==fault and error.activation_status=='not_attempted'
    assert error.code==f'ingestion_{fault}_failed'
    assert (error.encoding_report is not None)==(fault in ('bundle','vector','bm25'))
    if error.encoding_report is not None:assert error.encoding_report.status=='success'
    assert (error.candidate_bundle_id is not None)==(fault in ('vector','bm25'))
    assert job.manager.catalog.read()==first.active and PRIVATE not in str(error)+repr(error)+caplog.text


def test_dense_failure_report_survives_whole_job_error(setup_job,monkeypatch):
    job,dense,_=setup_job
    def fail(*args,**kwargs):
        report=new_report();report.update(attempted_requests=1,error_code='embedding_connection_failed')
        raise EmbeddingExecutionError('embedding_connection_failed',report)
    monkeypatch.setattr(dense,'encode_batch',fail)
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=0)
    error=caught.value
    assert error.stage=='encode' and error.code=='embedding_connection_failed'
    assert error.encoding_report.status=='failed' and error.encoding_report.requests['attempted_requests']==1
    assert job.manager.catalog.read() is None


@pytest.mark.parametrize('force',[False,True])
def test_broken_old_index_cannot_be_bypassed(setup_job,tmp_path,force):
    job,dense,_=setup_job;first=job.run(expected_revision=0);before=dense.calls
    marker=job.manager.catalog.path.parent/'vectors'/first.active.version.vector_index_id/'ready.json'
    marker.write_text('{}')
    if force:(tmp_path/'source/L1_Module.md').write_text('# 新版本\n\n新内容。\n')
    with pytest.raises(IngestionJobError):job.run(expected_revision=1,force=force)
    assert dense.calls==before and job.manager.catalog.read()==first.active


def test_successful_encoding_is_retained_on_real_revision_race(setup_job,tmp_path,monkeypatch):
    job,*_=setup_job;job.run(expected_revision=0)
    (tmp_path/'source/L2_B.md').write_text('# B\n\n新增内容。\n')
    rival,_,_=job_for(tmp_path,bm25=BM25Settings(1.2,.5));process=job.batch_processor.process;won=[]
    def encode_then_compete(inputs):
        result=process(inputs);won.append(rival.run(expected_revision=1));return result
    monkeypatch.setattr(job.batch_processor,'process',encode_then_compete)
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=1)
    error=caught.value
    assert error.stage=='activate' and error.code=='catalog_revision_conflict'
    assert error.activation_status=='not_committed' and error.encoding_report.status=='success'
    assert error.candidate_bundle_id and job.manager.catalog.read()==won[0].active


def test_commit_uncertain_is_not_claimed_as_rollback(setup_job,monkeypatch):
    job,*_=setup_job;commit=job.manager.catalog._commit
    def uncertain(conn):commit(conn);raise OSError(PRIVATE)
    # Skip catalog initialization commit; fail the activation commit only.
    calls=[]
    def second_commit(conn):
        calls.append(1)
        return uncertain(conn) if len(calls)==2 else commit(conn)
    monkeypatch.setattr(job.manager.catalog,'_commit',second_commit)
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=0)
    error=caught.value
    assert error.code=='catalog_commit_uncertain' and error.activation_status=='unknown'
    assert error.encoding_report.status=='success' and error.candidate_bundle_id
    assert job.manager.catalog.read().revision==1


@pytest.mark.parametrize('limit',['documents','chunks','inputs'])
def test_pre_encoding_limits_use_current_configuration(setup_job,tmp_path,limit):
    job,dense,_=setup_job
    if limit=='documents':job,dense,_=job_for(tmp_path,storage=storage_settings(tmp_path,max_documents=1))
    elif limit=='chunks':job,dense,_=job_for(tmp_path,storage=storage_settings(tmp_path,max_chunks=1))
    else:job,dense,_=job_for(tmp_path,cfg=config(runtime={'max_inputs':1}))
    with pytest.raises(IngestionJobError):job.run(expected_revision=0)
    assert dense.calls==0 and job.manager.catalog.read() is None


@pytest.mark.parametrize('action',['repeat','missing-removal'])
@pytest.mark.parametrize('limit',['max_input_utf8_bytes','max_batch_input_utf8_bytes'])
def test_reuse_still_applies_new_per_item_byte_limits(setup_job,tmp_path,action,limit):
    job,*_=setup_job;first=job.run(expected_revision=0)
    limited,dense,_=job_for(tmp_path,cfg=config(runtime={limit:1}))
    with pytest.raises(IngestionJobError) as caught:
        if action=='repeat':limited.run(expected_revision=1)
        else:limited.remove_document('doc-'+'0'*64,expected_revision=1)
    assert caught.value.stage=='prepare' and caught.value.code=='ingestion_prepare_failed'
    assert dense.calls==0 and limited.manager.catalog.read()==first.active


def test_force_rebuild_and_execution_only_change_reuse(setup_job,tmp_path):
    job,dense,_=setup_job;first=job.run(expected_revision=0);before=dense.calls
    forced=job.run(expected_revision=1,force=True)
    assert forced.encoding_report is not None and dense.calls>before and forced.unchanged_document_count==3
    changed,dense,_=job_for(tmp_path,cfg=config(runtime={'batch_size':1}),chroma=ChromaSettings('knowledge_hub',1))
    result=changed.run(expected_revision=forced.active.revision)
    assert result.encoding_report is None and dense.calls==0


def test_read_error_is_not_retention_and_configuration_cannot_change_in_place(setup_job,tmp_path):
    job,dense,_=setup_job;first=job.run(expected_revision=0)
    (tmp_path/'source/L1_Module.md').write_bytes(b'\xff')
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=1)
    assert caught.value.stage=='load' and job.manager.catalog.read()==first.active
    job.batch_processor.settings=config(runtime={'batch_size':1})
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=1)
    assert caught.value.stage=='validate'


@pytest.mark.parametrize('change',['chunk-size','model-revision','collection','bm25'])
def test_profile_change_executes_full_pipeline_with_pinned_old_audit(setup_job,tmp_path,change):
    job,*_=setup_job;first=job.run(expected_revision=0);args={}
    if change=='chunk-size':args['ingestion']=IngestionSettings(60,10)
    elif change=='model-revision':args['cfg']=config(embedding={'model_revision':'v2'})
    elif change=='collection':args['chroma']=ChromaSettings('changed_collection',2)
    else:args['bm25']=BM25Settings(1.2,.5)
    changed,dense,_=job_for(tmp_path,**args);result=changed.run(expected_revision=1)
    assert result.active.revision==2
    if change in ('collection','bm25'):
        assert result.encoding_report is None and dense.calls==0 and result.encoding_summary.encoded_chunk_count==0
    else:assert result.encoding_report is not None and dense.calls>0 and result.encoding_summary.reused_chunk_count==0
    assert result.unchanged_document_count==3 and result.updated_document_count==0
    assert result.active.version.bundle_id!=first.active.version.bundle_id


def test_post_encoding_storage_limit_keeps_the_encoding_report(setup_job,tmp_path):
    job,dense,_=job_for(tmp_path,storage=storage_settings(tmp_path,max_file_bytes=1000))
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=0)
    assert caught.value.stage=='bundle' and caught.value.code=='bundle_limit_exceeded'
    assert dense.calls>0 and caught.value.encoding_report.status=='success'
    assert caught.value.candidate_bundle_id is None and job.manager.catalog.read() is None


def test_broken_bundle_fails_before_encoding_even_with_force(setup_job):
    job,dense,_=setup_job;first=job.run(expected_revision=0);before=dense.calls
    (job.manager.catalog.path.parent/'artifacts'/first.active.version.bundle_id/'chunks.json').write_text('[]')
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=1,force=True)
    assert caught.value.stage=='select' and dense.calls==before
    assert caught.value.encoding_report is None


@pytest.mark.parametrize('when',['before','after'])
def test_unexpected_activation_failure_is_unknown(setup_job,monkeypatch,when):
    job,*_=setup_job;activate=job.manager.activate
    def fail(*args,**kwargs):
        if when=='after':activate(*args,**kwargs)
        raise OSError(PRIVATE)
    monkeypatch.setattr(job.manager,'activate',fail)
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=0)
    error=caught.value
    assert error.stage=='activate' and error.activation_status=='unknown'
    assert error.encoding_report.status=='success' and error.candidate_bundle_id
    assert (job.manager.catalog.read() is not None)==(when=='after')


def test_finalize_failure_reports_known_activation(setup_job,monkeypatch):
    import naiyue_rag.ingestion.pipeline as module
    job,*_=setup_job
    def fail(*args):raise OSError(PRIVATE)
    monkeypatch.setattr(module,'IngestionReceipt',fail)
    with pytest.raises(IngestionJobError) as caught:job.run(expected_revision=0)
    error=caught.value
    assert error.stage=='finalize' and error.activation_status=='activated'
    assert error.encoding_report.status=='success' and job.manager.catalog.read().revision==1


def test_control_interrupt_is_not_converted_to_normal_job_error(setup_job,monkeypatch):
    job,*_=setup_job
    def stop():raise KeyboardInterrupt()
    monkeypatch.setattr(job.loader,'load_all',stop)
    with pytest.raises(KeyboardInterrupt):job.run(expected_revision=0)
    assert job.manager.catalog.read() is None
