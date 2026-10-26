"""Native Chroma query/score geometry and new-process formal Dense consumers."""
from pathlib import Path
import os
import json
import subprocess
import sys
import pytest
from test_ingestion_pipeline_wiring import launch as ingest
from test_query_preparation_wiring import launch as prepare


def isolated(root,action):
    import socket
    def deny(*args,**kwargs):raise AssertionError('unexpected encoding, network or latest lookup')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
    from naiyue_rag import DenseRetriever,DenseResult,PreparedQuery,QueryEncoder
    from naiyue_rag.storage import DocumentManager,StorageSettings,ChromaSettings,BM25Settings,BundleStore
    if action=='geometry':
        from dataclasses import replace
        import numpy as np
        from test_storage_bundle import ingredients,storage_settings
        from naiyue_rag.storage import prepare_index_bundle,VectorUpserter,ChromaStore
        data=ingredients(root);result=data['encoding_result']
        result.records=[replace(record,dense_vector=[1.,0.,0.] if i==0 else [-1.,0.,0.] if i==1 else [0.,1.,0.])
                        for i,record in enumerate(result.records)]
        bundle=prepare_index_bundle(**data);storage=storage_settings(root);uid=BundleStore(storage).save(bundle).bundle_id
        cfg=ChromaSettings('knowledge_hub',2);VectorUpserter(storage,cfg,project_root=root).build(uid)
        store=ChromaStore(storage,cfg,project_root=root);docs=sorted(d.id for d in bundle.documents)
        hits=store.query(uid,[1.,0.,0.],document_ids=docs,top_k=100)
        assert {round(h['distance'],5) for h in hits}=={0.,1.,2.}
        assert {round(h['score'],5) for h in hits}=={0.,.5,1.}
        nearest=store.query(uid,[1.,0.,0.],document_ids=docs,top_k=1)[0]
        scope=[d for d in docs if d!=nearest['chunk'].source_ref]
        scoped=store.query(uid,[1.,0.,0.],document_ids=scope,top_k=1)
        assert len(scoped)==1 and scoped[0]['chunk'].source_ref in scope and scoped[0]['distance']>.5
        print(json.dumps(dict(geometry='passed',scope_prefilter='passed',model_requests=0)))
        return
    job=json.loads((root/'job.json').read_text());cfg=StorageSettings.from_dict(job['storage'])
    ready=PreparedQuery.from_dict(json.loads((root/'prepared-query.json').read_text()))
    manager=DocumentManager(cfg,ChromaSettings('changed_default',1),BM25Settings(1.2,0),project_root=root)
    manager.catalog.read=deny;QueryEncoder.encode=deny
    result=DenseRetriever(manager).retrieve(ready,top_k=100)
    assert DenseResult.from_dict(json.loads(json.dumps(result.to_dict()))).to_dict()==result.to_dict()
    assert result.prepared.active.to_dict()==job['active']
    bundle=BundleStore(cfg).load(ready.active.version.bundle_id)
    expected={c.id:c.to_dict() for c in bundle.chunks if c.source_ref in ready.document_ids}
    assert {h.chunk.id:h.chunk.to_dict() for h in result.hits}==expected
    if result.hits:
        import numpy as np
        vectors={r.input.item_id:np.asarray(r.dense_vector,dtype=np.float32) for r in bundle.encoding_result.records}
        query=np.asarray(ready.encoding.dense_vector,dtype=np.float32)
        for hit in result.hits:
            vec=vectors[hit.chunk.id];distance=float(1-np.dot(query,vec)/(np.linalg.norm(query)*np.linalg.norm(vec)))
            assert abs(distance-hit.distance)<1e-5 and hit.score==max(0.,1-hit.distance/2)
        first=DenseRetriever(manager).retrieve(ready,top_k=1)
        assert len(first.hits)==1 and abs(first.hits[0].distance-result.hits[0].distance)<1e-5
    cases=[h for h in result.hits if h.chunk.metadata['kind']=='test_case']
    if cases:assert cases[0].chunk.metadata['case_fields'][-1]=='明确结果'
    print(json.dumps(dict(pid=os.getpid(),hits=len(result.hits),model_requests=0,version_id=ready.active.version.version_id)))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_dense_retrieval_wiring import isolated
isolated(Path(sys.argv[2]),sys.argv[3])
'''


def launch(root,action):
    proc=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),str(root),action],
        cwd=root,env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},text=True,capture_output=True,timeout=60)
    assert proc.returncode==0,proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize('mode,empty_scope',[('normal',False),('normal',True),('zero',False),('all-empty',False),('mixed',False)])
def test_native_dense_after_preparation_in_new_process(tmp_path,mode,empty_scope):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\nALLOW_RESET=true\nANONYMIZED_TELEMETRY=false\n')
    built=ingest(tmp_path,'build',mode)
    (tmp_path/'source').rename(tmp_path/'source-offline')
    ready=prepare(tmp_path,'prepare',mode,empty_scope)
    found=launch(tmp_path,'retrieve')
    assert found['pid']!=ready['pid'] and found['hits']==ready['chunk_count']
    assert found['version_id']==built['receipt']['active']['version']['version_id']
    assert found['model_requests']==ready['model_requests']==built['model_requests']==0


def test_native_cosine_geometry_and_scope_before_top_k(tmp_path):
    (tmp_path/'.env').write_text('ANONYMIZED_TELEMETRY=false\n')
    assert launch(tmp_path,'geometry')==dict(geometry='passed',scope_prefilter='passed',model_requests=0)
