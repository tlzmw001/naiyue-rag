"""Formal Chroma contracts with deterministic IO/SDK failures, no native import."""
import copy
import json
from pathlib import Path
import pytest
from naiyue_rag.storage import (ChromaSettings,load_chroma_settings,VectorUpserter,ChromaStore,BundleStore)
from naiyue_rag.core.errors import SettingsError,StorageError
from test_storage_bundle import make_bundle,storage_settings,PRIVATE


@pytest.mark.parametrize('name,batch', [('bad/name',2),('ab',2),('127.0.0.1',2),('valid_name',0),
    ('valid_name',True),('valid_name',1.5)])
def test_invalid_chroma_configuration(name,batch):
    with pytest.raises(SettingsError,match='invalid_chroma_settings'):ChromaSettings(name,batch)


def test_strict_chroma_yaml(tmp_path):
    p=tmp_path/'config.yaml';p.write_text('collection_name: knowledge_hub\nbatch_size: 2\n')
    assert load_chroma_settings(p)==ChromaSettings('knowledge_hub',2)
    for bad in ['batch_size: 2\nbatch_size: 3','collection_name: valid_name\nbatch_size: 2\nextra: true',
                'collection_name: &a valid_name\nbatch_size: *a']:
        p.write_text(bad)
        with pytest.raises(SettingsError):load_chroma_settings(p)


class FakeClient:
    def __init__(self,path,events,fault):
        self.path=Path(path);self.events=events;self.fault=fault;self.file=self.path/'fake.json'
        self.data=json.loads(self.file.read_text()) if self.file.exists() else None
    def get_max_batch_size(self):return 100
    def create_collection(self,name,*,metadata,embedding_function,configuration):
        self.events.append('create');assert embedding_function is None
        self.path.mkdir(parents=True,exist_ok=True)
        self.data=dict(metadata=metadata,rows={},configuration={**configuration,'embedding_function':None})
        self.save();return self
    def get_collection(self,name,*,embedding_function):
        self.events.append('open');assert embedding_function is None
        if self.data is None:raise OSError(PRIVATE)
        return self
    @property
    def metadata(self):return self.data['metadata']
    @property
    def configuration(self):return self.data['configuration']
    def save(self):self.file.write_text(json.dumps(self.data))
    def upsert(self,*,ids,embeddings,documents,metadatas):
        self.events.append('upsert')
        if self.fault.get('write_at')==self.events.count('upsert'):raise OSError(PRIVATE)
        for uid,v,d,m in zip(ids,embeddings,documents,metadatas,strict=True):
            self.data['rows'][uid]=[v,d,m]
        self.save()
    def count(self):return len(self.data['rows'])
    def get(self,*,ids,include):
        self.events.append('get');ids=list(reversed(ids))
        if self.fault.get('missing'):ids=ids[:-1]
        rows=[copy.deepcopy(self.data['rows'][uid]) for uid in ids]
        if self.fault.get('vector') and rows:rows[0][0][0]+=1
        if self.fault.get('text') and rows:rows[0][1]+=PRIVATE
        if self.fault.get('metadata') and rows:rows[0][2]['source_sha256']='0'*64
        return dict(ids=ids,embeddings=[r[0] for r in rows],documents=[r[1] for r in rows],
                    metadatas=[r[2] for r in rows])
    def close(self):
        self.events.append('close')
        if self.fault.get('close'):raise OSError(PRIVATE)


@pytest.fixture
def setup_index(tmp_path,monkeypatch):
    import naiyue_rag.storage.chroma_backend as backend
    events=[];fault={}
    monkeypatch.setattr(backend,'new_client',lambda path,project_root:FakeClient(path,events,fault))
    cfg=storage_settings(tmp_path);bundle=make_bundle(tmp_path);saved=BundleStore(cfg).save(bundle)
    args=(cfg,ChromaSettings('knowledge_hub',2))
    writer=VectorUpserter(*args,project_root=tmp_path);reader=ChromaStore(*args,project_root=tmp_path)
    return writer,reader,saved.bundle_id,bundle,events,fault,cfg


def test_formal_roundtrip_repeat_and_isolation(setup_index):
    writer,reader,uid,bundle,events,_,_=setup_index
    receipt=writer.build(uid)
    assert receipt.status=='ready' and receipt.chunk_count==len(bundle.chunks)
    before=events.count('upsert');again=writer.build(uid)
    assert again.status=='unchanged' and events.count('upsert')==before
    assert reader.audit(uid).status=='verified'
    ids=[c.id for c in bundle.chunks[:2]]
    got=reader.get_by_ids(uid,ids)
    assert list(got)==ids and [got[i].to_dict() for i in ids]==[c.to_dict() for c in bundle.chunks[:2]]
    got[ids[0]].text=PRIVATE
    assert reader.get_by_ids(uid,ids)[ids[0]].text!=PRIVATE
    assert reader.get_by_ids(uid,[])=={}
    assert events.count('create')==1 and events.count('close')>=6


@pytest.mark.parametrize('fault',['missing','vector','text','metadata'])
def test_read_corruption_not_hidden_by_bundle(setup_index,fault,caplog):
    writer,reader,uid,_,_,flags,_=setup_index
    writer.build(uid);flags[fault]=True
    with pytest.raises(StorageError,match='chroma_integrity_failed'):reader.audit(uid)
    assert PRIVATE not in caplog.text


def test_write_failure_stops_batches_and_no_ready(setup_index,caplog):
    writer,_,uid,_,events,fault,cfg=setup_index;fault['write_at']=2
    with pytest.raises(StorageError,match='chroma_write_failed'):writer.build(uid)
    assert events.count('upsert')==2 and events[-1]=='close'
    assert not list(Path(cfg.storage_root).glob('*/vectors/*/ready.json'))
    assert PRIVATE not in caplog.text


def test_close_failure_does_not_publish_and_primary_error_preserved(setup_index):
    writer,_,uid,_,events,fault,cfg=setup_index;fault['close']=True
    with pytest.raises(StorageError,match='chroma_close_failed'):writer.build(uid)
    assert not list(Path(cfg.storage_root).glob('*/vectors/*/ready.json'))
    # Fake fault counters span both build attempts: target the next actual write.
    fault['write_at']=events.count('upsert')+1
    with pytest.raises(StorageError,match='chroma_write_failed'):writer.build(uid)
    assert events.count('upsert')==fault['write_at']


def test_missing_and_invalid_ids_do_not_create(setup_index):
    writer,reader,uid,bundle,events,cfg_fault,cfg=setup_index
    with pytest.raises(StorageError,match='chroma_index_not_found'):reader.audit(uid)
    assert events==[] and not list(Path(cfg.storage_root).glob('*/vectors'))
    writer.build(uid);before=len(events)
    for ids in [['unknown'],[bundle.chunks[0].id]*2,[c.id for c in bundle.chunks[:3]]]:
        with pytest.raises(StorageError,match='chroma_invalid_request'):reader.get_by_ids(uid,ids)
    assert len(events)==before


def test_bad_ready_is_not_repaired(setup_index):
    writer,reader,uid,_,events,_,cfg=setup_index;writer.build(uid)
    p=next(Path(cfg.storage_root).glob('*/vectors/*/ready.json'));p.write_text('{}\n')
    before=len(events)
    with pytest.raises(StorageError,match='chroma_index_incomplete'):reader.audit(uid)
    assert p.read_text()=='{}\n' and len(events)==before


@pytest.mark.parametrize('fault',['extra-record','identity','configuration','native-missing','native-symlink'])
def test_native_tampering_is_not_repaired(setup_index,fault,tmp_path):
    writer,reader,uid,_,events,_,cfg=setup_index;writer.build(uid)
    root=next(Path(cfg.storage_root).glob('*/vectors/*/chroma'));p=root/'fake.json'
    data=json.loads(p.read_text())
    if fault=='extra-record':data['rows']['unbound']=next(iter(data['rows'].values()))
    elif fault=='identity':data['metadata']['model_space_id']='0'*64
    elif fault=='configuration':data['configuration']['hnsw']['space']='l2'
    elif fault=='native-missing':p.unlink()
    else:
        elsewhere=tmp_path/'elsewhere';elsewhere.write_text(p.read_text());p.unlink();p.symlink_to(elsewhere)
    if fault not in ['native-missing','native-symlink']:p.write_text(json.dumps(data))
    before=events.count('upsert')
    with pytest.raises(StorageError):reader.audit(uid)
    assert events.count('upsert')==before


def test_sdk_batch_limit_prevents_create(setup_index):
    writer,_,uid,_,events,_,_=setup_index
    writer.config=ChromaSettings('knowledge_hub',101)
    with pytest.raises(StorageError,match='chroma_batch_limit'):writer.build(uid)
    assert events==['close']


@pytest.mark.parametrize('mode',['empty','blank'])
def test_empty_native_contract(tmp_path,monkeypatch,mode):
    import naiyue_rag.storage.chroma_backend as backend
    events=[];monkeypatch.setattr(backend,'new_client',lambda p,r:FakeClient(p,events,{}))
    cfg=storage_settings(tmp_path);saved=BundleStore(cfg).save(make_bundle(tmp_path,mode))
    writer=VectorUpserter(cfg,ChromaSettings('knowledge_hub',2),project_root=tmp_path)
    receipt=writer.build(saved.bundle_id)
    assert receipt.chunk_count==0 and writer.audit(saved.bundle_id).verified_count==0
    assert 'upsert' not in events and 'get' not in events


@pytest.mark.parametrize('fault',['marker-write','rename','parent-sync'])
def test_publication_failure_not_reported_ready(setup_index,monkeypatch,fault):
    import naiyue_rag.storage.chroma_index as module
    writer,reader,uid,_,_,_,cfg=setup_index
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    if fault=='marker-write':monkeypatch.setattr(writer.bundles,'_write_file',fail)
    elif fault=='rename':monkeypatch.setattr(module.os,'rename',fail)
    else:
        original=writer.bundles._sync_directory
        def sync(path):
            if path.name=='vectors':fail()
            original(path)
        monkeypatch.setattr(writer.bundles,'_sync_directory',sync)
    code='chroma_publish_uncertain' if fault=='parent-sync' else 'chroma_publish_failed' if fault=='rename' else 'chroma_write_failed'
    with pytest.raises(StorageError,match=code):writer.build(uid)
    if fault=='parent-sync':assert reader.audit(uid).status=='verified'
    else:assert not list(Path(cfg.storage_root).glob('*/vectors/[!.]*/ready.json'))


def test_non_float32_vector_rejected_before_index_creation(tmp_path):
    bundle=make_bundle(tmp_path);bundle.encoding_result.records[0].dense_vector=[1e300,2.,3.]
    cfg=storage_settings(tmp_path);receipt=BundleStore(cfg).save(bundle)
    writer=VectorUpserter(cfg,ChromaSettings('knowledge_hub',2),project_root=tmp_path)
    with pytest.raises(StorageError,match='chroma_integrity_failed'):writer.build(receipt.bundle_id)
    assert not list(Path(cfg.storage_root).glob('*/vectors'))


def test_missing_sdk_package_reports_fixed_code(monkeypatch,tmp_path):
    import naiyue_rag.storage.chroma_backend as backend
    def missing(name):raise backend.metadata.PackageNotFoundError(PRIVATE)
    monkeypatch.setattr(backend.metadata,'version',missing)
    with pytest.raises(StorageError,match='chroma_runtime_mismatch'):
        backend.new_client(tmp_path/'native',tmp_path)
