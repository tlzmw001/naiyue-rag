"""A new reader process consumes the real Hybrid query's selected version and IDs."""
from pathlib import Path
import json
import os
import subprocess
import sys
import pytest
from test_ingestion_pipeline_wiring import launch as ingest


def native(root,action,mode):
    import socket
    def deny(*args,**kwargs):raise AssertionError('unexpected dependency or credential access')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
    if action=='query':
        import httpx
        from naiyue_rag import (HybridSearch,HybridSettings,EncodingSettings,OpenAICompatibleEmbedding,
            DenseEncoder,SparseEncoder,QueryEncoder)
        from naiyue_rag.storage import StorageSettings,DocumentManager,ChromaSettings,BM25Settings
        from test_sparse_encoding_settings import sparse_config
        from test_openai_embedding import payload
        job=json.loads((root/'job.json').read_text());cfg=EncodingSettings.from_dict(job['encoding'])
        manager=DocumentManager(StorageSettings.from_dict(job['storage']),ChromaSettings('knowledge_hub',2),BM25Settings(1.5,.75),project_root=root)
        requests=[]
        def respond(request):requests.append(1);return httpx.Response(200,json=payload())
        transport=httpx.HTTPTransport;httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
        try:
            with OpenAICompatibleEmbedding(cfg,api_key='SYNTHETIC-NOT-A-KEY') as provider:
                encoder=QueryEncoder(cfg,DenseEncoder(cfg,provider),SparseEncoder(cfg,sparse_config(root,min_chinese_term_length=2 if mode=='normal' else 9999)))
                result=HybridSearch(manager,encoder,HybridSettings(20,20,10,60,'global',True)).search('cvr_ltv 开关 TC-01 0.5')
                (root/'hybrid.json').write_text(json.dumps(result.to_dict()))
        finally:httpx.HTTPTransport=transport
        print(json.dumps(dict(pid=os.getpid(),hits=len(result.hits),mock_requests=len(requests),model_requests=0)))
        return
    import builtins
    original_open=builtins.open
    def guarded(path,*args,**kwargs):
        if isinstance(path,(str,os.PathLike)) and Path(path).name=='.env':deny()
        return original_open(path,*args,**kwargs)
    builtins.open=guarded
    from naiyue_rag import HybridResult,KnowledgeReader,QueryEncoder
    from naiyue_rag.storage import StorageSettings
    from naiyue_rag.storage.index_catalog import IndexCatalog
    import naiyue_rag.storage.chroma_backend as chroma
    import naiyue_rag.storage.bm25_backend as bm25
    IndexCatalog.read=deny;QueryEncoder.encode=deny;chroma.new_client=deny;bm25._sdk=deny
    job=json.loads((root/'job.json').read_text());cfg=StorageSettings.from_dict(job['storage'])
    result=HybridResult.from_dict(json.loads((root/'hybrid.json').read_text()));reader=KnowledgeReader(cfg)
    files=[p for p in Path(cfg.storage_root).rglob('*') if p.is_file()]
    before={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in files}
    for hit in result.hits:
        full=reader.read_chunk(result.prepared,hit.chunk.id,max_characters=10000)
        assert full['chunk']==hit.chunk.to_dict() and full['active']==result.prepared.active.to_dict()
        span=hit.chunk.metadata['body_span']
        excerpt=reader.read_lines(result.prepared,hit.chunk.source_ref,start_line=span['line_start'],end_line=span['line_end'],max_characters=10000)
        assert hit.chunk.text in excerpt['text'] and excerpt['source_sha256']==span['source_sha256']
        if hit.chunk.metadata['kind']=='test_case':assert full['chunk']['metadata']['case_fields'][-1]=='明确结果'
    for doc_id in result.prepared.document_ids:
        relations=reader.related_documents(result.prepared,doc_id,max_links=100)
        assert relations['active']==result.prepared.active.to_dict()
    assert before=={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in files}
    print(json.dumps(dict(pid=os.getpid(),hits=len(result.hits),storage_unchanged=True,model_requests=0)))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_knowledge_reader_wiring import native
native(Path(sys.argv[2]),sys.argv[3],sys.argv[4])
'''


def launch(root,action,mode):
    proc=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),str(root),action,mode],
        cwd=root,env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},text=True,capture_output=True,timeout=60)
    assert proc.returncode==0,proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize('mode',['normal','zero','all-empty','mixed'])
def test_native_hybrid_to_reader_in_another_process(tmp_path,mode):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\nANONYMIZED_TELEMETRY=false\nALLOW_RESET=true\n')
    first=ingest(tmp_path,'build',mode);(tmp_path/'source').rename(tmp_path/'source-offline')
    found=launch(tmp_path,'query',mode);read=launch(tmp_path,'read',mode)
    assert first['pid']!=found['pid']!=read['pid'] and read['hits']==found['hits']
    assert read['storage_unchanged'] and read['model_requests']==found['model_requests']==first['model_requests']==0
