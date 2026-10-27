"""Explicit saved policies preserve the pre-change bundle and native reload."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from naiyue_rag import DocumentChunker,IngestionSettings
from naiyue_rag.core.errors import SettingsError,ChunkingError,StorageError
from naiyue_rag.storage import IndexBundle,BundleStore
from test_storage_bundle import storage_settings
from test_settings import configuration
from test_document_chunker import document,assert_bound,offline

FIXTURE=Path(__file__).parent/'fixtures/chunking-v1-bundle.json'


def test_explicit_legacy_policy_matches_default_and_serialization():
    implicit=IngestionSettings.from_dict(dict(chunk_size=40,chunk_overlap=10))
    explicit=IngestionSettings(40,10,chunking_policy='markdown-source-v1')
    assert implicit==explicit
    assert explicit.to_dict()=={'chunk_size':40,'chunk_overlap':10}
    restored=IngestionSettings.from_dict(explicit.to_dict())
    assert restored.chunking_policy=='markdown-source-v1'
    assert IngestionSettings.from_dict(explicit.to_dict()|{'chunking_policy':'markdown-source-v1'})==explicit
    doc=document('# 模块\n\n'+'重复中文正文。'*15)
    old,_=DocumentChunker(implicit).split_document(doc)
    new,_=DocumentChunker(explicit).split_document(doc)
    assert [c.to_dict() for c in old]==[c.to_dict() for c in new]
    assert_bound(doc,new)


def test_saved_missing_policy_does_not_follow_future_runtime_default(monkeypatch):
    import naiyue_rag.core.ingestion_settings as module
    monkeypatch.setattr(module,'DEFAULT_CHUNKING_POLICY','future-unknown-default')
    saved=IngestionSettings.from_dict({'chunk_size':40,'chunk_overlap':10})
    assert saved.chunking_policy=='markdown-source-v1'
    with pytest.raises(ChunkingError):DocumentChunker(IngestionSettings(40,10))


@pytest.mark.parametrize('policy',['unknown','',True,[],1])
def test_unknown_policy_never_silently_uses_default(policy):
    settings=IngestionSettings(40,10,chunking_policy=policy)
    with pytest.raises(ChunkingError,match='invalid_chunking_config'):DocumentChunker(settings)


@pytest.mark.parametrize('extra',[{'unknown':1},{'chunking_policy':None}])
def test_saved_settings_fields_are_strict(extra):
    with pytest.raises(SettingsError):IngestionSettings.from_dict({'chunk_size':40,'chunk_overlap':10}|extra)


def test_runtime_settings_allow_explicit_policy_without_changing_snapshot_bridge(tmp_path):
    from naiyue_rag.core.settings import Settings
    raw=configuration(tmp_path);baseline=Settings.from_dict(raw).to_snapshot_config()
    raw['ingestion']={'chunk_size':40,'chunk_overlap':10,'chunking_policy':'markdown-source-v1'}
    settings=Settings.from_dict(raw)
    assert settings.ingestion.chunking_policy=='markdown-source-v1'
    assert settings.to_snapshot_config()==baseline


def test_frozen_legacy_manifest_and_new_process_read(tmp_path):
    fixture=json.loads(FIXTURE.read_text());bundle=IndexBundle.from_dict(fixture['bundle'])
    assert bundle.ingestion_settings.chunking_policy=='markdown-source-v1'
    assert bundle.to_dict()==fixture['bundle']
    cfg=storage_settings(tmp_path);store=BundleStore(cfg)
    header,_=store._materialize(bundle)
    assert header==fixture['manifest']
    receipt=store.save(bundle)
    assert receipt.bundle_id==fixture['manifest']['bundle_id']
    script='''
import json,socket,sys
sys.path.insert(0,sys.argv[1])
def deny(*args,**kwargs):raise AssertionError('network forbidden')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
from naiyue_rag.storage import BundleStore,StorageSettings
cfg=StorageSettings.from_dict(json.loads(sys.argv[2]))
store=BundleStore(cfg);bundle=store.load(sys.argv[3])
assert bundle.ingestion_settings.chunking_policy=='markdown-source-v1'
header,_=store._materialize(bundle)
assert header['bundle_id']==sys.argv[3]
print(json.dumps(bundle.to_dict(),ensure_ascii=False))
'''
    proc=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).resolve().parents[1]),
        json.dumps(cfg.to_dict()),receipt.bundle_id],capture_output=True,text=True,timeout=30)
    assert proc.returncode==0,proc.stderr
    assert json.loads(proc.stdout)==fixture['bundle']
    native_script='''
import json,socket,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
def deny(*args,**kwargs):raise AssertionError('network forbidden')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
from naiyue_rag.storage import (BundleStore,StorageSettings,VectorUpserter,BM25Indexer,
    DocumentManager,ChromaSettings,BM25Settings)
from naiyue_rag import QueryPipeline
from test_query_encoding import setup
cfg=StorageSettings.from_dict(json.loads(sys.argv[2]));uid=sys.argv[3]
root=Path(cfg.storage_root).parent;store=BundleStore(cfg);bundle=store.load(uid)
assert not (root/'source').exists()
cs=ChromaSettings('legacy_policy_test',2);bs=BM25Settings(1.5,.75)
VectorUpserter(cfg,cs,project_root=root).build(uid);BM25Indexer(cfg,bs).build(uid)
manager=DocumentManager(cfg,cs,bs,project_root=root)
active=manager.activate(uid,expected_revision=0).active
assert manager.open_active()==active
listing=manager.list_documents(expected_revision=1)
assert len(listing.documents)==len(bundle.documents)
for item in listing.documents:
    detail=manager.get_document_detail(item.document_id,expected_revision=1)
    assert detail.chunk_ids and detail.document.chunk_count==len(detail.chunk_ids)
encoder,dense,sparse=setup(bundle.encoding_settings)
prepared=QueryPipeline(manager,encoder).prepare('  检查  ',scope_document_ids=[],expected_revision=1)
assert prepared.status=='empty_scope' and prepared.active==active
assert dense.calls==sparse.calls==[]
assert store._materialize(store.load(uid))[0]['bundle_id']==uid
print(json.dumps(dict(documents=len(listing.documents),status=prepared.status,model_calls=0)))
'''
    proc=subprocess.run([sys.executable,'-I','-c',native_script,str(Path(__file__).resolve().parents[1]),
        json.dumps(cfg.to_dict()),receipt.bundle_id],capture_output=True,text=True,timeout=60,cwd=tmp_path,
        env={'HOME':str(tmp_path),'PATH':os.defpath,'OMP_NUM_THREADS':'1'})
    assert proc.returncode==0,proc.stderr
    assert json.loads(proc.stdout)==dict(documents=len(bundle.documents),status='empty_scope',model_calls=0)


@pytest.mark.parametrize('field,value',[
    ('parser_version','unknown-version'),('keep_separator',1),('config_sha256','0'*64),
    ('separators',['','。'])])
def test_changed_actual_profile_never_reuses_unchanged_sources(field,value):
    from test_file_integrity import plan
    fixture=json.loads(FIXTURE.read_text());bundle=IndexBundle.from_dict(fixture['bundle'])
    bundle.chunks[0].metadata['component_metadata'][field]=value
    assert not plan(bundle,bundle.documents).reuse_active
    with pytest.raises(StorageError,match='bundle_source_mismatch'):bundle.to_dict()


def test_saved_unknown_policy_and_unsupported_component_version_are_rejected():
    raw=json.loads(FIXTURE.read_text())['bundle']
    raw['ingestion_settings']['chunking_policy']='unknown'
    with pytest.raises(StorageError):IndexBundle.from_dict(raw)
    raw=json.loads(FIXTURE.read_text())['bundle']
    raw['chunks'][0]['metadata']['component_metadata']['splitter_version']='unknown-version'
    with pytest.raises(StorageError,match='bundle_source_mismatch'):IndexBundle.from_dict(raw)


def test_policy_parameters_are_independent_copies():
    from naiyue_rag.core.chunking_policy import chunking_parameters
    first=chunking_parameters('markdown-source-v1')
    first['separators'].clear()
    second=chunking_parameters('markdown-source-v1')
    assert second['separators']==['\n\n','\n','. ','! ','? ','; ',', ',' ','']
