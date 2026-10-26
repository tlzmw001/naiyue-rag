"""Native threaded Chroma/BM25 lifecycles and a complete query after restart."""
from pathlib import Path
import json
import os
import subprocess
import sys
import pytest
from test_ingestion_pipeline_wiring import launch as ingest


def native(root,mode,statistics_scope,empty_scope):
    import socket
    def deny(*args,**kwargs):raise AssertionError('external network forbidden')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
    import httpx
    from naiyue_rag import (HybridSearch,HybridSettings,HybridResult,EncodingSettings,OpenAICompatibleEmbedding,
        DenseEncoder,SparseEncoder,QueryEncoder)
    from naiyue_rag.storage import StorageSettings,ChromaSettings,BM25Settings,DocumentManager,BundleStore
    from test_sparse_encoding_settings import sparse_config
    from test_openai_embedding import payload
    job=json.loads((root/'job.json').read_text());cfg=EncodingSettings.from_dict(job['encoding'])
    storage=StorageSettings.from_dict(job['storage']);manager=DocumentManager(storage,ChromaSettings('new_default',1),BM25Settings(2,0),project_root=root)
    listing=manager.list_documents();scope=[] if empty_scope else [d.document_id for d in listing.documents if d.source_path.startswith('L2_')] if mode=='normal' else None
    query='完全中文问题' if mode=='all-empty' else 'cvr_ltv 开关 TC-01 0.5'
    seen=[]
    def respond(request):seen.append(json.loads(request.content));return httpx.Response(200,json=payload())
    transport=httpx.HTTPTransport;httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
    orders=[]
    try:
        with OpenAICompatibleEmbedding(cfg,api_key='SYNTHETIC-NOT-A-KEY') as provider:
            sparse=SparseEncoder(cfg,sparse_config(root,min_chinese_term_length=2 if mode=='normal' else 9999))
            encoder=QueryEncoder(cfg,DenseEncoder(cfg,provider),sparse)
            for parallel in (True,False):
                before=len(seen);settings=HybridSettings(20,20,10,60,statistics_scope,parallel)
                result=HybridSearch(manager,encoder,settings).search(query,scope_document_ids=scope,expected_revision=1)
                assert len(seen)-before==(1 if result.prepared.status=='ready' else 0)
                assert HybridResult.from_dict(json.loads(json.dumps(result.to_dict()))).to_dict()==result.to_dict()
                assert result.prepared.active.to_dict()==job['active']
                bundle=BundleStore(storage).load(result.prepared.active.version.bundle_id);chunks={c.id:c.to_dict() for c in bundle.chunks}
                expected={}
                for hits in (result.dense_hits,result.sparse_hits):
                    for rank,hit in enumerate(hits,1):expected[hit.chunk.id]=expected.get(hit.chunk.id,0)+1/(60+rank)
                ids=sorted(expected,key=lambda uid:(-expected[uid],uid))[:10]
                assert [h.chunk.id for h in result.hits]==ids
                for hit in result.hits:
                    assert hit.chunk.to_dict()==chunks[hit.chunk.id] and hit.chunk.source_ref in result.prepared.document_ids
                    assert hit.score==expected[hit.chunk.id]
                orders.append([(h.chunk.id,h.score,h.dense_rank,h.sparse_rank) for h in result.hits])
            assert orders[0]==orders[1]
        assert provider.closed
    finally:httpx.HTTPTransport=transport
    print(json.dumps(dict(pid=os.getpid(),hits=len(result.hits),mock_requests=len(seen),model_requests=0,
        native_parallel_and_serial_equal=True,statistics_scope=statistics_scope)))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_hybrid_search_wiring import native
native(Path(sys.argv[2]),sys.argv[3],sys.argv[4],sys.argv[5]=='yes')
'''


@pytest.mark.parametrize('mode,stats,empty_scope',[('normal','global',False),('normal','scope',False),
    ('normal','global',True),('zero','global',False),('all-empty','scope',False),('mixed','global',False),('mixed','scope',False)])
def test_native_hybrid_threaded_and_serial_after_restart(tmp_path,mode,stats,empty_scope):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\nALLOW_RESET=true\nANONYMIZED_TELEMETRY=false\n')
    built=ingest(tmp_path,'build',mode);(tmp_path/'source').rename(tmp_path/'source-offline')
    proc=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),str(tmp_path),mode,stats,'yes' if empty_scope else 'no'],
        cwd=tmp_path,env={'HOME':str(tmp_path),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},text=True,capture_output=True,timeout=60)
    assert proc.returncode==0,proc.stderr
    found=json.loads(proc.stdout)
    assert found['pid']!=built['pid'] and found['native_parallel_and_serial_equal']
    assert found['model_requests']==built['model_requests']==0
    assert found['mock_requests']==(0 if empty_scope or mode=='zero' else 2)
