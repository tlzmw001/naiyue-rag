"""A pinned, source-bound query preparation, including empty and failure branches."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import pytest
from naiyue_rag import QueryEncoder
from naiyue_rag.core.errors import EncodingError,StorageError,EmbeddingExecutionError
from naiyue_rag.encoding.execution_report import new_report
from naiyue_rag.storage import DocumentManager,ChromaSettings,BM25Settings,ChromaStore
from test_document_manager import prepared,second
from test_query_encoding import setup,QUERY,PRIVATE
from test_storage_bundle import storage_settings
from test_encoding_settings import config

MISSING='doc-'+'0'*64


@pytest.fixture
def job(prepared):
    from naiyue_rag import QueryPipeline
    manager,uid,bundle,*_=prepared;active=manager.activate(uid,expected_revision=0).active
    encoder,dense,sparse=setup(bundle.encoding_settings)
    return QueryPipeline(manager,encoder),active,bundle,dense,sparse


def error_type():
    from naiyue_rag.core.errors import QueryJobError
    return QueryJobError


def assert_error(caught,stage,code,active=None,report=False):
    error=caught.value
    assert error.stage==stage and error.code==code and error.active==active
    assert (error.encoding_report is not None)==report
    assert error.trace_report is not None and error.trace_report['status']=='error'
    assert error.trace_report['error']['stage']==stage
    assert PRIVATE not in str(error)+repr(error)+json.dumps(error.to_dict())
    assert not hasattr(error,'dense_vector') and not hasattr(error,'query_terms')
    assert type(error).from_dict(json.loads(json.dumps(error.to_dict()))).to_dict()==error.to_dict()


def test_ready_scope_projection_encoding_and_trace(job,monkeypatch):
    pipeline,active,bundle,dense,sparse=job;reads=[];read=pipeline.manager.catalog.read
    def counted():reads.append(1);return read()
    monkeypatch.setattr(pipeline.manager.catalog,'read',counted)
    selected=[d.id for d in bundle.documents if d.metadata['source_path'].startswith('L2_')]
    result=pipeline.prepare(QUERY,scope_document_ids=list(reversed(selected)),expected_revision=1)
    assert result.status=='ready' and result.active==active and reads==[1]
    assert result.document_ids==sorted(selected)
    assert result.chunk_ids==sorted(c.id for c in bundle.chunks if c.source_ref in selected)
    assert len(dense.calls)==len(sparse.calls)==1 and result.encoding.input.retrieval_text==QUERY
    assert result.encoding.input.query_sha256==result.query_sha256
    trace=result.trace_report
    assert [r['stage'] for r in trace['stages']]==['request','resources','embedding']
    assert trace['status']=='success' and trace['stages'][1]['data']['index_id']==active.version.version_id
    assert trace['stages'][1]['data']['corpus_id']==active.version.source_fingerprint
    assert trace['stages'][2]['data']['adapter_calls']==1 and trace['stages'][2]['data']['usage']['total_tokens']==7
    assert QUERY not in json.dumps(trace) and 'dense_vector' not in json.dumps(trace)
    assert not hasattr(result,'candidates') and not hasattr(result,'results')


def test_none_scope_exclusions_and_explicit_empty(job):
    pipeline,active,bundle,dense,_=job;allids=sorted(d.id for d in bundle.documents)
    result=pipeline.prepare(QUERY,exclude_document_ids=[allids[0]])
    assert result.document_ids==allids[1:]
    before=len(dense.calls)
    for args in ({'scope_document_ids':[]},{'exclude_document_ids':allids},
                 {'scope_document_ids':[allids[0]],'exclude_document_ids':[allids[0]]}):
        empty=pipeline.prepare(QUERY,**args)
        assert empty.status=='empty_scope' and empty.active==active and empty.document_ids==empty.chunk_ids==[]
        assert empty.encoding is None and len(dense.calls)==before
        assert [s['stage'] for s in empty.trace_report['stages']]==['request','resources']


@pytest.mark.parametrize('args',[{'scope_document_ids':[MISSING]},{'exclude_document_ids':[MISSING]}])
def test_unknown_ids_reject_before_audit_or_encoding(job,monkeypatch,args):
    pipeline,active,_,dense,_=job
    monkeypatch.setattr(pipeline.manager,'_audit',lambda *args:pytest.fail('unknown scope must not start SDK'))
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY,**args)
    assert_error(caught,'resources','query_invalid_scope',active)
    assert dense.calls==[]


@pytest.mark.parametrize('query,args',[('',{}),(QUERY,{'scope_document_ids':[MISSING,MISSING]}),
    (QUERY,{'expected_revision':True})])
def test_bad_request_never_reads_catalog(job,monkeypatch,query,args):
    pipeline,_,_,dense,_=job
    monkeypatch.setattr(pipeline.manager.catalog,'read',lambda:pytest.fail('invalid request before IO'))
    with pytest.raises(error_type()) as caught:pipeline.prepare(query,**args)
    assert caught.value.stage=='request' and dense.calls==[]


def test_stale_revision_rejects_before_audit_and_encoding(job):
    pipeline,_,_,dense,_=job
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY,expected_revision=0)
    assert_error(caught,'resources','catalog_revision_conflict')
    assert dense.calls==[]


@pytest.mark.parametrize('scope',[None,[]])
def test_unactivated_does_not_create_storage(tmp_path,monkeypatch,scope):
    from naiyue_rag import QueryPipeline
    manager=DocumentManager(storage_settings(tmp_path),ChromaSettings('knowledge_hub',2),BM25Settings(1.5,.75),project_root=tmp_path)
    encoder,dense,_=setup();pipeline=QueryPipeline(manager,encoder)
    monkeypatch.setattr(manager,'_audit',lambda *args:pytest.fail('unactivated must not open SDK'))
    result=pipeline.prepare(QUERY,scope_document_ids=scope,expected_revision=0)
    assert result.status=='unactivated' and result.active is None and result.document_ids==result.chunk_ids==[]
    assert result.encoding is None and dense.calls==[] and not Path(manager.settings.storage_root).exists()
    assert [s['stage'] for s in result.trace_report['stages']]==['request']
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY,scope_document_ids=[MISSING])
    assert_error(caught,'resources','query_invalid_scope')


@pytest.mark.parametrize('profile',['model','representation','tokenizer','dimensions'])
def test_encoding_profile_must_match_active(job,profile):
    from naiyue_rag import QueryPipeline
    pipeline,active,bundle,_,_=job
    if profile=='model':cfg=config(embedding={'model_revision':'new'})
    elif profile=='representation':cfg=config(representation={'query_prefix':'changed: '})
    elif profile=='dimensions':cfg=config(embedding={'expected_dimensions':4})
    else:cfg=bundle.encoding_settings
    encoder,dense,sparse=setup(cfg)
    if profile=='tokenizer':encoder.tokenizer_id=sparse.tokenizer_id='b'*64
    candidate=QueryPipeline(pipeline.manager,encoder)
    with pytest.raises(error_type()) as caught:candidate.prepare(QUERY)
    assert_error(caught,'resources','query_identity_mismatch',active)
    assert dense.calls==[]


def test_runtime_change_and_manager_defaults_do_not_rebind_indexes(job):
    from naiyue_rag import QueryPipeline
    pipeline,active,bundle,*_=job;manager=pipeline.manager
    changed=DocumentManager(manager.settings,ChromaSettings('other_collection',1),BM25Settings(1.2,0),project_root=manager.project_root)
    encoder,_,_=setup(config(runtime={'batch_size':1}))
    result=QueryPipeline(changed,encoder).prepare(QUERY)
    assert result.active==active and result.encoding.report.status=='success'


@pytest.mark.parametrize('component',['encoder','dense','sparse'])
def test_components_cannot_be_replaced_in_place(job,component):
    pipeline,*_=job;encoder,_,_=setup()
    if component=='encoder':pipeline.query_encoder=encoder
    else:setattr(pipeline.query_encoder,component+'_encoder',getattr(encoder,component+'_encoder'))
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY)
    assert caught.value.stage=='request'


@pytest.mark.parametrize('kind',['bundle','chroma','bm25'])
@pytest.mark.parametrize('scope',[None,[]])
def test_broken_snapshot_is_not_empty_result(job,kind,scope):
    pipeline,active,_,dense,_=job;version=active.version;root=pipeline.manager.catalog.path.parent
    namespace,uid,file=('artifacts',version.bundle_id,'chunks.json') if kind=='bundle' else \
        ('vectors',version.vector_index_id,'ready.json') if kind=='chroma' else ('bm25',version.bm25_index_id,'ready.json')
    (root/namespace/uid/file).write_text('{}')
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY,scope_document_ids=scope)
    assert caught.value.stage=='resources' and dense.calls==[]
    assert pipeline.manager.catalog.read()==active


def test_actual_activation_during_encoding_does_not_change_selected_snapshot(job,prepared,tmp_path):
    pipeline,active,bundle,dense,_=job;rival,uid=second(prepared,tmp_path)
    won=[]
    dense.hook=lambda batch:won.append(rival.activate(uid,expected_revision=1).active)
    result=pipeline.prepare(QUERY,expected_revision=1)
    assert result.active==active and result.document_ids==sorted(d.id for d in bundle.documents)
    assert pipeline.manager.catalog.read()==won[0] and won[0].revision==2 and len(dense.calls)==1


@pytest.mark.parametrize('fault',['select','audit','dense','sparse','pairing'])
def test_failures_keep_primary_stage_and_actual_usage(job,monkeypatch,caplog,fault):
    pipeline,active,_,dense,sparse=job
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    if fault=='select':monkeypatch.setattr(pipeline.manager,'_document_bundle',fail)
    elif fault=='audit':monkeypatch.setattr(pipeline.manager,'_audit',fail)
    elif fault=='dense':
        def dense_fail(batch):
            report=new_report();report.update(attempted_requests=1,error_code='embedding_connection_failed')
            raise EmbeddingExecutionError('embedding_connection_failed',report)
        dense.hook=dense_fail
    elif fault=='sparse':sparse.hook=fail
    else:monkeypatch.setattr(sparse,'encode_batch',lambda batch:[])
    stage='resources' if fault in ('select','audit') else 'embedding'
    code='query_resources_failed' if fault in ('select','audit') else 'embedding_connection_failed' if fault=='dense' else \
        'encoding_pairing_failed' if fault=='pairing' else 'encoding_stage_failed'
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY)
    assert_error(caught,stage,code,None if fault=='select' else active,report=stage=='embedding')
    if stage=='embedding':
        report=caught.value.encoding_report
        assert report.status=='failed' and report.requests['attempted_requests']==1
        assert report.usage['total_tokens']==(None if fault=='dense' else 7)
    assert PRIVATE not in caplog.text and pipeline.manager.catalog.read()==active


@pytest.mark.parametrize('fault',['wrong-query','wrong-profile','result-contract','serialize'])
def test_post_encoding_failure_keeps_successful_encoding_report(job,monkeypatch,fault):
    import naiyue_rag.query.pipeline as module
    pipeline,active,_,_,_=job;encode=pipeline.query_encoder.encode
    if fault in ('wrong-query','wrong-profile'):
        def changed(query):
            result=encode('different query' if fault=='wrong-query' else query)
            if fault=='wrong-profile':result.tokenizer_id=result.sparse.tokenizer_id='c'*64
            return result
        monkeypatch.setattr(pipeline.query_encoder,'encode',changed)
    else:
        def fail(*args,**kwargs):raise OSError(PRIVATE)
        monkeypatch.setattr(module,'PreparedQuery' if fault=='result-contract' else '_json_bytes',fail)
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY)
    assert_error(caught,'embedding','query_identity_mismatch' if fault in ('wrong-query','wrong-profile') else 'query_embedding_failed',active,True)
    assert caught.value.encoding_report.status=='success'


@pytest.mark.parametrize('stage',['request','resources','embedding'])
def test_trace_record_failure_is_explicit_and_retains_known_report(job,monkeypatch,stage):
    import naiyue_rag.query.pipeline as module
    pipeline,active,_,_,_=job;record=module.TraceContext.record_stage
    def fail(self,name,data,**kwargs):
        if name==stage:raise OSError(PRIVATE)
        return record(self,name,data,**kwargs)
    monkeypatch.setattr(module.TraceContext,'record_stage',fail)
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY)
    assert_error(caught,stage,'query_trace_failed',None if stage=='request' else active,stage=='embedding')


def test_trace_failure_cannot_replace_primary_error(job,monkeypatch,caplog):
    import naiyue_rag.query.pipeline as module
    pipeline,active,_,_,sparse=job
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    sparse.hook=fail;monkeypatch.setattr(module.TraceContext,'finish',fail)
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY)
    error=caught.value
    assert error.stage=='embedding' and error.code=='encoding_stage_failed' and error.active==active
    assert error.encoding_report.status=='failed' and error.trace_report is None
    assert 'query_trace_failed' in caplog.text and PRIVATE not in caplog.text


def test_trace_constructor_failure_is_explicit(job,monkeypatch):
    import naiyue_rag.query.pipeline as module
    pipeline,_,_,dense,_=job
    def fail(*args):raise OSError(PRIVATE)
    monkeypatch.setattr(module,'TraceContext',fail)
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY)
    assert caught.value.code=='query_trace_failed' and caught.value.trace_report is None and dense.calls==[]


def test_empty_sparse_terms_and_unknown_usage_remain_valid(job):
    pipeline,_,_,dense,sparse=job;sparse.empty=True;dense.usage=None
    result=pipeline.prepare(QUERY)
    assert result.status=='ready' and result.encoding.query_terms==[]
    assert result.encoding.report.usage['total_tokens'] is None
    assert result.trace_report['stages'][-1]['data']['usage'] is None


def test_preparation_needs_no_source_markdown(job,tmp_path):
    pipeline,active,_,_,_=job
    (tmp_path/'source').rename(tmp_path/'source-offline')
    result=pipeline.prepare(QUERY)
    assert result.active==active and result.status=='ready'


def test_control_interrupt_propagates(job):
    pipeline,active,_,dense,_=job
    def stop(batch):raise KeyboardInterrupt()
    dense.hook=stop
    with pytest.raises(KeyboardInterrupt):pipeline.prepare(QUERY)
    assert pipeline.manager.catalog.read()==active


def test_prepared_result_roundtrip_and_copy(job):
    from naiyue_rag import PreparedQuery
    pipeline,_,_,_,_=job;result=pipeline.prepare(QUERY);raw=result.to_dict()
    assert set(raw)=={'status','active','query_sha256','document_ids','chunk_ids','encoding','trace_report'}
    assert PreparedQuery.from_dict(json.loads(json.dumps(raw))).to_dict()==raw
    raw['encoding']['dense_vector'].clear();raw['chunk_ids'].clear();raw['trace_report']['stages'].clear()
    assert result.encoding.dense_vector and result.chunk_ids and result.trace_report['stages']
    assert QUERY not in repr(result) and 'dense_vector' not in repr(result)


@pytest.mark.parametrize('fault',['extra','missing','status','active','hash','doc-id','chunk-id','duplicate',
    'order','doc-count','chunk-count','ready-no-encoding','query-binding','profile','trace-error','trace-resource',
    'trace-usage','empty-with-encoding','empty-has-chunks','unactivated-with-active','container'])
def test_invalid_prepared_queries_rejected(job,fault):
    from naiyue_rag import PreparedQuery
    pipeline,_,_,_,_=job;raw=pipeline.prepare(QUERY).to_dict()
    if fault=='extra':raw['secret']=PRIVATE
    elif fault=='missing':raw.pop('status')
    elif fault=='status':raw['status']='retrieved'
    elif fault=='active':raw['active']=None
    elif fault=='hash':raw['query_sha256']='0'*64
    elif fault=='doc-id':raw['document_ids'][0]='../source'
    elif fault=='chunk-id':raw['chunk_ids'][0]='doc-'+'0'*64
    elif fault=='duplicate':raw['chunk_ids'].append(raw['chunk_ids'][0]);raw['chunk_ids'].sort()
    elif fault=='order':raw['chunk_ids'].reverse()
    elif fault=='doc-count':raw['document_ids']=sorted('doc-'+f'{n:064x}' for n in range(4))
    elif fault=='chunk-count':raw['chunk_ids']=sorted('unit-'+f'{n:064x}' for n in range(raw['active']['version']['chunk_count']+1))
    elif fault=='ready-no-encoding':raw['encoding']=None
    elif fault=='query-binding':raw['query_sha256']='a'*64
    elif fault=='profile':raw['encoding']['tokenizer_id']=raw['encoding']['sparse']['tokenizer_id']='b'*64
    elif fault=='trace-error':raw['trace_report'].update(status='error',error=dict(stage='embedding',code='embedding_failed'))
    elif fault=='trace-resource':raw['trace_report']['stages'][1]['data']['index_id']='0'*64
    elif fault=='trace-usage':raw['trace_report']['stages'][2]['data']['adapter_calls']=0
    elif fault=='empty-with-encoding':raw.update(status='empty_scope',document_ids=[],chunk_ids=[])
    elif fault=='empty-has-chunks':raw.update(status='empty_index',encoding=None)
    elif fault=='unactivated-with-active':raw.update(status='unactivated',document_ids=[],chunk_ids=[],encoding=None)
    else:raw=[]
    with pytest.raises(error_type()):PreparedQuery.from_dict(raw)


@pytest.mark.parametrize('blank',[False,True])
def test_active_empty_library_or_blank_document_is_not_unactivated(job,tmp_path,blank):
    from naiyue_rag import QueryPipeline
    from test_ingestion_pipeline import job_for
    pipeline,*_=job;root=tmp_path/'empty-job';(root/'source').mkdir(parents=True)
    if blank:(root/'source/blank.md').write_text('')
    ingestion,_,_=job_for(root);active=ingestion.run(expected_revision=0).active
    encoder,dense,_=setup();result=QueryPipeline(ingestion.manager,encoder).prepare(QUERY)
    assert result.status=='empty_index' and result.active==active and result.encoding is None and dense.calls==[]
    assert len(result.document_ids)==int(blank) and result.chunk_ids==[]


def test_storage_close_failure_is_observable_before_encoding(job,prepared):
    pipeline,active,_,dense,_=job;prepared[3]['close']=True
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY)
    assert_error(caught,'resources','chroma_close_failed',active)
    assert dense.calls==[] and pipeline.manager.catalog.read()==active


def test_actual_result_budget_failure_preserves_known_usage(job,monkeypatch):
    import naiyue_rag.query.pipeline as module
    pipeline,active,*_=job
    def fail(*args,**kwargs):raise StorageError('bundle_limit_exceeded')
    monkeypatch.setattr(module,'_json_bytes',fail)
    with pytest.raises(error_type()) as caught:pipeline.prepare(QUERY)
    assert_error(caught,'embedding','query_result_limit',active,True)
    assert caught.value.encoding_report.status=='success'


def test_query_error_closed_fields_and_defensive_report_copy(job):
    pipeline,*_=job;result=pipeline.prepare(QUERY);cls=error_type()
    error=cls('embedding','query_embedding_failed',active=result.active,encoding_report=result.encoding.report)
    raw=error.to_dict();raw['encoding_report']['batches'].clear()
    assert error.encoding_report.batches
    good=error.to_dict()
    for change in ({'extra':PRIVATE},{'stage':PRIVATE},{'code':PRIVATE},{'active':[]},{'trace_report':{}},
                   {'stage':'request'},{'stage':'resources'},{'active':None}):
        with pytest.raises(ValueError,match='query_invalid_request'):cls.from_dict(good|change)
