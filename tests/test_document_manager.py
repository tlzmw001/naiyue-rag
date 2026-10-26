"""Activation coordinates real bundles/BM25 with the existing deterministic Chroma boundary."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import pytest
from naiyue_rag.storage import (DocumentManager,BundleStore,ChromaSettings,BM25Settings,
    VectorUpserter,BM25Indexer,ActiveVersion,ActivationReceipt)
from naiyue_rag.core.errors import StorageError
from test_bm25_store import save_bundle
from test_chroma_index import FakeClient
from test_storage_bundle import PRIVATE,storage_settings


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    import naiyue_rag.storage.chroma_backend as backend
    events=[];fault={}
    monkeypatch.setattr(backend,'new_client',lambda path,root:FakeClient(path,events,fault))
    cfg,uid,bundle=save_bundle(tmp_path)
    cs=ChromaSettings('knowledge_hub',2);bs=BM25Settings(1.5,.75)
    VectorUpserter(cfg,cs,project_root=tmp_path).build(uid);BM25Indexer(cfg,bs).build(uid)
    return DocumentManager(cfg,cs,bs,project_root=tmp_path),uid,bundle,fault,events


def second(prepared,tmp_path):
    manager,_,_,_,_=prepared
    child=tmp_path/'second';child.mkdir()
    _,uid,bundle=save_bundle(child)
    cfg=manager.settings;uid=BundleStore(cfg).save(bundle).bundle_id
    # Different index parameters on the same bundle still form another exact version.
    cs=ChromaSettings('other_collection',3);bs=BM25Settings(1.2,0)
    VectorUpserter(cfg,cs,project_root=tmp_path).build(uid);BM25Indexer(cfg,bs).build(uid)
    return DocumentManager(cfg,cs,bs,project_root=tmp_path),uid


def test_activate_repeat_reopen_and_fixed_identity(prepared,tmp_path,monkeypatch):
    manager,uid,bundle,_,events=prepared
    assert manager.open_active() is None
    def forbidden(*args,**kwargs):pytest.fail('activation must not build')
    monkeypatch.setattr(VectorUpserter,'build',forbidden);monkeypatch.setattr(BM25Indexer,'build',forbidden)
    receipt=manager.activate(uid,expected_revision=0)
    assert receipt.status=='activated' and receipt.active.revision==1
    active=manager.open_active();assert active==receipt.active
    assert active.version.bundle_id==uid and active.version.chunk_count==len(bundle.chunks)
    assert ActivationReceipt.from_dict(receipt.to_dict())==receipt
    assert manager.activate(uid,expected_revision=1).status=='unchanged'
    assert manager.open_active().revision==1
    changed=DocumentManager(manager.settings,ChromaSettings('changed_default',1),BM25Settings(2,0),project_root=tmp_path)
    assert changed.open_active()==active and events.count('create')==1
    with sqlite3.connect(manager.catalog.path) as conn:
        assert conn.execute('select count(*) from versions').fetchone()[0]==1


def test_switch_and_stale_revision_preserve_pinned_version(prepared,tmp_path):
    manager,uid,_,_,_=prepared;g1=manager.activate(uid,expected_revision=0).active
    newer,new_uid=second(prepared,tmp_path)
    g2=newer.activate(new_uid,expected_revision=1).active
    assert g2.revision==2 and g2.version.version_id!=g1.version.version_id
    assert manager.open_active()==g2
    assert BundleStore(manager.settings).load(g1.version.bundle_id).chunks
    with pytest.raises(StorageError,match='catalog_revision_conflict'):manager.activate(uid,expected_revision=1)
    assert manager.open_active()==g2
    assert manager.activate(uid,expected_revision=2).active.revision==3
    with pytest.raises(StorageError,match='catalog_revision_conflict'):manager.activate(uid,expected_revision=1)


@pytest.mark.parametrize('value',[True,-1,1.0,None,2**63])
def test_invalid_revision_has_no_catalog_side_effects(prepared,value):
    manager,uid,_,_,_=prepared
    with pytest.raises(StorageError,match='catalog_invalid_request'):manager.activate(uid,expected_revision=value)
    assert not manager.catalog.path.exists()


@pytest.mark.parametrize('uid',['../outside',None,'x','A'*64])
def test_invalid_bundle_id_has_no_catalog_side_effects(prepared,uid):
    manager,*_=prepared
    with pytest.raises(StorageError,match='catalog_invalid_request'):manager.activate(uid,expected_revision=0)
    assert not manager.catalog.path.exists()


@pytest.mark.parametrize('fault',['bm25','chroma','bundle','close'])
def test_bad_active_artifact_is_not_silently_repaired(prepared,fault):
    manager,uid,_,flags,_=prepared;active=manager.activate(uid,expected_revision=0).active
    if fault=='bm25':
        p=manager.catalog.path.parent/'bm25'/active.version.bm25_index_id/'rows.json';p.write_text('[]')
    elif fault=='chroma':flags['text']=True
    elif fault=='close':flags['close']=True
    else:
        p=manager.catalog.path.parent/'artifacts'/uid/'chunks.json';p.write_text('[]')
    with pytest.raises(StorageError):manager.open_active()
    assert manager.catalog.read()==active


@pytest.mark.parametrize('fault',['missing-bm25','bad-chroma','mismatched-receipt','audit-close'])
def test_failed_candidate_keeps_old_active_and_no_new_registration(prepared,tmp_path,monkeypatch,fault,caplog):
    from naiyue_rag.storage import ChromaStore
    manager,uid,_,flags,_=prepared;old=manager.activate(uid,expected_revision=0).active
    newer,new_uid=second(prepared,tmp_path)
    if fault=='missing-bm25':newer.bm25_settings=BM25Settings(9,.1)
    elif fault=='bad-chroma':flags['metadata']=True
    elif fault=='audit-close':flags['close']=True
    else:
        original=ChromaStore.audit
        def wrong(self,bundle_id):return replace(original(self,bundle_id),model_space_id='a'*64)
        monkeypatch.setattr(ChromaStore,'audit',wrong)
    with pytest.raises(StorageError):newer.activate(new_uid,expected_revision=1)
    assert manager.catalog.read()==old
    with sqlite3.connect(manager.catalog.path) as conn:
        assert conn.execute('select count(*) from versions').fetchone()[0]==1
    assert PRIVATE not in caplog.text


@pytest.mark.parametrize('fault',['publish','pointer','commit-before','commit-after','close','rollback-close'])
def test_catalog_failures_are_observable_without_partial_success(prepared,tmp_path,monkeypatch,fault,caplog):
    manager,uid,_,_,_=prepared;old=manager.activate(uid,expected_revision=0).active
    newer,new_uid=second(prepared,tmp_path);cat=newer.catalog
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    if fault=='publish':monkeypatch.setattr(cat,'publish',fail)
    elif fault=='pointer':
        original=cat.publish
        def pointer(conn,obj,revision):
            conn.execute('insert into versions values (?,?)',(obj.version_id,json.dumps(obj.to_dict())))
            fail()
        monkeypatch.setattr(cat,'publish',pointer)
    elif fault.startswith('commit'):
        original=cat._commit
        def commit(conn):
            if fault=='commit-after':original(conn)
            fail()
        monkeypatch.setattr(cat,'_commit',commit)
    elif fault=='close':
        original=cat._close
        def close(conn):original(conn);fail()
        monkeypatch.setattr(cat,'_close',close)
    else:
        original_rollback=cat._rollback;original_close=cat._close
        monkeypatch.setattr(cat,'publish',fail)
        def rollback(conn):original_rollback(conn);fail()
        def close(conn):original_close(conn);fail()
        monkeypatch.setattr(cat,'_rollback',rollback);monkeypatch.setattr(cat,'_close',close)
    expected='catalog_commit_uncertain' if fault.startswith('commit') or fault=='close' else 'catalog_write_failed'
    with pytest.raises(StorageError,match=expected):newer.activate(new_uid,expected_revision=1)
    # Read with a fresh catalog, without executing the injected cleanup path again.
    got=manager.catalog.read()
    assert got.revision==(2 if fault in ('commit-after','close') else 1)
    if got.revision==1:assert got==old
    if fault=='rollback-close':assert 'catalog_cleanup_failed' in caplog.text
    assert PRIVATE not in caplog.text


def test_busy_report_after_commit_must_remain_uncertain(prepared,tmp_path,monkeypatch):
    manager,uid,_,_,_=prepared;manager.activate(uid,expected_revision=0)
    newer,new_uid=second(prepared,tmp_path);original=newer.catalog._commit
    def committed_then_busy(conn):
        original(conn)
        error=sqlite3.OperationalError(PRIVATE);error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        raise error
    monkeypatch.setattr(newer.catalog,'_commit',committed_then_busy)
    with pytest.raises(StorageError,match='catalog_commit_uncertain'):
        newer.activate(new_uid,expected_revision=1)
    assert manager.catalog.read().revision==2


@pytest.mark.parametrize('action',['unchanged','read'])
def test_no_write_cleanup_failure_is_explicit(prepared,monkeypatch,action):
    manager,uid,_,_,_=prepared;active=manager.activate(uid,expected_revision=0).active
    original=manager.catalog._close
    def fail(conn):original(conn);raise OSError(PRIVATE)
    monkeypatch.setattr(manager.catalog,'_close',fail)
    with pytest.raises(StorageError,match='catalog_cleanup_failed'):
        if action=='unchanged':manager.activate(uid,expected_revision=1)
        else:manager.open_active()
    monkeypatch.setattr(manager.catalog,'_close',original)
    assert manager.open_active()==active


def test_first_failed_audit_leaves_valid_empty_catalog(prepared,monkeypatch):
    from naiyue_rag.storage import ChromaStore,BM25Store
    manager,uid,_,_,_=prepared
    def fail(*args):raise StorageError('chroma_close_failed')
    def forbidden(*args):pytest.fail('must stop after failed vector audit')
    monkeypatch.setattr(ChromaStore,'audit',fail);monkeypatch.setattr(BM25Store,'audit',forbidden)
    with pytest.raises(StorageError,match='chroma_close_failed'):manager.activate(uid,expected_revision=0)
    assert manager.catalog.read() is None
    with sqlite3.connect(manager.catalog.path) as conn:
        assert conn.execute('select count(*) from versions').fetchone()[0]==0


@pytest.mark.parametrize('field',['source_fingerprint','vector_index_id','bm25_index_id'])
def test_open_active_cross_checks_persisted_binding(prepared,field):
    from naiyue_rag.storage import IndexVersion
    from naiyue_rag.storage.bundle_store import _digest,_json_bytes
    manager,uid,_,_,_=prepared;active=manager.activate(uid,expected_revision=0).active
    raw=active.version.to_dict();raw.pop('version_id');raw[field]='f'*64
    raw['version_id']=_digest(_json_bytes(raw,65536,newline=False))
    with manager.catalog.write() as conn:manager.catalog.publish(conn,IndexVersion.from_dict(raw),2)
    with pytest.raises(StorageError,match='catalog_identity_mismatch'):manager.open_active()
    assert manager.catalog.read().revision==2


def test_revision_overflow_does_not_publish(prepared,tmp_path):
    manager,uid,_,_,_=prepared;manager.activate(uid,expected_revision=0)
    with sqlite3.connect(manager.catalog.path) as conn:conn.execute('update active set revision=?',(2**63-1,))
    newer,new_uid=second(prepared,tmp_path)
    with pytest.raises(StorageError,match='catalog_limit_exceeded'):newer.activate(new_uid,expected_revision=2**63-1)
    assert manager.catalog.read().revision==2**63-1


def test_actual_revision_preserves_historical_l2_and_old_snapshot(prepared,tmp_path):
    from naiyue_rag import (MarkdownLoader,DocumentChunker,prepare_knowledge_base,
        prepare_document_encoding_inputs,BatchProcessor)
    from naiyue_rag.storage import prepare_index_bundle,ChromaStore
    from test_storage_bundle import Dense,KB
    from test_batch_processor import Sparse
    manager,uid,bundle,_,_=prepared;old=manager.activate(uid,expected_revision=0).active
    source=tmp_path/'source'
    (source/'L1_Module.md').write_text('# 模块v2\n\n新增规则；[历史](L2_A.md)；[新增](L2_B.md)。\n')
    (source/'L2_B.md').write_text('# 新需求B\n\nthreshold=0.8；其余规则回归历史A。\n')
    docs=MarkdownLoader(source,KB,4096).load_all();cfg=bundle.encoding_settings
    chunks,relations,_=prepare_knowledge_base(docs,DocumentChunker(bundle.ingestion_settings),text_mode='raw')
    result=BatchProcessor(cfg,Dense(cfg),Sparse(cfg)).process(prepare_document_encoding_inputs(docs,chunks,cfg))
    candidate=prepare_index_bundle(docs,chunks,relations,result,knowledge_base_id=KB,
        encoding_settings=cfg,ingestion_settings=bundle.ingestion_settings)
    new_uid=BundleStore(manager.settings).save(candidate).bundle_id
    VectorUpserter(manager.settings,manager.chroma_settings,project_root=tmp_path).build(new_uid)
    with pytest.raises(StorageError,match='bm25_index_not_found'):manager.activate(new_uid,expected_revision=1)
    assert manager.open_active()==old
    BM25Indexer(manager.settings,manager.bm25_settings).build(new_uid)
    new=manager.activate(new_uid,expected_revision=1).active
    restored=BundleStore(manager.settings).load(new.version.bundle_id)
    paths={d.metadata['source_path']:d for d in restored.documents}
    before={d.metadata['source_path']:d for d in bundle.documents}
    assert {'L1_Module.md','L2_A.md','L2_B.md','L2_A_测试用例.md'}==set(paths)
    assert paths['L2_A.md'].to_dict()==before['L2_A.md'].to_dict()
    assert paths['L1_Module.md'].id==before['L1_Module.md'].id
    assert paths['L1_Module.md'].metadata['source_sha256']!=before['L1_Module.md'].metadata['source_sha256']
    old_bundle=BundleStore(manager.settings).load(old.version.bundle_id)
    assert old_bundle.to_dict()==bundle.to_dict() and manager.open_active()==new
    reader=ChromaStore(manager.settings,manager.chroma_settings,project_root=tmp_path)
    old_ids=[c.id for c in old_bundle.chunks[:2]]
    assert set(reader.get_by_ids(old.version.bundle_id,old_ids))==set(old_ids)


def test_real_sqlite_commit_busy_rolls_back_without_switch(prepared,tmp_path):
    manager,uid,_,_,_=prepared;old=manager.activate(uid,expected_revision=0).active
    newer,new_uid=second(prepared,tmp_path)
    reader=sqlite3.connect(manager.catalog.path,isolation_level=None)
    try:
        reader.execute('BEGIN');reader.execute('SELECT * FROM active').fetchall()
        with pytest.raises(StorageError,match='catalog_busy'):newer.activate(new_uid,expected_revision=1)
    finally:reader.close()
    assert manager.open_active()==old
    with sqlite3.connect(manager.catalog.path) as conn:
        assert conn.execute('select count(*) from versions').fetchone()[0]==1


def test_sql_pointer_failure_rolls_back_inserted_version(prepared,tmp_path,monkeypatch):
    manager,uid,_,_,_=prepared;old=manager.activate(uid,expected_revision=0).active
    newer,new_uid=second(prepared,tmp_path);original=newer.catalog.publish
    def restricted(conn,obj,revision):
        def authorize(action,table,*args):
            return sqlite3.SQLITE_DENY if table=='active' and action==sqlite3.SQLITE_INSERT else sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
        original(conn,obj,revision)
    monkeypatch.setattr(newer.catalog,'publish',restricted)
    with pytest.raises(StorageError,match='catalog_write_failed'):newer.activate(new_uid,expected_revision=1)
    assert manager.catalog.read()==old
    with sqlite3.connect(manager.catalog.path) as conn:
        assert conn.execute('select count(*) from versions').fetchone()[0]==1


def test_constructor_and_empty_read_do_not_load_env_or_sdk(tmp_path,monkeypatch):
    import builtins
    import naiyue_rag.storage.chroma_backend as backend
    real_open=builtins.open;real_path_open=Path.open
    def checked_open(path,*args,**kwargs):
        if isinstance(path,(str,Path)) and Path(path).name=='.env':pytest.fail('dotenv must not be loaded here')
        return real_open(path,*args,**kwargs)
    def path_open(path,*args,**kwargs):
        if path.name=='.env':pytest.fail('dotenv must not be loaded here')
        return real_path_open(path,*args,**kwargs)
    def forbidden(*args):pytest.fail('native SDK is not needed for construction or no active version')
    monkeypatch.setattr(builtins,'open',checked_open);monkeypatch.setattr(Path,'open',path_open)
    monkeypatch.setattr(backend,'new_client',forbidden)
    cfg=storage_settings(tmp_path)
    manager=DocumentManager(cfg,ChromaSettings('knowledge_hub',2),BM25Settings(1.5,.75),project_root=tmp_path)
    assert manager.open_active() is None and not Path(cfg.storage_root).exists()
