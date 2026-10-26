"""Version DTOs and local catalog boundaries; never imports the native Chroma SDK."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import pytest
from naiyue_rag.storage import IndexVersion,ActiveVersion,ActivationReceipt
from naiyue_rag.storage.index_catalog import IndexCatalog
from naiyue_rag.storage.bundle_store import _digest,_json_bytes
from naiyue_rag.core.errors import StorageError
from test_storage_bundle import storage_settings,KB,PRIVATE


def version(**changes):
    raw=dict(schema_version=1,knowledge_base_id=KB,bundle_id='1'*64,vector_index_id='2'*64,
        bm25_index_id='3'*64,document_count=1,chunk_count=2,source_fingerprint='4'*64,
        model_space_id='5'*64,representation_id='6'*64,tokenizer_id='7'*64,dimensions=3,
        chroma_collection_name='knowledge_hub',chroma_sdk_version='1.5.9',bm25_k1=1.5,
        bm25_b=.75,bm25_sdk_version='0.3.13')
    raw.update(changes)
    raw['version_id']=_digest(_json_bytes(raw,65536,newline=False))
    return raw


def catalog(tmp_path,**limits):
    cfg=storage_settings(tmp_path,**limits);cat=IndexCatalog(cfg)
    cat.path.parent.mkdir(parents=True,mode=0o700)
    return cat


def test_version_receipt_strict_roundtrip_and_copy():
    raw=version();obj=IndexVersion.from_dict(raw)
    active=ActiveVersion(1,obj);receipt=ActivationReceipt('activated',active)
    wire=json.loads(json.dumps(receipt.to_dict()))
    assert ActivationReceipt.from_dict(wire)==receipt
    wire['active']['version']['document_count']=PRIVATE
    assert receipt.active.version.document_count==1
    assert obj.to_dict()==raw and repr(obj).find(KB)==-1
    with pytest.raises(StorageError,match='catalog_invalid_request'):
        ActiveVersion(True,obj)
    with pytest.raises(StorageError,match='catalog_invalid_request'):
        ActivationReceipt('partial',active)
    with pytest.raises(StorageError):ActiveVersion.from_dict(dict(revision=1,version=raw,extra=1))
    with pytest.raises(StorageError):ActivationReceipt.from_dict(dict(status='activated',active=active.to_dict(),extra=1))


@pytest.mark.parametrize('field,value',[
    ('schema_version',True),('schema_version',2),('document_count',True),('chunk_count',-1),
    ('dimensions',0),('dimensions',True),('knowledge_base_id','bad\nname'),('knowledge_base_id',''),
    ('bundle_id','../bad'),('vector_index_id','A'*64),('bm25_index_id','x'),
    ('model_space_id','x'),('representation_id','x'),('tokenizer_id','x'),('source_fingerprint','x'),
    ('chroma_collection_name','bad/name'),('bm25_k1',0),('bm25_b',True),('bm25_b',1.1)])
def test_invalid_version_fields(field,value):
    with pytest.raises(StorageError):IndexVersion.from_dict(version(**{field:value}))


@pytest.mark.parametrize('fault',['extra','missing','hash','sdk','nan','inf'])
def test_version_mutation_rejected(fault):
    raw=version()
    if fault=='extra':raw['extra']=PRIVATE
    elif fault=='missing':raw.pop('chunk_count')
    elif fault=='hash':raw['chunk_count']+=1
    elif fault=='sdk':raw=version(chroma_sdk_version='old')
    else:raw['bm25_k1']=float(fault)
    with pytest.raises(StorageError):IndexVersion.from_dict(raw)


def test_missing_catalog_is_read_only(tmp_path):
    cfg=storage_settings(tmp_path);cat=IndexCatalog(cfg)
    assert cat.read() is None and not Path(cfg.storage_root).exists()


def test_catalog_atomic_registration_repeat_and_schema(tmp_path):
    cat=catalog(tmp_path);obj=IndexVersion.from_dict(version())
    with cat.write() as conn:
        assert cat.current(conn) is None
        cat.publish(conn,obj,1)
    assert cat.read()==ActiveVersion(1,obj)
    assert cat.path.stat().st_mode & 0o077==0
    before=cat.path.read_bytes()
    with cat.write() as conn:
        assert cat.lookup(conn,obj.version_id)==obj
    assert cat.path.read_bytes()==before
    with sqlite3.connect(cat.path) as conn:
        assert conn.execute('select count(*) from versions').fetchone()[0]==1


@pytest.mark.parametrize('fault',['garbage','empty','schema','trigger','dangling','json','version-hash'])
def test_bad_catalog_is_not_empty_or_repaired(tmp_path,fault):
    cat=catalog(tmp_path)
    if fault in ('garbage','empty'):
        cat.path.write_bytes(b'not sqlite' if fault=='garbage' else b'')
    else:
        with cat.write() as conn:cat.publish(conn,IndexVersion.from_dict(version()),1)
        with sqlite3.connect(cat.path) as conn:
            if fault=='schema':conn.execute('pragma user_version=2')
            elif fault=='trigger':conn.execute('create trigger bad after insert on versions begin select 1; end')
            elif fault=='dangling':conn.execute("update active set version_id=?",('f'*64,))
            elif fault=='json':conn.execute('update versions set descriptor_json=?',(PRIVATE,))
            else:
                raw=version();raw['chunk_count']=99
                conn.execute('update versions set descriptor_json=?',(_json_bytes(raw,65536,newline=False).decode(),))
    before=cat.path.read_bytes()
    with pytest.raises(StorageError):cat.read()
    assert cat.path.read_bytes()==before


@pytest.mark.parametrize('fault',['catalog-link','journal-link','fifo','ancestor-link'])
def test_catalog_paths_cannot_redirect(tmp_path,fault):
    cat=catalog(tmp_path);external=tmp_path/'external';external.write_text(PRIVATE)
    if fault=='catalog-link':cat.path.symlink_to(external)
    elif fault=='journal-link':Path(str(cat.path)+'-journal').symlink_to(external)
    elif fault=='fifo':
        import os
        os.mkfifo(cat.path)
    else:
        other=tmp_path/'other';other.mkdir()
        (other/cat.path.parent.name).symlink_to(cat.path.parent,target_is_directory=True)
        cat=IndexCatalog(replace(cat.settings,storage_root=str(other)))
    with pytest.raises(StorageError,match='catalog_path_invalid'):cat.read()
    assert external.read_text()==PRIVATE


def test_catalog_bounds_and_scope(tmp_path):
    cat=catalog(tmp_path)
    with cat.write() as conn:cat.publish(conn,IndexVersion.from_dict(version()),1)
    with pytest.raises(StorageError,match='catalog_limit_exceeded'):
        IndexCatalog(replace(cat.settings,max_bundle_bytes=1,max_file_bytes=1,max_manifest_bytes=1)).read()
    with pytest.raises(StorageError,match='catalog_limit_exceeded'):
        IndexCatalog(replace(cat.settings,max_manifest_bytes=128)).read()
    with sqlite3.connect(cat.path) as conn:
        raw=version(knowledge_base_id='other');conn.execute('delete from active');conn.execute('delete from versions')
        conn.execute('insert into versions values (?,?)',(raw['version_id'],_json_bytes(raw,65536,newline=False).decode()))
        conn.execute('insert into active values (1,?,1)',(raw['version_id'],))
    with pytest.raises(StorageError,match='catalog_identity_mismatch'):cat.read()


@pytest.mark.parametrize('fault',['connect','commit-before','commit-after','directory-sync'])
def test_interrupted_initialization_never_repairs_existing_file(tmp_path,monkeypatch,fault,caplog):
    import naiyue_rag.storage.index_catalog as module
    cat=catalog(tmp_path);original=cat._commit
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    with monkeypatch.context() as patch:
        if fault=='connect':patch.setattr(module.sqlite3,'connect',fail)
        elif fault=='directory-sync':patch.setattr(cat.bundles,'_sync_directory',fail)
        else:
            def commit(conn):
                if fault=='commit-after':original(conn)
                fail()
            patch.setattr(cat,'_commit',commit)
        expected='catalog_write_failed' if fault=='connect' else 'catalog_commit_uncertain'
        with pytest.raises(StorageError,match=expected):
            with cat.write():pytest.fail('initialization did not complete')
    assert cat.path.exists()
    before=cat.path.read_bytes()
    if fault in ('commit-after','directory-sync'):assert cat.read() is None
    else:
        with pytest.raises(StorageError):
            with cat.write():pytest.fail('existing incomplete catalog must not be repaired')
    assert cat.path.read_bytes()==before and PRIVATE not in caplog.text


def test_page_limit_before_commit_rolls_back_pointer(tmp_path,monkeypatch):
    cat=catalog(tmp_path)
    with cat.write() as conn:cat.publish(conn,IndexVersion.from_dict(version()),1)
    old=cat.read();original=cat._size
    def limit(conn):
        if conn.total_changes:raise StorageError('catalog_limit_exceeded')
        original(conn)
    monkeypatch.setattr(cat,'_size',limit)
    with pytest.raises(StorageError,match='catalog_limit_exceeded'):
        with cat.write() as conn:cat.publish(conn,IndexVersion.from_dict(version(chunk_count=3)),2)
    assert cat.read()==old


@pytest.mark.parametrize('code',[sqlite3.SQLITE_IOERR,sqlite3.SQLITE_READONLY_ROLLBACK])
def test_catalog_io_and_readonly_recovery_are_read_failures(tmp_path,monkeypatch,code,caplog):
    import naiyue_rag.storage.index_catalog as module
    cat=catalog(tmp_path)
    with cat.write() as conn:cat.publish(conn,IndexVersion.from_dict(version()),1)
    before=cat.path.read_bytes();connect=module.sqlite3.connect
    class ReadFault:
        def __init__(self,conn):self.conn=conn
        def __getattr__(self,name):return getattr(self.conn,name)
        def execute(self,sql,*args):
            if sql=='PRAGMA quick_check(1)':
                error=sqlite3.OperationalError(PRIVATE);error.sqlite_errorcode=code
                raise error
            return self.conn.execute(sql,*args)
    monkeypatch.setattr(module.sqlite3,'connect',lambda *a,**kw:ReadFault(connect(*a,**kw)))
    with pytest.raises(StorageError,match='catalog_read_failed'):cat.read()
    assert cat.path.read_bytes()==before and PRIVATE not in caplog.text
