"""Real persisted artifacts feed SDK-free management, then an independent chunk consumer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_document_manager_wiring import launch as prepare


def read_job(root):
    import socket
    def forbidden(*args,**kwargs):raise AssertionError('forbidden management dependency')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=forbidden
    # Audit actual opens, including pathlib and C-level opens, rather than only loader calls.
    def audit(event,args):
        if event!='open' or not isinstance(args[0],(str,bytes,os.PathLike)):return
        path=Path(os.fsdecode(args[0])).absolute()
        if path.name=='.env' or any(path==root/name or root/name in path.parents
                                  for name in ('source','source-offline')):forbidden()
    sys.addaudithook(audit)
    from naiyue_rag import MarkdownLoader,DenseEncoder,SparseEncoder
    from naiyue_rag.encoding.sparse_tokenizer import SparseTokenizer
    import jieba
    from naiyue_rag.storage import (DocumentManager,StorageSettings,ChromaSettings,BM25Settings,
        ChromaStore,VectorUpserter,BM25Store,BM25Indexer,DocumentList,DocumentDetail)
    MarkdownLoader.load_all=forbidden
    DenseEncoder.encode_batch=SparseEncoder.encode_batch=SparseTokenizer.tokenize=forbidden
    jieba.Tokenizer.initialize=forbidden
    DocumentManager.open_active=forbidden
    for cls,names in [(ChromaStore,['audit','get_by_ids']),(VectorUpserter,['build']),
                      (BM25Store,['audit']),(BM25Indexer,['build'])]:
        for name in names:setattr(cls,name,forbidden)
    job=json.loads((root/'job.json').read_text())
    manager=DocumentManager(StorageSettings.from_dict(job['storage']),ChromaSettings('knowledge_hub',2),
        BM25Settings(1.5,.75),project_root=root)
    listing=manager.list_documents()
    details=[manager.get_document_detail(d.document_id,expected_revision=listing.active.revision).to_dict()
             for d in listing.documents]
    missing=manager.get_document_detail('doc-'+'0'*64,expected_revision=listing.active.revision)
    assert missing.document is None and missing.chunk_ids==[] and missing.active==listing.active
    assert DocumentList.from_dict(listing.to_dict())==listing
    assert all(DocumentDetail.from_dict(d).active==listing.active for d in details)
    assert all(name not in sys.modules for name in ('chromadb','bm25s','openai'))
    print(json.dumps(dict(pid=os.getpid(),listing=listing.to_dict(),details=details,model_requests=0)))


def consume_job(root,mode):
    import socket
    def forbidden(*args,**kwargs):raise AssertionError('unexpected network')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=forbidden
    from naiyue_rag.storage import (DocumentList,DocumentDetail,StorageSettings,ChromaSettings,ChromaStore)
    result=json.loads((root/'management.json').read_text());listing=DocumentList.from_dict(result['listing'])
    job=json.loads((root/'job.json').read_text());active=listing.active
    reader=ChromaStore(StorageSettings.from_dict(job['storage']),
        ChromaSettings(active.version.chroma_collection_name,2),project_root=root)
    seen=[];cases=0
    for raw in result['details']:
        detail=DocumentDetail.from_dict(raw);assert detail.active==active
        chunks={}
        for start in range(0,len(detail.chunk_ids),2):
            chunks.update(reader.get_by_ids(active.version.bundle_id,detail.chunk_ids[start:start+2]))
        assert set(chunks)==set(detail.chunk_ids)
        for chunk in chunks.values():
            assert chunk.source_ref==detail.document.document_id
            assert chunk.metadata['body_span']['source_sha256']==detail.document.source_sha256
            if chunk.metadata['kind']=='test_case':
                assert chunk.metadata['case_fields'][-1]=='明确结果';cases+=1
        seen.extend(detail.chunk_ids)
    assert set(seen)==set(job['ids']) and len(seen)==active.version.chunk_count
    if mode=='normal':assert cases>0
    print(json.dumps(dict(pid=os.getpid(),chunk_count=len(seen),model_requests=0)))


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_document_management_wiring import read_job,consume_job
root=Path(sys.argv[2])
if sys.argv[3]=='read':read_job(root)
else:consume_job(root,sys.argv[4])
'''


def launch(root,action,mode):
    child=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(Path(__file__).resolve().parents[1]),
        str(root),action,mode],cwd=root,env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},
        capture_output=True,text=True,timeout=60)
    assert child.returncode==0,child.stderr
    return json.loads(child.stdout)


def snapshot(root):
    return {str(p.relative_to(root)):(p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mode',['normal','zero','all-empty','mixed'])
def test_native_activation_metadata_read_and_id_consumer(tmp_path,mode):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\n'
        'ALLOW_RESET=true\nANONYMIZED_TELEMETRY=false\n')
    (tmp_path/'bm25.yaml').write_text('k1: 1.5\nb: 0.75\n')
    first=prepare(tmp_path,'build',mode)
    # The live source disappears after activation; only its immutable snapshot is available.
    (tmp_path/'source').rename(tmp_path/'source-offline')
    before=snapshot(tmp_path/'storage');selected=(tmp_path/'active.json').read_bytes()
    result=launch(tmp_path,'read',mode)
    assert snapshot(tmp_path/'storage')==before and (tmp_path/'active.json').read_bytes()==selected
    assert result['listing']['active']==first['active']
    assert result['model_requests']==first['model_requests']==0 and result['pid']!=first['pid']
    assert len(result['listing']['documents'])==first['active']['version']['document_count']
    (tmp_path/'management.json').write_text(json.dumps(result))
    consumed=launch(tmp_path,'consume',mode)
    assert consumed['pid']!=result['pid'] and consumed['model_requests']==0
    assert consumed['chunk_count']==first['active']['version']['chunk_count']
