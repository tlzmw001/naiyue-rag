"""Real pinned Chroma in isolated TEST processes; the library runs SDK in-process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest


def run_native(project,root,action):
    import socket
    def deny(*args,**kwargs):raise AssertionError('network forbidden')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
    from naiyue_rag.storage import (BundleStore,VectorUpserter,ChromaStore,load_chroma_settings,
                                  prepare_index_bundle,StorageSettings)
    from test_storage_bundle import ingredients,storage_settings
    import naiyue_rag.storage.chroma_backend as backend
    if action.startswith('build'):
        import httpx
        from naiyue_rag import (OpenAICompatibleEmbedding,DenseEncoder,SparseEncoder,BatchProcessor,
                               prepare_document_encoding_inputs)
        from test_sparse_encoding_settings import sparse_config
        from test_openai_embedding import payload
        data=ingredients(root,'empty' if action=='build-empty' else 'normal');cfg=data['encoding_settings'];requests=[]
        def respond(request):
            wire=json.loads(request.content);requests.append(wire)
            return httpx.Response(200,json=payload(len(wire['input'])))
        original=httpx.HTTPTransport;httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
        try:
            with OpenAICompatibleEmbedding(cfg,api_key='SYNTHETIC-NOT-A-KEY') as provider:
                result=BatchProcessor(cfg,DenseEncoder(cfg,provider),SparseEncoder(cfg,sparse_config(root))).process(
                    prepare_document_encoding_inputs(data['documents'],data['chunks'],cfg))
        finally:httpx.HTTPTransport=original
        data['encoding_result']=result;bundle=prepare_index_bundle(**data);cfg=storage_settings(root)
        receipt=BundleStore(cfg).save(bundle)
        saved=dict(settings=cfg.to_dict(),bundle_id=receipt.bundle_id)
        (root/'job.json').write_text(json.dumps(saved))
    else:
        job=json.loads((root/'job.json').read_text());cfg=StorageSettings.from_dict(job['settings'])
        receipt=type('Saved',(),{'bundle_id':job['bundle_id']})()
        bundle=BundleStore(cfg).load(receipt.bundle_id)
        requests=[]
    cc=load_chroma_settings(root/'chroma.yaml')
    # Observe actual native Settings, not just the construction arguments.
    original_client=backend.new_client;opens=[]
    def checked_client(path,project_root):
        client=original_client(path,project_root);settings=client.get_settings()
        assert not settings.allow_reset and not settings.anonymized_telemetry
        assert settings.chroma_memory_limit_bytes==104857600
        opens.append(1);return client
    backend.new_client=checked_client
    if action.startswith('build'):
        writer=VectorUpserter(cfg,cc,project_root=root)
        built=writer.build(receipt.bundle_id);assert built.status=='ready'
        assert writer.build(receipt.bundle_id).status=='unchanged'
    else:
        # Forbid business writes on actual SDK classes in the reloading process.
        import chromadb
        from chromadb.api.client import Client
        from chromadb.api.models.Collection import Collection
        def forbidden(*args,**kwargs):raise AssertionError('unexpected business write')
        Client.create_collection=Client.get_or_create_collection=forbidden
        Collection.upsert=Collection.delete=forbidden
        Client.reset=forbidden
    reader=ChromaStore(cfg,cc,project_root=root);checked=reader.audit(receipt.bundle_id)
    ids=[c.id for c in bundle.chunks]
    got={}
    for start in range(0,len(ids),cc.batch_size):got.update(reader.get_by_ids(receipt.bundle_id,ids[start:start+cc.batch_size]))
    assert {i:c.to_dict() for i,c in got.items()}=={c.id:c.to_dict() for c in bundle.chunks}
    if bundle.chunks:
        case=next(c for c in got.values() if c.metadata['kind']=='test_case')
        assert case.metadata['case_fields'][-1]=='明确结果'
    assert reader.get_by_ids(receipt.bundle_id,[])=={}
    print(json.dumps(dict(status='complete',count=checked.chunk_count,opens=len(opens),
                         model_requests=0,mock_requests=len(requests),pid=os.getpid())))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_chroma_native import run_native
run_native(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3])
'''


def launch(root,action,cwd):
    child=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),str(root),action],
        cwd=cwd,env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},
        capture_output=True,text=True,timeout=45)
    assert child.returncode==0,child.stderr
    return json.loads(child.stdout)


def test_real_formal_encoding_store_and_new_process(tmp_path):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\n'
        'ALLOW_RESET=true\nANONYMIZED_TELEMETRY=false\nCHROMA_MEMORY_LIMIT_BYTES=104857600\n')
    (tmp_path/'chroma.yaml').write_text('collection_name: knowledge_hub\nbatch_size: 2\n')
    first=launch(tmp_path,'build',tmp_path)
    elsewhere=tmp_path/'other-cwd';elsewhere.mkdir()
    second=launch(tmp_path,'read',elsewhere)
    assert first['status']==second['status']=='complete'
    assert first['count']==second['count']>0 and first['pid']!=second['pid']
    assert first['mock_requests']>0 and second['mock_requests']==0
    assert first['model_requests']==second['model_requests']==0
    index=next((tmp_path/'storage').glob('*/vectors/*/chroma'))
    assert all(p.stat().st_mode & 0o077==0 for p in index.rglob('*'))


def test_real_empty_index_and_reload(tmp_path):
    (tmp_path/'.env').write_text('CHROMA_MEMORY_LIMIT_BYTES=104857600\nANONYMIZED_TELEMETRY=false\n')
    (tmp_path/'chroma.yaml').write_text('collection_name: knowledge_hub\nbatch_size: 2\n')
    first=launch(tmp_path,'build-empty',tmp_path);second=launch(tmp_path,'read',tmp_path)
    assert first['count']==second['count']==0
    assert first['mock_requests']==second['mock_requests']==0


def test_invalid_shared_env_import_has_safe_error(tmp_path):
    (tmp_path/'.env').write_text('ALLOW_RESET=SYNTHETIC-PRIVATE-INVALID\n')
    script='''
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from naiyue_rag.storage.chroma_backend import new_client
from naiyue_rag.core.errors import StorageError
try:new_client(Path(sys.argv[2])/'database',Path(sys.argv[2]))
except StorageError as error:print(error.code)
else:raise AssertionError('invalid SDK configuration accepted')
'''
    child=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).resolve().parents[1]),str(tmp_path)],
        cwd=tmp_path,env={'HOME':str(tmp_path),'PATH':os.defpath},capture_output=True,text=True,timeout=30)
    assert child.returncode==0 and child.stdout.strip()=='chroma_environment_invalid'
    assert 'SYNTHETIC-PRIVATE-INVALID' not in child.stderr
    assert not (tmp_path/'database').exists()
