"""Pinned Dense retrieval, native request projection and strict failure contracts."""
import copy
from dataclasses import replace
import json
import math
import pytest
from naiyue_rag.core.errors import StorageError,QueryJobError
from naiyue_rag.storage import ChromaStore,ChromaSettings,DocumentManager,BM25Settings
from test_chroma_index import FakeClient,setup_index
from test_query_preparation import job
from test_document_manager import prepared,second
from test_query_encoding import QUERY,PRIVATE,setup
from test_storage_bundle import storage_settings


@pytest.fixture
def native_query(monkeypatch):
    calls=[];fault={}
    def query(client,**args):
        calls.append(copy.deepcopy(args))
        if fault.get('io'):raise OSError(PRIVATE)
        scope=set(args['where']['document_id']['$in']);q=args['query_embeddings'][0]
        rows=client.data['rows'];pairs=[]
        for uid,(vec,text,meta) in rows.items():
            if meta['document_id'] in scope:
                distance=1-sum(a*b for a,b in zip(q,vec,strict=True))/(math.hypot(*q)*math.hypot(*vec))
                pairs.append((distance,uid))
        pairs=sorted(pairs)[:args['n_results']]
        raw=dict(ids=[[uid for _,uid in pairs]],distances=[[d for d,_ in pairs]],
            documents=[[rows[uid][1] for _,uid in pairs]],metadatas=[[copy.deepcopy(rows[uid][2]) for _,uid in pairs]])
        key=fault.get('shape')
        if key=='missing':raw.pop('distances')
        elif key=='outer':raw['ids'].append([])
        elif key=='short':raw['distances'][0].clear()
        elif key=='duplicate':raw['ids'][0][-1]=raw['ids'][0][0]
        elif key=='unknown':raw['ids'][0][0]='unit-'+'0'*64
        elif key=='nan':raw['distances'][0][0]=float('nan')
        elif key=='bool':raw['distances'][0][0]=True
        elif key=='text':raw['documents'][0][0]=PRIVATE
        elif key=='metadata':raw['metadatas'][0][0]['source_sha256']='0'*64
        elif key=='outside':
            uid=next(uid for uid,row in rows.items() if row[2]['document_id'] not in scope)
            raw['ids'][0][0]=uid
        elif key=='interrupt':raise KeyboardInterrupt()
        return raw
    monkeypatch.setattr(FakeClient,'query',query,raising=False)
    return calls,fault


def retriever(manager):
    from naiyue_rag import DenseRetriever
    return DenseRetriever(manager)


def test_store_query_projects_scope_and_complete_chunks(setup_index,native_query):
    writer,reader,uid,bundle,*_=setup_index;writer.build(uid)
    scope=[bundle.chunks[-1].source_ref]
    result=reader.query(uid,[1.,2.,3.],document_ids=scope,top_k=100)
    expected={c.id:c.to_dict() for c in bundle.chunks if c.source_ref in scope}
    assert {r['chunk'].id:r['chunk'].to_dict() for r in result}==expected
    calls,_=native_query
    assert len(calls)==1 and calls[0]['where']=={'document_id':{'$in':scope}}
    assert calls[0]['n_results']==len(expected) and calls[0]['query_embeddings']==[[1.,2.,3.]]
    assert calls[0]['include']==['documents','metadatas','distances']
    assert all(abs(r['distance'])<1e-6 and abs(r['score']-1)<1e-6 for r in result)
    assert [r['chunk'].id for r in result]==sorted(expected)


@pytest.mark.parametrize('vector,k,scope',[
    ([1.,2.,3.],0,None),([1.,2.,3.],True,None),([1.,2.,3.],10001,None),
    ([1.,2.],1,None),([0.,0.,0.],1,None),([1.,float('nan'),3.],1,None),
    ([True,2.,3.],1,None),([1e300,2.,3.],1,None),((1.,2.,3.),1,None),
    ([1.,2.,3.],1,['doc-'+'0'*64]),([1.,2.,3.],1,'bad'),
])
def test_invalid_store_input_does_not_query_sdk(setup_index,native_query,vector,k,scope):
    writer,reader,uid,bundle,*_=setup_index;writer.build(uid)
    scope=[bundle.documents[0].id] if scope is None else scope
    with pytest.raises(StorageError,match='chroma_invalid_request'):reader.query(uid,vector,document_ids=scope,top_k=k)
    assert native_query[0]==[]


@pytest.mark.parametrize('fault',['missing','outer','short','duplicate','unknown','nan','bool','text','metadata','outside'])
def test_bad_native_result_fails_whole_query(setup_index,native_query,fault,caplog):
    writer,reader,uid,bundle,*_=setup_index;writer.build(uid)
    calls,flags=native_query;flags['shape']=fault
    scope=sorted({c.source_ref for c in bundle.chunks})
    if fault=='outside':scope=scope[:1]
    with pytest.raises(StorageError,match='chroma_integrity_failed'):reader.query(uid,[1.,2.,3.],document_ids=scope,top_k=10)
    assert PRIVATE not in caplog.text


def test_ready_retrieval_uses_prepared_vector_once_and_never_reads_catalog(job,native_query,monkeypatch):
    pipeline,active,bundle,dense,sparse=job;ready=pipeline.prepare(QUERY)
    monkeypatch.setattr(pipeline.manager.catalog,'read',lambda:pytest.fail('must not select latest'))
    result=retriever(pipeline.manager).retrieve(ready,top_k=3)
    assert result.prepared.to_dict()==ready.to_dict() and len(result.hits)==3
    assert len(dense.calls)==len(sparse.calls)==len(native_query[0])==1
    assert [h.rank for h in result.hits]==[1,2,3]
    assert all(h.chunk.id in ready.chunk_ids and h.chunk.source_ref in ready.document_ids for h in result.hits)
    assert result.score_kind=='chroma_cosine_affine_v1'
    cls=type(result);assert cls.from_dict(json.loads(json.dumps(result.to_dict()))).to_dict()==result.to_dict()
    raw=result.to_dict();raw['hits'][0]['chunk']['text']=PRIVATE
    assert PRIVATE not in json.dumps(result.to_dict())


@pytest.mark.parametrize('k',[0,True,1.2,10001])
def test_bad_retrieval_limit_retains_known_encoding(job,native_query,k):
    pipeline,*_=job;ready=pipeline.prepare(QUERY)
    with pytest.raises(QueryJobError) as caught:retriever(pipeline.manager).retrieve(ready,top_k=k)
    assert caught.value.stage=='dense' and caught.value.code=='query_invalid_request'
    assert caught.value.encoding_report.to_dict()==ready.encoding.report.to_dict()
    assert caught.value.active==ready.active and native_query[0]==[]


@pytest.mark.parametrize('fault',['io','close','scope','chunk','budget','version'])
def test_dense_errors_keep_version_usage_and_safe_code(job,native_query,monkeypatch,fault,caplog):
    import naiyue_rag.query.dense_retriever as module
    pipeline,active,*_=job;ready=pipeline.prepare(QUERY);calls,flags=native_query
    expected='chroma_read_failed'
    if fault=='io':flags['io']=True
    elif fault=='close':
        def fail(self):raise OSError(PRIVATE)
        monkeypatch.setattr(FakeClient,'close',fail);expected='chroma_close_failed'
    elif fault=='scope':ready=replace(ready,document_ids=ready.document_ids[:-1]);expected='query_invalid_scope'
    elif fault=='chunk':ready=replace(ready,chunk_ids=ready.chunk_ids[:-1]);expected='query_invalid_scope'
    elif fault=='budget':
        def fail(*args,**kwargs):raise StorageError('bundle_limit_exceeded')
        monkeypatch.setattr(module,'_json_bytes',fail);expected='query_result_limit'
    elif fault=='version':
        from naiyue_rag.storage.bundle_store import _digest,_json_bytes
        from naiyue_rag.storage import IndexVersion,ActiveVersion
        raw=ready.active.version.to_dict();raw.pop('version_id');raw['vector_index_id']='0'*64
        raw['version_id']=_digest(_json_bytes(raw,pipeline.storage_settings.max_manifest_bytes,newline=False))
        trace=copy.deepcopy(ready.trace_report);trace['stages'][1]['data']['index_id']=raw['version_id']
        ready=replace(ready,active=ActiveVersion(active.revision,IndexVersion.from_dict(raw)),trace_report=trace)
        expected='catalog_identity_mismatch'
    with pytest.raises(QueryJobError) as caught:retriever(pipeline.manager).retrieve(ready,top_k=2)
    error=caught.value
    assert error.stage=='dense' and error.code==expected and error.active==ready.active
    assert error.encoding_report.to_dict()==ready.encoding.report.to_dict()
    assert PRIVATE not in str(error)+repr(error)+json.dumps(error.to_dict())+caplog.text
    assert not hasattr(error,'hits')


def test_pinned_result_ignores_new_active_version(job,prepared,tmp_path,native_query):
    pipeline,active,*_=job;ready=pipeline.prepare(QUERY)
    manager,uid=second(prepared,tmp_path);new=manager.activate(uid,expected_revision=1).active
    result=retriever(manager).retrieve(ready,top_k=2)
    assert new.revision==2 and result.prepared.active==active


def test_explicit_empty_scope_returns_no_hits_and_still_audits(job,native_query,monkeypatch):
    pipeline,*_=job;ready=pipeline.prepare(QUERY,scope_document_ids=[])
    result=retriever(pipeline.manager).retrieve(ready,top_k=2)
    assert result.hits==[] and native_query[0]==[]
    def fail(*args,**kwargs):raise StorageError('chroma_index_incomplete')
    monkeypatch.setattr(ChromaStore,'audit',fail)
    with pytest.raises(QueryJobError,match='chroma_index_incomplete'):retriever(pipeline.manager).retrieve(ready,top_k=2)


def test_unactivated_does_not_initialize_sdk(tmp_path,native_query):
    from naiyue_rag import QueryPipeline
    encoder,*_=setup();manager=DocumentManager(storage_settings(tmp_path),ChromaSettings('knowledge_hub',2),BM25Settings(1.5,.75),project_root=tmp_path)
    ready=QueryPipeline(manager,encoder).prepare(QUERY)
    result=retriever(manager).retrieve(ready,top_k=2)
    assert result.hits==[] and native_query[0]==[] and result.prepared.active is None


def test_control_interrupt_propagates(job,native_query):
    pipeline,*_=job;ready=pipeline.prepare(QUERY);native_query[1]['shape']='interrupt'
    with pytest.raises(KeyboardInterrupt):retriever(pipeline.manager).retrieve(ready,top_k=2)


@pytest.mark.parametrize('fault',['extra','rank','score','distance','duplicate','outside','reorder','top_k'])
def test_dense_result_contract_rejects_mutation(job,native_query,fault):
    pipeline,*_=job;result=retriever(pipeline.manager).retrieve(pipeline.prepare(QUERY),top_k=3)
    raw=result.to_dict()
    if fault=='extra':raw['extra']=PRIVATE
    elif fault=='rank':raw['hits'][0]['rank']=True
    elif fault=='score':raw['hits'][0]['score']=0.1234
    elif fault=='distance':raw['hits'][0]['distance']=float('inf')
    elif fault=='duplicate':raw['hits'][1]=copy.deepcopy(raw['hits'][0])
    elif fault=='outside':raw['hits'][0]['chunk']['id']='unit-'+'0'*64
    elif fault=='reorder':raw['hits'].reverse()
    else:raw['top_k']=0
    with pytest.raises(ValueError,match='query_invalid_request'):type(result).from_dict(raw)
