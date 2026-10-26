"""Configured BM25 statistics, fixed sources and explicit sparse failures."""
from dataclasses import replace
import copy
import json
import math
import numpy as np
import pytest
from naiyue_rag.core.errors import SettingsError,StorageError,QueryJobError
from naiyue_rag.storage import BM25Store,BM25Settings,BM25Indexer
from test_query_preparation import job
from test_document_manager import prepared,second
from test_query_encoding import QUERY,PRIVATE
from test_bm25_store import save_bundle,index_folder


def settings(top_k=20,statistics_scope='global'):
    from naiyue_rag import SparseQuerySettings
    return SparseQuerySettings(top_k,statistics_scope)


@pytest.mark.parametrize('k,mode',[(0,'global'),(True,'global'),(1.2,'global'),(2,'auto'),(2,None)])
def test_invalid_sparse_query_settings(k,mode):
    with pytest.raises(SettingsError,match='invalid_sparse_query_settings'):settings(k,mode)


def test_strict_yaml_roundtrip_and_actual_mode_switch(job,tmp_path):
    from naiyue_rag import load_sparse_query_settings,SparseRetriever
    pipeline,*_=job;ready=pipeline.prepare(QUERY);path=tmp_path/'query.yaml'
    for mode in ('global','scope'):
        path.write_text(f'top_k: 2\nstatistics_scope: {mode}\n')
        cfg=load_sparse_query_settings(path);result=SparseRetriever(pipeline.manager,cfg).retrieve(ready)
        assert result.statistics_scope==mode and result.top_k==2
        assert result.score_kind==f'bm25s_lucene_{mode}_v1'
        assert type(cfg).from_dict(cfg.to_dict())==cfg
    for raw in ('top_k: 2\ntop_k: 3\nstatistics_scope: global','top_k: 2\nstatistics_scope: scope\nextra: true',
                'top_k: 2','top_k: &a 2\nstatistics_scope: *a'):
        path.write_text(raw)
        with pytest.raises(SettingsError):load_sparse_query_settings(path)


def hand_scores(records,terms,k1=1.5,b=.75):
    N=len(records);avg=sum(r.doc_length for r in records)/N if N else 0
    out=[]
    for row in records:
        value=0.
        for term in terms:
            tf=row.term_frequencies.get(term,0);df=sum(term in r.term_frequencies for r in records)
            if tf:value+=math.log(1+(N-df+.5)/(df+.5))*tf/(tf+k1*(1-b+b*row.doc_length/avg))
        out.append(value)
    return out


@pytest.mark.parametrize('mode',['global','scope'])
def test_native_scores_match_hand_formula_and_scope_before_top_k(tmp_path,mode):
    cfg,uid,bundle=save_bundle(tmp_path);store=BM25Indexer(cfg,BM25Settings(1.5,.75));store.build(uid)
    docs=sorted({r.input.source_document_id for r in bundle.encoding_result.records});scope=docs[1:]
    records=bundle.encoding_result.records;chosen=[r for r in records if r.input.source_document_id in scope]
    population=records if mode=='global' else chosen;terms=['开关','1']
    values=hand_scores([r.sparse for r in population],terms)
    scores={r.input.item_id:v for r,v in zip(population,values,strict=True) if r.input.source_document_id in scope and v>0}
    result=store.query(uid,terms,document_ids=scope,top_k=100,statistics_scope=mode)
    assert [h['chunk'].id for h in result]==sorted(scores,key=lambda uid:(-scores[uid],uid))
    assert all(math.isclose(h['score'],scores[h['chunk'].id],rel_tol=1e-12,abs_tol=1e-15) for h in result)
    expected={c.id:c.to_dict() for c in bundle.chunks}
    assert all(h['chunk'].to_dict()==expected[h['chunk'].id] for h in result)
    assert len(store.query(uid,terms,document_ids=scope,top_k=1,statistics_scope=mode))==1
    folder=index_folder(cfg);before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in folder.iterdir()}
    store.query(uid,terms,document_ids=scope,top_k=10,statistics_scope=mode)
    assert before=={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in folder.iterdir()}


@pytest.mark.parametrize('mode',['global','scope'])
@pytest.mark.parametrize('terms,scope',[([],None),(['NOT_IN_VOCAB'],None),(['开关'],[])])
def test_sparse_empty_terms_unknown_terms_and_empty_scope(tmp_path,mode,terms,scope):
    cfg,uid,bundle=save_bundle(tmp_path);store=BM25Indexer(cfg,BM25Settings(1.5,.75));store.build(uid)
    scope=[d.id for d in bundle.documents] if scope is None else scope
    assert store.query(uid,terms,document_ids=scope,top_k=10,statistics_scope=mode)==[]
    (index_folder(cfg)/'ready.json').write_text('{}')
    with pytest.raises(StorageError):store.query(uid,terms,document_ids=scope,top_k=10,statistics_scope=mode)


@pytest.mark.parametrize('terms,scope,k,mode',[
    ('开关',None,2,'global'),(['开关','开关'],None,2,'scope'),([''],None,2,'global'),
    ([True],None,2,'global'),(['\ud800'],None,2,'global'),(['开关'],['doc-'+'0'*64],2,'global'),
    (['开关'],None,True,'scope'),(['开关'],None,10001,'scope'),(['开关'],None,2,'auto')])
def test_bad_store_arguments(tmp_path,terms,scope,k,mode):
    cfg,uid,bundle=save_bundle(tmp_path);store=BM25Indexer(cfg,BM25Settings(1.5,.75));store.build(uid)
    scope=[d.id for d in bundle.documents] if scope is None else scope
    with pytest.raises(StorageError,match='bm25_invalid_request'):store.query(uid,terms,document_ids=scope,top_k=k,statistics_scope=mode)


@pytest.mark.parametrize('mode',['global','scope'])
def test_retriever_pins_scope_and_keeps_encoding(job,monkeypatch,mode):
    from naiyue_rag import SparseRetriever,SparseResult
    pipeline,active,bundle,dense,sparse=job;ready=pipeline.prepare(QUERY)
    monkeypatch.setattr(pipeline.manager.catalog,'read',lambda:pytest.fail('no latest lookup'))
    result=SparseRetriever(pipeline.manager,settings(3,mode)).retrieve(ready)
    assert result.prepared.to_dict()==ready.to_dict() and len(dense.calls)==len(sparse.calls)==1
    assert all(h.chunk.id in ready.chunk_ids for h in result.hits) and len(result.hits)<=3
    raw=result.to_dict();assert SparseResult.from_dict(json.loads(json.dumps(raw))).to_dict()==raw
    raw['hits'][0]['chunk']['metadata']['case_id']=PRIVATE
    assert PRIVATE not in json.dumps(result.to_dict())


@pytest.mark.parametrize('mode',['global','scope'])
@pytest.mark.parametrize('fault',['io','nan','negative','shape','interrupt'])
def test_native_score_faults_are_not_empty_results(job,monkeypatch,mode,fault,caplog):
    import bm25s
    from naiyue_rag import SparseRetriever
    pipeline,*_=job;ready=pipeline.prepare(QUERY)
    def bad(self,tokens,**kwargs):
        if fault=='io':raise OSError(PRIVATE)
        if fault=='interrupt':raise KeyboardInterrupt()
        n=self.scores['num_docs'];values=np.zeros(n,dtype='float64')
        if fault=='shape':return values[:-1]
        values[0]=float('nan') if fault=='nan' else -1
        return values
    monkeypatch.setattr(bm25s.BM25,'get_scores',bad)
    if fault=='interrupt':
        with pytest.raises(KeyboardInterrupt):SparseRetriever(pipeline.manager,settings(2,mode)).retrieve(ready)
        return
    with pytest.raises(QueryJobError) as caught:SparseRetriever(pipeline.manager,settings(2,mode)).retrieve(ready)
    error=caught.value;assert error.stage=='sparse' and error.active==ready.active
    assert error.encoding_report.to_dict()==ready.encoding.report.to_dict()
    assert error.code==('bm25_query_failed' if fault=='io' else 'bm25_integrity_failed')
    assert PRIVATE not in caplog.text+str(error)+json.dumps(error.to_dict())


@pytest.mark.parametrize('fault',['extra','rank','score','mode','duplicate','outside','top_k','order'])
def test_sparse_result_strict_contract(job,fault):
    from naiyue_rag import SparseRetriever,SparseResult
    pipeline,*_=job;result=SparseRetriever(pipeline.manager,settings(10)).retrieve(pipeline.prepare(QUERY));raw=result.to_dict()
    assert len(raw['hits'])>=2
    if fault=='extra':raw['extra']=PRIVATE
    elif fault=='rank':raw['hits'][0]['rank']=True
    elif fault=='score':raw['hits'][0]['score']=0.
    elif fault=='mode':raw['statistics_scope']='auto'
    elif fault=='duplicate':raw['hits'][1]=copy.deepcopy(raw['hits'][0])
    elif fault=='outside':raw['hits'][0]['chunk']['id']='unit-'+'0'*64
    elif fault=='top_k':raw['top_k']=0
    else:raw['hits'].reverse()
    with pytest.raises(ValueError,match='query_invalid_request'):SparseResult.from_dict(raw)


@pytest.mark.parametrize('fault',['scope','budget','too_many'])
def test_sparse_pipeline_errors_keep_usage(job,monkeypatch,fault):
    from naiyue_rag import SparseRetriever
    import naiyue_rag.query.sparse_retriever as module
    pipeline,*_=job;ready=pipeline.prepare(QUERY);cfg=settings(3)
    code='query_invalid_scope'
    if fault=='scope':ready=replace(ready,chunk_ids=ready.chunk_ids[:-1])
    elif fault=='budget':
        def fail(*args,**kwargs):raise StorageError('bundle_limit_exceeded')
        monkeypatch.setattr(module,'_json_bytes',fail);code='query_result_limit'
    else:cfg=settings(10001);code='query_invalid_request'
    with pytest.raises(QueryJobError) as caught:SparseRetriever(pipeline.manager,cfg).retrieve(ready)
    assert caught.value.code==code and caught.value.stage=='sparse'
    assert caught.value.active==ready.active and caught.value.encoding_report.to_dict()==ready.encoding.report.to_dict()
