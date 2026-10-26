"""Public Pipeline runs across processes, with real local indexes and mocked HTTP only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_document_management_wiring import launch as consume


def native_job(root,action,mode):
    import socket
    def forbidden(*args,**kwargs):raise AssertionError('unexpected network or repeated encoding')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=forbidden
    import httpx
    from naiyue_rag import (IngestionPipeline,IngestionSettings,EncodingSettings,BatchProcessor,DenseEncoder,
        SparseEncoder,OpenAICompatibleEmbedding,IngestionReceipt)
    from naiyue_rag.storage import StorageSettings,ChromaSettings,BM25Settings,BundleStore
    from test_storage_bundle import ingredients,storage_settings
    from test_sparse_encoding_settings import sparse_config
    from test_encoding_settings import config
    from test_openai_embedding import payload
    if action=='build':
        ingredients(root,'normal' if mode=='normal' else 'empty')
        if mode in ('all-empty','mixed'):(root/'source/empty.md').write_text('# 空词片段\n\n完全中文的说明。\n')
        if mode=='mixed':(root/'source/technical.md').write_text('# 配置\n\ncvr_ltv=1 threshold=0.5 TC-01\n')
        cfg=config();storage=storage_settings(root);revision=0
    else:
        prior=json.loads((root/'job.json').read_text());storage=StorageSettings.from_dict(prior['storage'])
        cfg=EncodingSettings.from_dict(prior['encoding']);revision=prior['active']['revision']
        if action=='update':
            (root/'source/L1_Module.md').write_text('# 模块v2\n\n[历史A](L2_A.md)\n\n新规则。\n')
            (root/'source/L2_A.md').rename(root/'offline-A.md')
            (root/'source/L2_A_测试用例.md').rename(root/'offline-cases.md')
            (root/'source/L2_B.md').write_text('# B\n\n[模块](L1_Module.md)\n\n新需求。\n')
            (root/'source/L2_B_测试用例.md').write_text((root/'offline-cases.md').read_text().replace('A测试用例','B测试用例'))
    seen=[]
    def respond(request):
        wire=json.loads(request.content);seen.append(wire)
        return httpx.Response(200,json=payload(len(wire['input'])))
    transport=httpx.HTTPTransport;httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
    try:
        with OpenAICompatibleEmbedding(cfg,api_key='SYNTHETIC-NOT-A-KEY') as provider:
            sparse=SparseEncoder(cfg,sparse_config(root,min_chinese_term_length=2 if mode=='normal' else 9999))
            batch=BatchProcessor(cfg,DenseEncoder(cfg,provider),sparse)
            job=IngestionPipeline(storage,IngestionSettings(40,10),batch,ChromaSettings('knowledge_hub',2),
                BM25Settings(1.5,.75),knowledge_base_root=root/'source',project_root=root)
            if action=='repeat':batch.process=forbidden;sparse.encode_batch=forbidden
            receipt=job.run(expected_revision=revision)
        assert provider.closed
    finally:httpx.HTTPTransport=transport
    listing=job.manager.list_documents(expected_revision=receipt.active.revision)
    details=[job.manager.get_document_detail(d.document_id,expected_revision=receipt.active.revision).to_dict()
             for d in listing.documents]
    bundle=BundleStore(storage).load(receipt.active.version.bundle_id)
    if action=='repeat':
        assert seen==[] and receipt.encoding_report is None and receipt.status=='unchanged'
        assert receipt.active.to_dict()==prior['active']
        assert receipt.unchanged_document_count==len(bundle.documents)
    else:
        assert len(seen)==receipt.encoding_report.requests['attempted_requests']
        assert receipt.encoding_report.paired_input_count==len(bundle.chunks)
        if action=='update':
            assert receipt.active.revision==2 and receipt.retained_document_count==2
            assert receipt.added_document_count==2 and receipt.updated_document_count==1
            assert len(BundleStore(storage).load(prior['bundle_id']).documents)==3
        (root/'job.json').write_text(json.dumps(dict(storage=storage.to_dict(),encoding=cfg.to_dict(),
            active=receipt.active.to_dict(),bundle_id=receipt.active.version.bundle_id,ids=[c.id for c in bundle.chunks])))
    assert IngestionReceipt.from_dict(json.loads(json.dumps(receipt.to_dict())))==receipt
    assert job.manager.open_active()==receipt.active
    if mode=='all-empty':assert all(not r.sparse.tokens for r in bundle.encoding_result.records)
    elif mode=='mixed':assert any(r.sparse.tokens for r in bundle.encoding_result.records) and any(not r.sparse.tokens for r in bundle.encoding_result.records)
    print(json.dumps(dict(pid=os.getpid(),receipt=receipt.to_dict(),mock_requests=len(seen),model_requests=0,
        listing=listing.to_dict(),details=details)))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_ingestion_pipeline_wiring import native_job
native_job(Path(sys.argv[2]),sys.argv[3],sys.argv[4])
'''


def launch(root,action,mode):
    child=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),
        str(root),action,mode],cwd=root,env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},
        capture_output=True,text=True,timeout=60)
    assert child.returncode==0,child.stderr
    return json.loads(child.stdout)


@pytest.mark.parametrize('mode',['normal','zero','all-empty','mixed'])
def test_public_pipeline_restart_reuse_and_existing_chunk_consumer(tmp_path,mode):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\n'
        'ALLOW_RESET=true\nANONYMIZED_TELEMETRY=false\n')
    first=launch(tmp_path,'build',mode);again=launch(tmp_path,'repeat',mode)
    assert first['pid']!=again['pid'] and first['receipt']['active']==again['receipt']['active']
    assert first['model_requests']==again['model_requests']==again['mock_requests']==0
    assert again['receipt']['active']['revision']==1
    (tmp_path/'management.json').write_text(json.dumps(again))
    observed=consume(tmp_path,'consume',mode)
    assert observed['chunk_count']==again['receipt']['active']['version']['chunk_count']
    if mode=='normal':
        revised=launch(tmp_path,'update',mode)
        assert revised['receipt']['active']['revision']==2 and revised['receipt']['retained_document_count']==2
        (tmp_path/'management.json').write_text(json.dumps(revised))
        assert consume(tmp_path,'consume',mode)['chunk_count']==revised['receipt']['active']['version']['chunk_count']
