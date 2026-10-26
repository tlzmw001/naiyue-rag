"""Both configured statistics policies consume saved native snapshots after restart."""
from pathlib import Path
import json
import os
import subprocess
import sys
import pytest
from test_ingestion_pipeline_wiring import launch as ingest
from test_query_preparation_wiring import launch as prepare


def native(root):
    import socket
    def deny(*args,**kwargs):raise AssertionError('unexpected network, encoding or catalog selection')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
    from naiyue_rag import SparseRetriever,SparseResult,PreparedQuery,QueryEncoder,load_sparse_query_settings
    from naiyue_rag.storage import DocumentManager,StorageSettings,ChromaSettings,BM25Settings,BundleStore
    from test_sparse_retrieval import hand_scores
    job=json.loads((root/'job.json').read_text());cfg=StorageSettings.from_dict(job['storage'])
    ready=PreparedQuery.from_dict(json.loads((root/'prepared-query.json').read_text()))
    manager=DocumentManager(cfg,ChromaSettings('changed_default',1),BM25Settings(1.2,0),project_root=root)
    manager.catalog.read=deny;QueryEncoder.encode=deny
    bundle=BundleStore(cfg).load(ready.active.version.bundle_id);records=bundle.encoding_result.records
    bm25=next(Path(cfg.storage_root).glob('*/bm25/[!.]*'))
    before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in bm25.iterdir()};outputs={}
    for mode in ('global','scope'):
        path=root/'sparse-query.yaml';path.write_text(f'top_k: 20\nstatistics_scope: {mode}\n')
        result=SparseRetriever(manager,load_sparse_query_settings(path)).retrieve(ready)
        assert SparseResult.from_dict(json.loads(json.dumps(result.to_dict()))).to_dict()==result.to_dict()
        population=records if mode=='global' else [r for r in records if r.input.source_document_id in ready.document_ids]
        terms=[] if ready.encoding is None else ready.encoding.query_terms
        values=hand_scores([r.sparse for r in population],terms)
        expected={r.input.item_id:v for r,v in zip(population,values,strict=True)
                  if v>0 and r.input.source_document_id in ready.document_ids}
        order=sorted(expected,key=lambda uid:(-expected[uid],uid))[:20]
        assert [h.chunk.id for h in result.hits]==order
        chunks={c.id:c.to_dict() for c in bundle.chunks}
        for hit in result.hits:
            assert abs(hit.score-expected[hit.chunk.id])<1e-12 and hit.chunk.to_dict()==chunks[hit.chunk.id]
        assert result.prepared.active.to_dict()==job['active'] and result.statistics_scope==mode
        outputs[mode]=dict(hit_count=len(result.hits),score_kind=result.score_kind)
    assert before=={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in bm25.iterdir()}
    print(json.dumps(dict(pid=os.getpid(),modes=outputs,model_requests=0,bm25_files_unchanged=True)))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_sparse_retrieval_wiring import native
native(Path(sys.argv[2]))
'''


@pytest.mark.parametrize('mode,empty_scope',[('normal',False),('normal',True),('zero',False),('all-empty',False),('mixed',False)])
def test_native_sparse_modes_after_restart(tmp_path,mode,empty_scope):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\nALLOW_RESET=true\nANONYMIZED_TELEMETRY=false\n')
    built=ingest(tmp_path,'build',mode)
    (tmp_path/'source').rename(tmp_path/'source-offline')
    ready=prepare(tmp_path,'prepare',mode,empty_scope)
    proc=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),str(tmp_path)],
        cwd=tmp_path,env={'HOME':str(tmp_path),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},text=True,capture_output=True,timeout=60)
    assert proc.returncode==0,proc.stderr
    found=json.loads(proc.stdout)
    assert found['pid']!=ready['pid'] and found['bm25_files_unchanged']
    assert found['model_requests']==ready['model_requests']==built['model_requests']==0
    assert set(found['modes'])=={'global','scope'}
    if empty_scope or mode in ('zero','all-empty'):
        assert found['modes']['global']['hit_count']==found['modes']['scope']['hit_count']==0
