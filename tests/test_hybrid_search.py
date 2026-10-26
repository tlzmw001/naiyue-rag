"""One encoding, configured real branches, RRF arithmetic and whole-query failures."""
import copy
import json
import threading
from dataclasses import replace
import pytest
from naiyue_rag.core.errors import QueryJobError,StorageError,SettingsError
from naiyue_rag.core.trace_context import TraceContext,validate_trace_report
from test_query_preparation import job
from test_document_manager import prepared,second
from test_dense_retrieval import native_query
from test_query_encoding import QUERY,PRIVATE


def config(**changes):
    from naiyue_rag import HybridSettings
    return HybridSettings.from_dict(dict(dense_top_k=3,sparse_top_k=3,fusion_top_k=3,rrf_k=60,
        bm25_statistics_scope='global',parallel_retrieval=True)|changes)


def searcher(pipeline,**changes):
    from naiyue_rag import HybridSearch
    return HybridSearch(pipeline.manager,pipeline.query_encoder,config(**changes))


@pytest.mark.parametrize('change',[dict(dense_top_k=True),dict(sparse_top_k=0),dict(fusion_top_k=1.5),dict(rrf_k=0),
    dict(bm25_statistics_scope='auto'),dict(parallel_retrieval=1),dict(extra=3)])
def test_invalid_hybrid_config(change):
    with pytest.raises(SettingsError,match='invalid_hybrid_settings'):config(**change)


def test_config_yaml_is_consumed_by_actual_branches(job,native_query,tmp_path):
    from naiyue_rag import HybridSearch,load_hybrid_settings
    pipeline,*_=job;p=tmp_path/'hybrid.yaml'
    p.write_text('dense_top_k: 2\nsparse_top_k: 1\nfusion_top_k: 2\nrrf_k: 10\nbm25_statistics_scope: scope\nparallel_retrieval: false\n')
    result=HybridSearch(pipeline.manager,pipeline.query_encoder,load_hybrid_settings(p)).search(QUERY)
    assert len(result.dense_hits)==2 and len(result.sparse_hits)<=1 and len(result.hits)==2
    assert result.settings.rrf_k==10 and result.settings.bm25_statistics_scope=='scope'
    assert native_query[0][0]['n_results']==2
    for bad in ['dense_top_k: 2\ndense_top_k: 3','dense_top_k: &a 3\nsparse_top_k: *a']:
        p.write_text(bad)
        with pytest.raises(SettingsError):load_hybrid_settings(p)


def test_reference_rrf_formula_and_rank_provenance(job,native_query):
    from naiyue_rag import DenseResult,DenseHit,SparseResult,SparseHit,RRFFusion
    pipeline,*_=job;ready=pipeline.prepare(QUERY);bundle=pipeline.manager.bundles.load(ready.active.version.bundle_id)
    chunks=sorted(bundle.chunks,key=lambda c:c.id)[:3];a,b,c=chunks
    dense=DenseResult(ready,3,[DenseHit(i,ch,d,max(0.,1-d/2)) for i,(ch,d) in enumerate(zip(chunks,[.2,.4,.6]),1)])
    sparse=SparseResult(ready,3,'global',[SparseHit(1,b,4.),SparseHit(2,c,2.)])
    result=RRFFusion(60).fuse(dense,sparse,top_k=3)
    assert [h.chunk.id for h in result]==[b.id,c.id,a.id]
    assert [(h.dense_rank,h.sparse_rank) for h in result]==[(2,1),(3,2),(1,None)]
    assert result[0].score==1/62+1/61 and result[1].score==1/63+1/62 and result[2].score==1/61
    wrong=copy.deepcopy(sparse);wrong.hits[0].chunk.metadata['test_marker']=PRIVATE
    with pytest.raises(ValueError,match='query_invalid_request'):RRFFusion(60).fuse(dense,wrong,top_k=3)


@pytest.mark.parametrize('parallel',[True,False])
@pytest.mark.parametrize('mode',['global','scope'])
def test_hybrid_once_encoding_same_snapshot_and_trace(job,native_query,parallel,mode):
    from naiyue_rag import HybridResult
    pipeline,active,bundle,dense,sparse=job
    result=searcher(pipeline,parallel_retrieval=parallel,bm25_statistics_scope=mode).search(QUERY,expected_revision=1)
    assert len(dense.calls)==len(sparse.calls)==len(native_query[0])==1 and result.prepared.active==active
    assert len(result.hits)==3 and result.settings.bm25_statistics_scope==mode
    trace=result.trace_report;validate_trace_report(trace)
    assert trace['status']=='success' and trace['trace_id']!=result.prepared.trace_report['trace_id']
    assert [s['stage'] for s in trace['stages']]==['request','resources','embedding','dense','sparse','fusion']
    assert trace['stages'][3]['data']==dict(eligible_count=len(bundle.chunks),candidate_count=3)
    assert trace['stages'][4]['data']['candidate_count']==len(result.sparse_hits)
    assert QUERY not in json.dumps(trace) and 'dense_vector' not in json.dumps(trace)
    assert HybridResult.from_dict(json.loads(json.dumps(result.to_dict()))).to_dict()==result.to_dict()


def test_parallel_branch_start_is_proved_with_barrier(job,native_query,monkeypatch):
    from naiyue_rag import DenseRetriever,SparseRetriever
    pipeline,*_=job;barrier=threading.Barrier(2);threads=[]
    dense=DenseRetriever.retrieve;sparse=SparseRetriever.retrieve
    def d(self,*args,**kwargs):
        threads.append(threading.get_ident());barrier.wait(timeout=10);return dense(self,*args,**kwargs)
    def s(self,*args,**kwargs):
        threads.append(threading.get_ident());barrier.wait(timeout=10);return sparse(self,*args,**kwargs)
    monkeypatch.setattr(DenseRetriever,'retrieve',d);monkeypatch.setattr(SparseRetriever,'retrieve',s)
    assert searcher(pipeline).search(QUERY).hits and len(set(threads))==2


def test_explicit_empty_scope_still_runs_both_empty_branches(job,native_query):
    pipeline,active,_,dense,sparse=job
    result=searcher(pipeline).search(QUERY,scope_document_ids=[])
    assert result.prepared.active==active and result.hits==result.dense_hits==result.sparse_hits==[]
    assert dense.calls==sparse.calls==native_query[0]==[]
    assert result.trace_report['stages'][-1]['data']==dict(union_count=0,candidate_count=0)


@pytest.mark.parametrize('branch',['dense','sparse','both','fusion','trace','budget'])
def test_hybrid_errors_retain_stage_usage_and_never_degrade(job,native_query,monkeypatch,branch,caplog):
    from naiyue_rag import DenseRetriever,SparseRetriever,RRFFusion
    import naiyue_rag.query.hybrid_search as module
    pipeline,active,_,dense,sparse=job
    def fail_dense(*args,**kwargs):raise StorageError('chroma_read_failed')
    def fail_sparse(*args,**kwargs):raise StorageError('bm25_query_failed')
    if branch in ('dense','both'):monkeypatch.setattr(DenseRetriever,'retrieve',fail_dense)
    if branch in ('sparse','both'):monkeypatch.setattr(SparseRetriever,'retrieve',fail_sparse)
    if branch=='fusion':
        def fail(*args,**kwargs):raise RuntimeError(PRIVATE)
        monkeypatch.setattr(RRFFusion,'fuse',fail)
    if branch=='trace':
        original=TraceContext.record_stage
        def fail(self,stage,*args,**kwargs):
            if stage=='fusion':raise RuntimeError(PRIVATE)
            return original(self,stage,*args,**kwargs)
        monkeypatch.setattr(TraceContext,'record_stage',fail)
    if branch=='budget':
        def fail(*args,**kwargs):raise StorageError('bundle_limit_exceeded')
        monkeypatch.setattr(module,'_json_bytes',fail)
    with pytest.raises(QueryJobError) as caught:searcher(pipeline).search(QUERY)
    error=caught.value
    expected=('dense','chroma_read_failed') if branch in ('dense','both') else ('sparse','bm25_query_failed') if branch=='sparse' else \
        ('fusion','query_fusion_failed') if branch=='fusion' else ('fusion','query_trace_failed') if branch=='trace' else ('fusion','query_result_limit')
    assert (error.stage,error.code)==expected and error.active==active
    assert error.encoding_report.status=='success' and error.trace_report['status']=='error'
    assert len(dense.calls)==len(sparse.calls)==1 and not hasattr(error,'hits')
    assert PRIVATE not in caplog.text+str(error)+json.dumps(error.to_dict())
    if branch=='both':assert 'stage=sparse code=bm25_query_failed' in caplog.text


def test_hybrid_limits_reject_before_encoding(job,native_query):
    pipeline,_,_,dense,sparse=job
    with pytest.raises(QueryJobError,match='query_invalid_request'):searcher(pipeline,dense_top_k=10001).search(QUERY)
    assert dense.calls==sparse.calls==native_query[0]==[]


@pytest.mark.parametrize('fault',['extra','rrf_score','rank','source_rank','missing_hit','trace_count','mode'])
def test_hybrid_result_is_strict_and_defensively_copied(job,native_query,fault):
    from naiyue_rag import HybridResult
    pipeline,*_=job;result=searcher(pipeline).search(QUERY);raw=result.to_dict()
    if fault=='extra':raw['extra']=PRIVATE
    elif fault=='rrf_score':raw['hits'][0]['score']=.1234
    elif fault=='rank':raw['hits'][0]['rank']=True
    elif fault=='source_rank':raw['hits'][0]['dense_rank']=999
    elif fault=='missing_hit':raw['hits'].pop()
    elif fault=='trace_count':raw['trace_report']['stages'][-1]['data']['candidate_count']=999
    else:raw['settings']['bm25_statistics_scope']='auto'
    with pytest.raises(ValueError,match='query_invalid_request'):HybridResult.from_dict(raw)


def test_trace_accepts_explicit_eligible_count_without_inventing_ann_work():
    ctx=TraceContext();ctx.record_stage('dense',dict(eligible_count=7,candidate_count=2),elapsed_ms=4.)
    ctx.finish('success');validate_trace_report(ctx.to_dict())
    assert ctx.to_dict()['stages'][0]['data']==dict(eligible_count=7,candidate_count=2)


def test_preparation_failure_without_trace_keeps_original_stage_and_usage(job,native_query,monkeypatch):
    pipeline,*_=job;ready=pipeline.prepare(QUERY);app=searcher(pipeline)
    original=QueryJobError('embedding','query_embedding_failed',active=ready.active,encoding_report=ready.encoding.report)
    def fail(*args,**kwargs):raise original
    monkeypatch.setattr(app.pipeline,'prepare',fail)
    with pytest.raises(QueryJobError) as caught:app.search(QUERY)
    assert caught.value is original and caught.value.stage=='embedding'
    assert caught.value.encoding_report.to_dict()==ready.encoding.report.to_dict()
