"""One real bundle/Chroma/BM25 generation, restart pinning and process writer exclusion."""
from contextlib import redirect_stdout
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import pytest


def native_job(root,action,mode):
    # Reuse the existing real M1/M2/M3 + SDK MockTransport + native BM25 chain.
    from test_bm25_native import run_job
    with redirect_stdout(io.StringIO()):run_job(root,action,mode)
    from naiyue_rag.storage import (DocumentManager,BundleStore,ChromaStore,VectorUpserter,
        BM25Store,StorageSettings,ChromaSettings,BM25Settings,ActiveVersion)
    job=json.loads((root/'job.json').read_text());cfg=StorageSettings.from_dict(job['storage'])
    cs=ChromaSettings('knowledge_hub',2);bs=BM25Settings(1.5,.75)
    if action=='build':
        vector=VectorUpserter(cfg,cs,project_root=root).build(job['bundle_id'])
        manager=DocumentManager(cfg,cs,bs,project_root=root)
        active=manager.activate(job['bundle_id'],expected_revision=0).active
        assert active.version.vector_index_id==vector.index_id
        (root/'active.json').write_text(json.dumps(active.to_dict()))
        assert manager.activate(job['bundle_id'],expected_revision=1).status=='unchanged'
    else:
        expected=ActiveVersion.from_dict(json.loads((root/'active.json').read_text()))
        manager=DocumentManager(cfg,ChromaSettings('changed_default',1),BM25Settings(9,0),project_root=root)
        active=manager.open_active();assert active==expected
    version=active.version
    # The returned descriptor actually configures all three downstream consumers.
    bundle=BundleStore(cfg).load(version.bundle_id)
    vector=ChromaStore(cfg,ChromaSettings(version.chroma_collection_name,2),project_root=root)
    bm25=BM25Store(cfg,BM25Settings(version.bm25_k1,version.bm25_b)).audit(version.bundle_id)
    assert bm25.index_id==version.bm25_index_id
    ids=[c.id for c in bundle.chunks];got={}
    for start in range(0,len(ids),2):got.update(vector.get_by_ids(version.bundle_id,ids[start:start+2]))
    assert [got[c.id].to_dict() for c in bundle.chunks]==[c.to_dict() for c in bundle.chunks]
    assert ids==job['ids'] and len(ids)==version.chunk_count
    if mode=='normal':
        case=next(c for c in got.values() if c.metadata['kind']=='test_case')
        assert case.metadata['case_fields'][-1]=='明确结果'
    assert bm25.empty_chunk_count==(len(ids) if mode in ('zero','all-empty') else 0) or mode=='mixed'
    assert manager.open_active()==active
    print(json.dumps(dict(pid=os.getpid(),active=active.to_dict(),model_requests=0)))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_document_manager_wiring import native_job
native_job(Path(sys.argv[2]),sys.argv[3],sys.argv[4])
'''


def launch(root,action,mode):
    child=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),
        str(root),action,mode],cwd=root,env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},
        capture_output=True,text=True,timeout=60)
    assert child.returncode==0,child.stderr
    return json.loads(child.stdout)


@pytest.mark.parametrize('mode',['normal','zero','all-empty','mixed'])
def test_native_three_artifacts_activate_and_restart(tmp_path,mode):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\n'
        'ALLOW_RESET=true\nANONYMIZED_TELEMETRY=false\n')
    (tmp_path/'bm25.yaml').write_text('k1: 1.5\nb: 0.75\n')
    first=launch(tmp_path,'build',mode);second=launch(tmp_path,'read',mode)
    assert first['pid']!=second['pid'] and first['active']==second['active']
    assert first['model_requests']==second['model_requests']==0
    assert first['active']['revision']==1


def hold_catalog(settings,entered,release,results):
    from naiyue_rag.storage import StorageSettings,IndexVersion
    from naiyue_rag.storage.index_catalog import IndexCatalog
    from test_index_versions import version
    try:
        cat=IndexCatalog(StorageSettings.from_dict(settings))
        with cat.write() as conn:
            entered.set()
            if not release.wait(20):raise RuntimeError('test handshake timed out')
            cat.publish(conn,IndexVersion.from_dict(version(chunk_count=3)),2)
        results.put('committed')
    except Exception:results.put('failed')


def test_process_lock_and_stale_revision_without_sleep(tmp_path):
    from test_index_versions import catalog,version
    from naiyue_rag.storage import IndexVersion,DocumentManager,ChromaSettings,BM25Settings
    from naiyue_rag.core.errors import StorageError
    cat=catalog(tmp_path)
    with cat.write() as conn:cat.publish(conn,IndexVersion.from_dict(version()),1)
    ctx=multiprocessing.get_context('spawn');entered=ctx.Event();release=ctx.Event();results=ctx.Queue()
    worker=ctx.Process(target=hold_catalog,args=(cat.settings.to_dict(),entered,release,results));worker.start()
    manager=DocumentManager(cat.settings,ChromaSettings('knowledge_hub',2),BM25Settings(1.5,.75),project_root=tmp_path)
    try:
        assert entered.wait(20)
        with pytest.raises(StorageError,match='catalog_busy'):
            manager.activate('1'*64,expected_revision=1)
        # An uncommitted writer does not expose its future active version.
        assert cat.read().revision==1
        release.set();assert results.get(timeout=20)=='committed'
        worker.join(20);assert worker.exitcode==0
        with pytest.raises(StorageError,match='catalog_revision_conflict'):
            manager.activate('1'*64,expected_revision=1)
        assert cat.read().revision==2
    finally:
        release.set();worker.join(5)
        if worker.is_alive():worker.kill();worker.join(5)
        results.close();results.join_thread()
