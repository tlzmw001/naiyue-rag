"""Formal preparation through native snapshots, mocked HTTP and a new-process consumer."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_ingestion_pipeline_wiring import launch as ingest

QUERY='  cvr_ltv 0 1 0.5 TC-01 不开启 source:L2_A.md  '


def native_prepare(root,action,mode,empty_scope):
    import socket
    def forbidden(*args,**kwargs):raise AssertionError('unexpected external network or extra encoding')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=forbidden
    from naiyue_rag import PreparedQuery
    from naiyue_rag.storage import StorageSettings,ChromaSettings,BM25Settings,DocumentManager,BundleStore,ChromaStore
    job=json.loads((root/'job.json').read_text());storage=StorageSettings.from_dict(job['storage'])
    if action=='consume':
        result=PreparedQuery.from_dict(json.loads((root/'prepared-query.json').read_text()))
        selected=result.active;bundle=BundleStore(storage).load(selected.version.bundle_id)
        expected={c.id:c.to_dict() for c in bundle.chunks if c.source_ref in result.document_ids}
        assert set(expected)==set(result.chunk_ids)
        reader=ChromaStore(storage,ChromaSettings(selected.version.chroma_collection_name,2),project_root=root)
        chunks={}
        for start in range(0,len(result.chunk_ids),2):
            chunks.update(reader.get_by_ids(selected.version.bundle_id,result.chunk_ids[start:start+2]))
        assert {uid:c.to_dict() for uid,c in chunks.items()}==expected
        cases=[c for c in chunks.values() if c.metadata['kind']=='test_case']
        if mode=='normal' and not empty_scope:
            assert len(cases)==1 and cases[0].metadata['case_fields'][-1]=='明确结果'
        print(json.dumps(dict(pid=os.getpid(),chunk_count=len(chunks),model_requests=0)))
        return
    import httpx
    from naiyue_rag import (QueryPipeline,QueryEncoder,EncodingSettings,DenseEncoder,SparseEncoder,OpenAICompatibleEmbedding)
    from test_sparse_encoding_settings import sparse_config
    from test_openai_embedding import payload
    cfg=EncodingSettings.from_dict(job['encoding']);seen=[]
    def respond(request):
        wire=json.loads(request.content);seen.append(wire)
        return httpx.Response(200,json=payload(len(wire['input'])))
    transport=httpx.HTTPTransport;httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
    try:
        with OpenAICompatibleEmbedding(cfg,api_key='SYNTHETIC-NOT-A-KEY') as provider:
            sparse=SparseEncoder(cfg,sparse_config(root,min_chinese_term_length=2 if mode=='normal' else 9999))
            encoder=QueryEncoder(cfg,DenseEncoder(cfg,provider),sparse)
            manager=DocumentManager(storage,ChromaSettings('different_default',1),BM25Settings(1.2,0),project_root=root)
            listing=manager.list_documents(expected_revision=1)
            scope=[] if empty_scope else [d.document_id for d in listing.documents if d.source_path.startswith('L2_')] if mode=='normal' else None
            query='完全中文的问题' if mode=='all-empty' else QUERY
            result=QueryPipeline(manager,encoder).prepare(query,scope_document_ids=scope,expected_revision=1)
            assert PreparedQuery.from_dict(json.loads(json.dumps(result.to_dict()))).to_dict()==result.to_dict()
        assert provider.closed
    finally:httpx.HTTPTransport=transport
    assert result.active.to_dict()==job['active'] and manager.catalog.read()==result.active
    assert result.query_sha256==hashlib.sha256(query.strip().encode()).hexdigest()
    assert result.raw_query_sha256==hashlib.sha256(query.encode()).hexdigest()
    if empty_scope:assert result.status=='empty_scope'
    elif mode=='zero':assert result.status=='empty_index'
    else:assert result.status=='ready'
    assert len(seen)==(1 if result.status=='ready' else 0)
    if result.status=='ready':
        assert result.encoding.input.retrieval_text==query.strip() and result.encoding.input.embedding_text=='query: '+query.strip()
        assert result.encoding.report.requests['attempted_requests']==1
        if mode=='all-empty':assert result.encoding.query_terms==[]
        else:assert {'cvr_ltv','0','1','0.5','tc-01'}<=set(result.encoding.query_terms)
    # Internal DTO wire is test IPC, not an application trace or a final tool response.
    (root/'prepared-query.json').write_text(json.dumps(result.to_dict()))
    print(json.dumps(dict(pid=os.getpid(),status=result.status,chunk_count=len(result.chunk_ids),
        mock_requests=len(seen),model_requests=0,active=result.active.to_dict())))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_query_preparation_wiring import native_prepare
native_prepare(Path(sys.argv[2]),sys.argv[3],sys.argv[4],sys.argv[5]=='yes')
'''


def launch(root,action,mode,empty_scope=False):
    child=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),
        str(root),action,mode,'yes' if empty_scope else 'no'],cwd=root,
        env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},capture_output=True,text=True,timeout=60)
    assert child.returncode==0,child.stderr
    return json.loads(child.stdout)


@pytest.mark.parametrize('mode,empty_scope',[('normal',False),('normal',True),('zero',False),('all-empty',False),('mixed',False)])
def test_native_preparation_restart_and_pinned_chunk_consumer(tmp_path,mode,empty_scope):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\n'
        'ALLOW_RESET=true\nANONYMIZED_TELEMETRY=false\n')
    first=ingest(tmp_path,'build',mode)
    before=(tmp_path/'job.json').read_bytes()
    # The source root is absent; the stored source snapshot is sufficient for preparation.
    (tmp_path/'source').rename(tmp_path/'source-offline')
    ready=launch(tmp_path,'prepare',mode,empty_scope)
    assert ready['pid']!=first['pid'] and ready['active']==first['receipt']['active']
    assert (tmp_path/'job.json').read_bytes()==before
    consumed=launch(tmp_path,'consume',mode,empty_scope)
    assert consumed['pid']!=ready['pid'] and consumed['chunk_count']==ready['chunk_count']
    assert consumed['model_requests']==ready['model_requests']==first['model_requests']==0
