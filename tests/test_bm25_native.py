"""Real source/encoding/keyword persistence across separate test interpreters."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest


def run_job(root,action,mode):
    import socket
    def forbidden(*args,**kwargs):raise AssertionError('unexpected network or re-encoding')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=forbidden
    from naiyue_rag.storage import (BM25Indexer,BM25Store,load_bm25_settings,BundleStore,
                                  StorageSettings,prepare_index_bundle)
    from naiyue_rag.encoding.sparse_tokenizer import SparseTokenizer
    from naiyue_rag import SparseEncoder,DenseEncoder
    settings=load_bm25_settings(root/'bm25.yaml')
    if action=='build':
        import httpx
        from naiyue_rag import (MarkdownLoader,DocumentChunker,IngestionSettings,prepare_knowledge_base,
            prepare_document_encoding_inputs,OpenAICompatibleEmbedding,BatchProcessor,QueryEncoder)
        from test_storage_bundle import ingredients,storage_settings,KB
        from test_encoding_settings import config
        from test_sparse_encoding_settings import sparse_config
        from test_openai_embedding import payload
        if mode=='normal':data=ingredients(root)
        else:
            source=root/'source';source.mkdir()
            if mode!='zero':(source/'empty.md').write_text('# 空词片段\n\n完全中文的说明。\n')
            if mode=='mixed':(source/'technical.md').write_text('# 配置\n\ncvr_ltv=1 threshold=0.5 TC-01\n')
            cfg=config();ingestion=IngestionSettings(40,10)
            docs=MarkdownLoader(source,KB,4096).load_all()
            chunks,relations,_=prepare_knowledge_base(docs,DocumentChunker(ingestion),text_mode='raw')
            data=dict(documents=docs,chunks=chunks,relations=relations,knowledge_base_id=KB,
                      encoding_settings=cfg,ingestion_settings=ingestion)
        cfg=data['encoding_settings'];seen=[]
        def respond(request):
            wire=json.loads(request.content);seen.append(wire)
            return httpx.Response(200,json=payload(len(wire['input'])))
        original=httpx.HTTPTransport;httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
        try:
            with OpenAICompatibleEmbedding(cfg,api_key='SYNTHETIC-NOT-A-KEY') as provider:
                dense=DenseEncoder(cfg,provider)
                sparse=SparseEncoder(cfg,sparse_config(root,min_chinese_term_length=2 if mode=='normal' else 9999))
                result=BatchProcessor(cfg,dense,sparse).process(prepare_document_encoding_inputs(data['documents'],data['chunks'],cfg))
                terms=QueryEncoder(cfg,dense,sparse).encode('开关 开关 0.5 TC-01 cvr_ltv').query_terms if mode=='normal' else ['0.5']
        finally:httpx.HTTPTransport=original
        data['encoding_result']=result;bundle=prepare_index_bundle(**data);storage=storage_settings(root)
        uid=BundleStore(storage).save(bundle).bundle_id
        mocks=len(seen)
    else:
        job=json.loads((root/'job.json').read_text())
        storage=StorageSettings.from_dict(job['storage']);uid=job['bundle_id'];terms=job['terms'];mocks=0
    # The storage chain must consume persisted terms, never recompute them.
    SparseTokenizer.tokenize=forbidden;SparseEncoder.encode_batch=forbidden;DenseEncoder.encode_batch=forbidden
    writer=BM25Indexer(storage,settings)
    if action=='build':assert writer.build(uid).status=='ready'
    reader=BM25Store(storage,settings);receipt=reader.audit(uid)
    path,header,rows,records=reader._prepare(uid)
    model=reader._load_index(path,header,rows,records)
    scores=model.get_scores(terms).tolist() if model is not None else [0.]*len(rows)
    assert len(scores)==receipt.chunk_count
    if action=='build':
        (root/'job.json').write_text(json.dumps(dict(storage=storage.to_dict(),bundle_id=uid,
            terms=terms,scores=scores,ids=[r['item_id'] for r in rows])))
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in path.iterdir()}
        assert writer.build(uid).status=='unchanged'
        assert before=={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in path.iterdir()}
    else:
        assert scores==job['scores'] and [r['item_id'] for r in rows]==job['ids']
        assert 'openai' not in sys.modules
    assert 'chromadb' not in sys.modules
    print(json.dumps(dict(status='complete',chunk_count=receipt.chunk_count,
        empty_chunk_count=receipt.empty_chunk_count,vocab_count=receipt.vocab_count,
        mock_requests=mocks,model_requests=0,pid=os.getpid())))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_bm25_native import run_job
run_job(Path(sys.argv[2]),sys.argv[3],sys.argv[4])
'''


def launch(root,action,mode):
    child=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),str(root),action,mode],
        cwd=root,env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},
        capture_output=True,text=True,timeout=40)
    assert child.returncode==0,child.stderr
    return json.loads(child.stdout)


@pytest.mark.parametrize('mode',['normal','zero','all-empty','mixed'])
def test_formal_sdk_encoding_native_save_reload(tmp_path,mode):
    (tmp_path/'bm25.yaml').write_text('k1: 1.5\nb: 0.75\n')
    first=launch(tmp_path,'build',mode);second=launch(tmp_path,'read',mode)
    assert first['pid']!=second['pid'] and first['status']==second['status']=='complete'
    assert first['chunk_count']==second['chunk_count']
    assert first['model_requests']==second['model_requests']==0
    if mode=='normal':assert first['mock_requests']>0 and first['vocab_count']>0
    elif mode=='zero':assert first['chunk_count']==0 and first['mock_requests']==0
    elif mode=='all-empty':assert first['empty_chunk_count']==first['chunk_count']>0 and first['vocab_count']==0
    else:assert 0<first['empty_chunk_count']<first['chunk_count'] and first['vocab_count']>0
    paths=list((tmp_path/'storage').glob('*/bm25/*'))
    assert len(paths)==1
    assert paths[0].stat().st_mode&0o077==0
    assert all(p.stat().st_mode&0o077==0 for p in paths[0].iterdir())
