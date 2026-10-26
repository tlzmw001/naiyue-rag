"""Explicit snapshot removal; old artifacts and original sources remain available."""
import json
from pathlib import Path
import pytest
from naiyue_rag import IngestionSettings
from naiyue_rag.core.errors import IngestionJobError,StorageError,EmbeddingExecutionError
from naiyue_rag.encoding.execution_report import new_report
from naiyue_rag.storage import ChromaSettings,BM25Settings,ChromaStore,BM25Store
from test_ingestion_pipeline import setup_job,job_for
from test_storage_bundle import storage_settings,PRIVATE
from test_encoding_settings import config

MISSING='doc-'+'0'*64


def target(job,path='L2_A.md'):
    return next(d for d in job.manager.list_documents().documents if d.source_path==path)


@pytest.mark.parametrize('path',['L1_Module.md','L2_A.md','L2_A_测试用例.md'])
def test_remove_one_document_preserves_sources_and_old_indexes(setup_job,tmp_path,path):
    job,dense,_=setup_job;first=job.run(expected_revision=0);info=target(job,path)
    original={p.name:p.read_bytes() for p in (tmp_path/'source').iterdir()}
    old=job.manager.bundles.load(first.active.version.bundle_id);before=dense.calls
    receipt=job.remove_document(info.document_id,expected_revision=1)
    assert receipt.status=='removed' and receipt.previous_active==first.active and receipt.removed_document==info
    assert receipt.active.revision==2 and receipt.active.version.document_count==2
    assert receipt.active==job.manager.open_active() and receipt.encoding_report.status=='success'
    assert dense.calls-before==receipt.encoding_report.requests['attempted_requests']
    current=job.manager.bundles.load(receipt.active.version.bundle_id)
    assert {d.id:d.to_dict() for d in current.documents}=={d.id:d.to_dict() for d in old.documents if d.id!=info.document_id}
    assert all(c.source_ref!=info.document_id for c in current.chunks)
    assert all(n['document_id']!=info.document_id for n in current.relations['nodes'])
    assert all(info.document_id not in (e['from_document_id'],e['to_document_id']) for e in current.relations['edges'])
    if path=='L2_A.md':
        assert {'missing_pair','target_not_loaded'}<={d['category'] for d in current.relations['diagnostics']}
        assert any(c.metadata.get('case_id')=='TC-01' for c in current.chunks)
    assert job.manager.get_document_detail(info.document_id,expected_revision=2).document is None
    assert {p.name:p.read_bytes() for p in (tmp_path/'source').iterdir()}==original
    assert job.manager.bundles.load(first.active.version.bundle_id).to_dict()==old.to_dict()
    assert job.manager._audit(first.active.version.bundle_id,job.chroma_settings,job.bm25_settings)==first.active.version
    reader=ChromaStore(job.settings,job.chroma_settings,project_root=tmp_path)
    seen={}
    for start in range(0,len(old.chunks),2):
        seen.update(reader.get_by_ids(first.active.version.bundle_id,[c.id for c in old.chunks[start:start+2]]))
    assert set(seen)=={c.id for c in old.chunks}
    sparse=BM25Store(job.settings,job.bm25_settings)
    assert sparse.audit(receipt.active.version.bundle_id).verified_count==len(current.chunks)


def test_removed_source_is_added_by_next_explicit_ingestion(setup_job):
    job,*_=setup_job;job.run(expected_revision=0);info=target(job)
    removed=job.remove_document(info.document_id,expected_revision=1)
    assert removed.active.version.document_count==2
    again=job.run(expected_revision=2)
    assert again.added_document_count==1 and again.unchanged_document_count==2 and again.active.revision==3
    assert job.manager.get_document_detail(info.document_id,expected_revision=3).document==info


def test_removal_never_loads_live_sources(setup_job,tmp_path,monkeypatch):
    job,*_=setup_job;job.run(expected_revision=0);info=target(job)
    for p in (tmp_path/'source').iterdir():p.rename(tmp_path/p.name)
    (tmp_path/'source/broken.md').write_bytes(b'\xff')
    monkeypatch.setattr(job.loader,'load_all',lambda:pytest.fail('remove must not scan sources'))
    original=Path.open
    def guarded(path,*args,**kwargs):
        assert path.parent!=tmp_path/'source','remove must not open source Markdown'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',guarded)
    assert job.remove_document(info.document_id,expected_revision=1).status=='removed'


@pytest.mark.parametrize('active',[False,True])
def test_missing_is_noop_without_encoding_or_new_artifacts(setup_job,tmp_path,monkeypatch,active):
    job,dense,_=setup_job;previous=job.run(expected_revision=0).active if active else None
    before=dense.calls;seen=[];activate=job.manager.activate
    def checked(*args,**kwargs):seen.append(1);return activate(*args,**kwargs)
    monkeypatch.setattr(job.manager,'activate',checked)
    def forbidden(*args,**kwargs):pytest.fail('missing must not encode or build')
    import naiyue_rag.ingestion.pipeline as module
    for obj,name in [(job.batch_processor,'process'),(job.manager.bundles,'save'),
                     (module.VectorUpserter,'build'),(module.BM25Indexer,'build'),(job.loader,'load_all')]:
        monkeypatch.setattr(obj,name,forbidden)
    receipt=job.remove_document(MISSING,expected_revision=int(active))
    assert receipt.status=='not_found' and receipt.active==receipt.previous_active==previous
    assert receipt.removed_document is None and receipt.encoding_report is None and dense.calls==before
    assert seen==([1] if active else [])
    if not active:assert not Path(job.settings.storage_root).exists()


@pytest.mark.parametrize('uid,revision',[('../A',0),('doc-A',0),('doc-'+'A'*64,0),(None,0),(1,0),
    (MISSING,True),(MISSING,-1),(MISSING,2**63),(MISSING,None)])
def test_invalid_removal_rejects_before_io(setup_job,monkeypatch,uid,revision):
    job,*_=setup_job
    monkeypatch.setattr(job.manager.catalog,'read',lambda:pytest.fail('invalid request must not read catalog'))
    with pytest.raises(IngestionJobError) as caught:job.remove_document(uid,expected_revision=revision)
    assert caught.value.stage=='validate' and caught.value.code=='ingestion_invalid_request'


def test_repeat_removal_and_stale_revision(setup_job):
    job,*_=setup_job;job.run(expected_revision=0);uid=target(job).document_id
    removed=job.remove_document(uid,expected_revision=1)
    assert job.remove_document(uid,expected_revision=2).active==removed.active
    with pytest.raises(IngestionJobError) as caught:job.remove_document(uid,expected_revision=1)
    assert caught.value.stage=='select' and caught.value.code=='catalog_revision_conflict'


@pytest.mark.parametrize('path',['last.md','blank.md'])
def test_last_document_becomes_active_empty_library(setup_job,tmp_path,path):
    job,*_=setup_job
    for p in (tmp_path/'source').iterdir():p.rename(tmp_path/p.name)
    (tmp_path/'source'/path).write_text('' if path=='blank.md' else '# 最后\n\n说明。\n')
    first=job.run(expected_revision=0);uid=target(job,path).document_id
    receipt=job.remove_document(uid,expected_revision=1)
    assert receipt.status=='removed' and receipt.active.revision==2 and receipt.previous_active==first.active
    assert receipt.active.version.document_count==receipt.active.version.chunk_count==0
    assert receipt.encoding_report.status=='empty' and receipt.encoding_report.requests['attempted_requests']==0
    assert job.manager.open_active()==receipt.active and job.manager.list_documents().documents==[]


def test_same_bytes_different_path_and_other_kb_id(setup_job,tmp_path):
    from naiyue_rag.core.encoding_settings import digest
    job,*_=setup_job
    (tmp_path/'source/copy.md').write_bytes((tmp_path/'source/L2_A.md').read_bytes())
    job.run(expected_revision=0);info=target(job);copy=target(job,'copy.md')
    assert copy.source_sha256==info.source_sha256 and copy.document_id!=info.document_id
    other='doc-'+digest(['other-kb',info.source_path])
    assert job.remove_document(other,expected_revision=1).status=='not_found'
    job.remove_document(info.document_id,expected_revision=1)
    assert job.manager.get_document_detail(copy.document_id,expected_revision=2).document==copy


@pytest.mark.parametrize('profile',['size','overlap','model','representation','tokenizer','collection','k1','b'])
def test_removal_does_not_migrate_profile(setup_job,tmp_path,profile):
    job,*_=setup_job;first=job.run(expected_revision=0);uid=target(job).document_id;args={}
    if profile=='size':args['ingestion']=IngestionSettings(50,10)
    elif profile=='overlap':args['ingestion']=IngestionSettings(40,5)
    elif profile=='model':args['cfg']=config(embedding={'model_revision':'new'})
    elif profile=='representation':args['cfg']=config(representation={'query_prefix':'changed: '})
    elif profile=='collection':args['chroma']=ChromaSettings('another_collection',2)
    elif profile=='k1':args['bm25']=BM25Settings(1.2,.75)
    elif profile=='b':args['bm25']=BM25Settings(1.5,.5)
    candidate,dense,sparse=job_for(tmp_path,**args)
    if profile=='tokenizer':candidate.tokenizer_id=sparse.tokenizer_id=candidate.batch_processor.tokenizer_id='b'*64
    with pytest.raises(IngestionJobError) as caught:candidate.remove_document(uid,expected_revision=1)
    assert caught.value.stage=='plan' and caught.value.code=='ingestion_profile_mismatch'
    assert dense.calls==0 and candidate.manager.catalog.read()==first.active


def test_runtime_batch_change_is_not_profile_migration(setup_job,tmp_path):
    job,*_=setup_job;job.run(expected_revision=0);uid=target(job).document_id
    changed,_,_=job_for(tmp_path,cfg=config(runtime={'batch_size':1}),chroma=ChromaSettings('knowledge_hub',1))
    assert changed.remove_document(uid,expected_revision=1).status=='removed'


@pytest.mark.parametrize('limit',['documents','chunks','inputs'])
def test_current_limits_apply_to_retained_set(setup_job,tmp_path,limit):
    job,*_=setup_job;first=job.run(expected_revision=0);uid=target(job).document_id;args={}
    if limit=='documents':args['storage']=storage_settings(tmp_path,max_documents=2)
    elif limit=='chunks':args['storage']=storage_settings(tmp_path,max_chunks=1)
    else:args['cfg']=config(runtime={'max_inputs':1})
    limited,dense,_=job_for(tmp_path,**args)
    with pytest.raises(IngestionJobError):limited.remove_document(uid,expected_revision=1)
    assert dense.calls==0 and job.manager.catalog.read()==first.active


@pytest.mark.parametrize('backend',['chroma','bm25'])
@pytest.mark.parametrize('found',[True,False])
def test_broken_old_index_is_never_hidden(setup_job,backend,found):
    job,dense,_=setup_job;first=job.run(expected_revision=0);uid=target(job).document_id if found else MISSING
    namespace,ident=('vectors',first.active.version.vector_index_id) if backend=='chroma' else ('bm25',first.active.version.bm25_index_id)
    (job.manager.catalog.path.parent/namespace/ident/'ready.json').write_text('{}')
    before=dense.calls
    with pytest.raises(IngestionJobError):job.remove_document(uid,expected_revision=1)
    assert job.manager.catalog.read()==first.active and dense.calls==before


@pytest.mark.parametrize('stage',['select','plan','prepare','encode','bundle','vector','bm25'])
def test_failure_retains_exact_observations_and_old_active(setup_job,monkeypatch,caplog,stage):
    import naiyue_rag.ingestion.pipeline as module
    job,*_=setup_job;first=job.run(expected_revision=0);uid=target(job).document_id
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    objects={'select':(job.manager,'_document_bundle'),'plan':(module,'project_detail'),
        'prepare':(module,'prepare_knowledge_base'),'encode':(job.batch_processor,'process'),
        'bundle':(job.manager.bundles,'save'),'vector':(module.VectorUpserter,'build'),'bm25':(module.BM25Indexer,'build')}
    monkeypatch.setattr(*objects[stage],fail)
    with pytest.raises(IngestionJobError) as caught:job.remove_document(uid,expected_revision=1)
    error=caught.value
    assert error.stage==stage and error.code==f'ingestion_{stage}_failed' and error.activation_status=='not_attempted'
    assert (error.encoding_report is not None)==(stage in ('bundle','vector','bm25'))
    assert (error.candidate_bundle_id is not None)==(stage in ('vector','bm25'))
    assert job.manager.catalog.read()==first.active and PRIVATE not in caplog.text+str(error)+repr(error)
    assert IngestionJobError.from_dict(json.loads(json.dumps(error.to_dict()))).to_dict()==error.to_dict()


def test_dense_failed_report_is_not_lost_in_shared_builder(setup_job,monkeypatch):
    job,dense,_=setup_job;first=job.run(expected_revision=0);uid=target(job).document_id
    def fail(*args,**kwargs):
        report=new_report();report.update(attempted_requests=1,error_code='embedding_connection_failed')
        raise EmbeddingExecutionError('embedding_connection_failed',report)
    monkeypatch.setattr(dense,'encode_batch',fail)
    with pytest.raises(IngestionJobError) as caught:job.remove_document(uid,expected_revision=1)
    error=caught.value
    assert error.stage=='encode' and error.code=='embedding_connection_failed' and error.encoding_report.status=='failed'
    assert error.encoding_report.requests['attempted_requests']==1 and job.manager.catalog.read()==first.active


def test_revision_race_keeps_winner_and_current_encoding_report(setup_job,tmp_path,monkeypatch):
    job,*_=setup_job;job.run(expected_revision=0);uid=target(job).document_id
    rival,_,_=job_for(tmp_path,bm25=BM25Settings(1.2,.5));process=job.batch_processor.process;winner=[]
    def compete(inputs):
        result=process(inputs);winner.append(rival.run(expected_revision=1));return result
    monkeypatch.setattr(job.batch_processor,'process',compete)
    with pytest.raises(IngestionJobError) as caught:job.remove_document(uid,expected_revision=1)
    error=caught.value
    assert error.stage=='activate' and error.code=='catalog_revision_conflict' and error.activation_status=='not_committed'
    assert error.encoding_report.status=='success' and error.candidate_bundle_id
    assert job.manager.catalog.read()==winner[0].active


def test_commit_uncertain_requires_catalog_readback(setup_job,monkeypatch):
    job,*_=setup_job;job.run(expected_revision=0);uid=target(job).document_id;commit=job.manager.catalog._commit
    def uncertain(conn):commit(conn);raise OSError(PRIVATE)
    monkeypatch.setattr(job.manager.catalog,'_commit',uncertain)
    with pytest.raises(IngestionJobError) as caught:job.remove_document(uid,expected_revision=1)
    error=caught.value
    assert error.stage=='activate' and error.code=='catalog_commit_uncertain' and error.activation_status=='unknown'
    assert error.encoding_report.status=='success' and error.candidate_bundle_id
    assert job.manager.catalog.read().revision==2


@pytest.mark.parametrize('when',['before','after'])
def test_unexpected_activation_failure_is_unknown(setup_job,monkeypatch,when):
    job,*_=setup_job;job.run(expected_revision=0);uid=target(job).document_id;activate=job.manager.activate
    def fail(*args,**kwargs):
        if when=='after':activate(*args,**kwargs)
        raise OSError(PRIVATE)
    monkeypatch.setattr(job.manager,'activate',fail)
    with pytest.raises(IngestionJobError) as caught:job.remove_document(uid,expected_revision=1)
    error=caught.value
    assert error.stage=='activate' and error.activation_status=='unknown' and error.encoding_report is not None
    assert job.manager.catalog.read().revision==(2 if when=='after' else 1)


@pytest.mark.parametrize('found',[True,False])
def test_finalize_failure_keeps_known_commit(setup_job,monkeypatch,found):
    import naiyue_rag.ingestion.pipeline as module
    job,*_=setup_job;job.run(expected_revision=0);uid=target(job).document_id if found else MISSING
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    monkeypatch.setattr(module,'RemovalReceipt',fail)
    with pytest.raises(IngestionJobError) as caught:job.remove_document(uid,expected_revision=1)
    error=caught.value
    assert error.stage=='finalize' and error.activation_status==('activated' if found else 'unchanged')
    assert (error.encoding_report is not None)==found
    assert job.manager.catalog.read().revision==(2 if found else 1)


def test_no_active_finalize_failure_remains_not_attempted(setup_job,monkeypatch):
    import naiyue_rag.ingestion.pipeline as module
    job,*_=setup_job
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    monkeypatch.setattr(module,'RemovalReceipt',fail)
    with pytest.raises(IngestionJobError) as caught:job.remove_document(MISSING,expected_revision=0)
    assert caught.value.stage=='plan' and caught.value.activation_status=='not_attempted'
    assert job.manager.catalog.read() is None


def test_control_interrupt_propagates_without_normal_error(setup_job,monkeypatch):
    job,*_=setup_job;first=job.run(expected_revision=0);uid=target(job).document_id
    def stop(*args):raise KeyboardInterrupt()
    monkeypatch.setattr(job.batch_processor,'process',stop)
    with pytest.raises(KeyboardInterrupt):job.remove_document(uid,expected_revision=1)
    assert job.manager.catalog.read()==first.active
