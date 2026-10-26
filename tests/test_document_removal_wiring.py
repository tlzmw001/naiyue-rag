"""Native triad removal/restart and the pre-existing ID consumer, no real network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_ingestion_pipeline_wiring import launch as ingest
from test_document_management_wiring import launch as consume


def native_removal(root,action,mode):
    import socket
    def forbidden(*args,**kwargs):raise AssertionError('unexpected network or source scan')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=forbidden
    import httpx
    from naiyue_rag import (IngestionPipeline,IngestionSettings,EncodingSettings,BatchProcessor,
        DenseEncoder,SparseEncoder,OpenAICompatibleEmbedding,RemovalReceipt)
    from naiyue_rag.storage import StorageSettings,ChromaSettings,BM25Settings,BundleStore,DocumentManager,ChromaStore
    from test_sparse_encoding_settings import sparse_config
    from test_openai_embedding import payload
    prior=json.loads((root/'original-job.json').read_text());storage=StorageSettings.from_dict(prior['storage'])
    cfg=EncodingSettings.from_dict(prior['encoding']);chroma=ChromaSettings('knowledge_hub',2);bm25=BM25Settings(1.5,.75)
    if action=='old':
        manager=DocumentManager(storage,chroma,bm25,project_root=root)
        version=prior['active']['version'];bundle=BundleStore(storage).load(prior['bundle_id'])
        assert manager._audit(prior['bundle_id'],chroma,bm25).to_dict()==version
        reader=ChromaStore(storage,chroma,project_root=root)
        chunks={}
        for start in range(0,len(prior['ids']),2):
            chunks.update(reader.get_by_ids(prior['bundle_id'],prior['ids'][start:start+2]))
        assert {c.id:c.to_dict() for c in chunks.values()}=={c.id:c.to_dict() for c in bundle.chunks}
        assert len(bundle.documents)==version['document_count']
        print(json.dumps(dict(pid=os.getpid(),old_document_count=len(bundle.documents),model_requests=0)))
        return
    seen=[]
    def respond(request):
        wire=json.loads(request.content);seen.append(wire)
        return httpx.Response(200,json=payload(len(wire['input'])))
    transport=httpx.HTTPTransport;httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
    try:
        with OpenAICompatibleEmbedding(cfg,api_key='SYNTHETIC-NOT-A-KEY') as provider:
            sparse=SparseEncoder(cfg,sparse_config(root,min_chinese_term_length=2 if mode=='normal' else 9999))
            batch=BatchProcessor(cfg,DenseEncoder(cfg,provider),sparse)
            job=IngestionPipeline(storage,IngestionSettings(40,10),batch,chroma,bm25,
                knowledge_base_root=root/'source',project_root=root)
            job.loader.load_all=forbidden
            listing=job.manager.list_documents(expected_revision=1)
            path='L2_A.md' if mode=='normal' else 'technical.md' if mode=='mixed' else 'empty.md'
            info=next((d for d in listing.documents if d.source_path==path),None)
            uid='doc-'+'0'*64 if info is None else info.document_id
            receipt=job.remove_document(uid,expected_revision=1)
        assert provider.closed
    finally:httpx.HTTPTransport=transport
    assert RemovalReceipt.from_dict(json.loads(json.dumps(receipt.to_dict())))==receipt
    assert receipt.previous_active.to_dict()==prior['active']
    assert receipt.status==('not_found' if mode=='zero' else 'removed')
    assert len(seen)==(0 if receipt.encoding_report is None else receipt.encoding_report.requests['attempted_requests'])
    assert job.manager.open_active()==receipt.active
    bundle=BundleStore(storage).load(receipt.active.version.bundle_id)
    assert all(d.id!=uid for d in bundle.documents) and all(c.source_ref!=uid for c in bundle.chunks)
    assert len(bundle.documents)==prior['active']['version']['document_count']-(info is not None)
    if mode in ('all-empty','mixed'):assert all(not r.sparse.tokens for r in bundle.encoding_result.records)
    if mode=='normal':assert any(c.metadata.get('case_id')=='TC-01' for c in bundle.chunks)
    listing=job.manager.list_documents(expected_revision=receipt.active.revision)
    details=[job.manager.get_document_detail(d.document_id,expected_revision=receipt.active.revision).to_dict()
             for d in listing.documents]
    (root/'job.json').write_text(json.dumps(dict(storage=storage.to_dict(),encoding=cfg.to_dict(),
        active=receipt.active.to_dict(),bundle_id=receipt.active.version.bundle_id,ids=[c.id for c in bundle.chunks])))
    print(json.dumps(dict(pid=os.getpid(),receipt=receipt.to_dict(),listing=listing.to_dict(),details=details,
        mock_requests=len(seen),model_requests=0)))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_document_removal_wiring import native_removal
native_removal(Path(sys.argv[2]),sys.argv[3],sys.argv[4])
'''


def launch(root,action,mode):
    child=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),
        str(root),action,mode],cwd=root,env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},
        capture_output=True,text=True,timeout=60)
    assert child.returncode==0,child.stderr
    return json.loads(child.stdout)


@pytest.mark.parametrize('mode',['normal','zero','all-empty','mixed'])
def test_native_removal_preserves_old_version_and_existing_consumer(tmp_path,mode):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\n'
        'ALLOW_RESET=true\nANONYMIZED_TELEMETRY=false\n')
    first=ingest(tmp_path,'build',mode)
    (tmp_path/'original-job.json').write_bytes((tmp_path/'job.json').read_bytes())
    original={p.name:p.read_bytes() for p in (tmp_path/'source').iterdir()}
    removed=launch(tmp_path,'remove',mode)
    assert removed['pid']!=first['pid'] and removed['model_requests']==0
    assert removed['receipt']['active']['revision']==(1 if mode=='zero' else 2)
    assert {p.name:p.read_bytes() for p in (tmp_path/'source').iterdir()}==original
    (tmp_path/'management.json').write_text(json.dumps(removed))
    observed=consume(tmp_path,'consume','normal' if mode=='normal' else mode)
    assert observed['pid']!=removed['pid'] and observed['model_requests']==0
    assert observed['chunk_count']==removed['receipt']['active']['version']['chunk_count']
    old=launch(tmp_path,'old',mode)
    assert old['model_requests']==0 and old['old_document_count']==first['receipt']['active']['version']['document_count']
