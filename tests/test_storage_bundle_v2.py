"""New bundle format retains strict v1 reading and native downstream consumers."""
import json
import os
from pathlib import Path
import subprocess
import sys
from dataclasses import replace
import pytest
from naiyue_rag.core.errors import StorageError
from naiyue_rag.storage import BundleStore
from test_storage_bundle import make_bundle,storage_settings


def make_v2(root):
    from naiyue_rag.core.encoding_snapshot import EncodingSnapshot
    from naiyue_rag.core.ingestion_encoding_summary import IngestionEncodingSummary
    from naiyue_rag.storage.artifact_bundle_v2 import prepare_index_bundle_v2
    old=make_bundle(root);n=len(old.chunks)
    snapshot=EncodingSnapshot.from_result(old.knowledge_base_id,old.encoding_result)
    summary=IngestionEncodingSummary(n,n,0,old.encoding_result.report if n else None)
    bundle=prepare_index_bundle_v2(old.documents,old.chunks,old.relations,snapshot,summary,
        knowledge_base_id=old.knowledge_base_id,encoding_settings=old.encoding_settings,ingestion_settings=old.ingestion_settings)
    return old,bundle


def test_old_and_new_formats_remain_strict_and_independently_readable(tmp_path):
    from naiyue_rag.storage import IndexBundle
    from naiyue_rag.storage.artifact_bundle_v2 import IndexBundleV2
    old,new=make_v2(tmp_path);store=BundleStore(storage_settings(tmp_path))
    a=store.save(old);b=store.save(new)
    assert a.bundle_id!=b.bundle_id
    assert type(store.load(a.bundle_id)) is IndexBundle and type(store.load(b.bundle_id)) is IndexBundleV2
    assert store.load(a.bundle_id).to_dict()==old.to_dict()
    assert store.load(b.bundle_id).to_dict()==new.to_dict()
    assert store._materialize(new)[0]['schema_version']==2
    assert store.save(new).status=='unchanged'


@pytest.mark.parametrize('fault',['source','missing-record','summary-count','origin-job','extra'])
def test_new_bundle_never_weakens_source_or_job_binding(tmp_path,fault):
    from naiyue_rag.storage.artifact_bundle_v2 import IndexBundleV2
    _,new=make_v2(tmp_path);raw=new.to_dict()
    if fault=='source':raw['chunks'][0]['text']='changed'
    elif fault=='missing-record':raw['encoding_snapshot']['records'].pop()
    elif fault=='summary-count':raw['encoding_summary']['reused_chunk_count']=1
    elif fault=='origin-job':raw['encoding_snapshot']['origins'][0]['source_job_id']='0'*32
    else:raw['extra']=1
    with pytest.raises(StorageError):IndexBundleV2.from_dict(raw)


def test_native_indexes_management_and_query_prepare_consume_v2_in_new_process(tmp_path):
    old,new=make_v2(tmp_path);cfg=storage_settings(tmp_path);store=BundleStore(cfg)
    uid=store.save(new).bundle_id
    script='''
import json,socket,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
def deny(*args,**kwargs):raise AssertionError('network forbidden')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
from naiyue_rag.storage import (StorageSettings,BundleStore,VectorUpserter,BM25Indexer,
    DocumentManager,ChromaSettings,BM25Settings)
from naiyue_rag import QueryPipeline,KnowledgeReader
from test_query_encoding import setup
cfg=StorageSettings.from_dict(json.loads(sys.argv[2]));uid=sys.argv[3];root=Path(cfg.storage_root).parent
bundle=BundleStore(cfg).load(uid);cs=ChromaSettings('snapshot_v2_test',2);bs=BM25Settings(1.5,.75)
VectorUpserter(cfg,cs,project_root=root).build(uid);BM25Indexer(cfg,bs).build(uid)
manager=DocumentManager(cfg,cs,bs,project_root=root);active=manager.activate(uid,expected_revision=0).active
assert manager.open_active()==active and len(manager.list_documents().documents)==len(bundle.documents)
encoder,dense,sparse=setup(bundle.encoding_settings)
prepared=QueryPipeline(manager,encoder).prepare('  检查开关  ',expected_revision=1)
assert prepared.status=='ready' and len(dense.calls)==len(sparse.calls)==1
_,read=KnowledgeReader(cfg)._bundle(prepared)
assert read.to_dict()==bundle.to_dict()
print(json.dumps(dict(schema=2,chunks=len(read.chunks),model_api_requests=0)))
'''
    child=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).resolve().parents[1]),json.dumps(cfg.to_dict()),uid],
        text=True,capture_output=True,timeout=60,cwd=tmp_path,
        env={'HOME':str(tmp_path),'PATH':os.defpath,'OMP_NUM_THREADS':'1'})
    assert child.returncode==0,child.stderr
    assert json.loads(child.stdout)==dict(schema=2,chunks=len(old.chunks),model_api_requests=0)


def test_snapshot_job_limits_apply_only_to_current_encoded_records(tmp_path):
    from naiyue_rag import EncodingSnapshot,IngestionEncodingSummary,prepare_index_bundle_v2
    old,new=make_v2(tmp_path);cfg=old.encoding_settings
    limited=replace(cfg,runtime=replace(cfg.runtime,max_inputs=1,max_requests=1))
    raw=new.encoding_snapshot.to_dict()
    for origin in raw['origins']:origin.update(kind='reused',source_bundle_id='f'*64)
    snapshot=EncodingSnapshot.from_dict(raw);n=len(snapshot.records)
    reused=prepare_index_bundle_v2(old.documents,old.chunks,old.relations,snapshot,IngestionEncodingSummary(n,0,n,None),
        knowledge_base_id=old.knowledge_base_id,encoding_settings=limited,ingestion_settings=old.ingestion_settings)
    assert reused.encoding_summary.encoded_chunk_count==0 and len(reused.encoding_snapshot.records)>1
    with pytest.raises(StorageError):
        prepare_index_bundle_v2(old.documents,old.chunks,old.relations,new.encoding_snapshot,new.encoding_summary,
            knowledge_base_id=old.knowledge_base_id,encoding_settings=limited,ingestion_settings=old.ingestion_settings)


def test_v2_file_corruption_is_rejected_without_repair(tmp_path):
    _,new=make_v2(tmp_path);store=BundleStore(storage_settings(tmp_path));uid=store.save(new).bundle_id
    (store._path(uid)/'encoding.json').write_text('{}')
    with pytest.raises(StorageError,match='bundle_integrity_failed'):store.load(uid)
