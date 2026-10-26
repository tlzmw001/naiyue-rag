"""Whole-job pairing and observations at real encoder boundaries, no network."""
import copy
import json
from types import SimpleNamespace
import pytest
from naiyue_rag.encoding.batch_processor import BatchProcessor
from naiyue_rag.core.errors import EncodingError,EmbeddingExecutionError,EncodingJobError
from naiyue_rag.core.encoding_types import EncodingInput,text_sha
from naiyue_rag.core.sparse_types import SparseRecord
from naiyue_rag.encoding.validation import ProviderBatchResult
from naiyue_rag.encoding.execution_report import new_report
from test_encoding_settings import config
from test_document_chunker import offline

TOKENIZER='a'*64
PRIVATE='SYNTHETIC_PRIVATE'

def inputs(cfg=None,count=5):
    cfg=cfg or config();out=[]
    for n in range(count):
        text=f'开关 TC-{n:02d} 0.5';emb=cfg.representation.document_prefix+text;sha=text_sha('document')
        out.append(EncodingInput(f'C{n+1}','document','kb','doc',sha,
            dict(start_char=n,end_char=n+1,line_start=n+1,line_end=n+1,source_sha256=sha),
            text,emb,text_sha(text),text_sha(emb),cfg.model_space_id,cfg.representation_id,None))
    return out

class Dense:
    def __init__(self,cfg):self.settings=cfg;self.calls=[];self.hook=None;self.usages=[7,5,3]
    def encode_batch(self,batch,*,remaining_seconds):
        self.calls.append(([i.item_id for i in batch],remaining_seconds))
        if self.hook:self.hook(batch,len(self.calls))
        usage=self.usages[len(self.calls)-1];report=new_report();report.update(attempted_requests=1,http_status=200)
        ordered=list(reversed(batch))
        result=ProviderBatchResult([[float(i.item_id[1:]),2.,3.] for i in ordered],
            [i.item_id for i in ordered],[i.embedding_text_sha256 for i in ordered],self.settings.model_space_id,
            'synthetic-model','simulated',None if usage is None else dict(prompt_tokens=usage,total_tokens=usage),
            'unknown_missing' if usage is None else 'known')
        return result,report

class Sparse:
    def __init__(self,cfg):self.encoding_settings=cfg;self.tokenizer_id=TOKENIZER;self.calls=[];self.hook=None
    def encode_batch(self,batch):
        self.calls.append([i.item_id for i in batch])
        if self.hook:self.hook(batch,len(self.calls))
        return [SparseRecord(i.item_id,i.kind,i.retrieval_text_sha256,[],{},0,0,TOKENIZER) for i in reversed(batch)]

def setup(cfg=None):
    cfg=cfg or config();dense=Dense(cfg);sparse=Sparse(cfg)
    return BatchProcessor(cfg,dense,sparse),dense,sparse

def test_success_pairs_by_id_and_restores_input_order():
    job,dense,sparse=setup();source=inputs();result=job.process(source)
    assert [r.input.item_id for r in result.records]==['C1','C2','C3','C4','C5']
    assert [r.dense_vector[0] for r in result.records]==[1,2,3,4,5]
    assert [r.batch_index for r in result.records]==[0,0,1,1,2]
    report=result.report.to_dict()
    assert report['status']=='success' and report['completed_batch_count']==3 and report['paired_input_count']==5
    assert report['requests']['attempted_requests']==3 and report['usage']['total_tokens']==15
    assert report['usage']['status']=='complete' and len(sparse.calls)==3
    assert result.records[0].input is not source[0]
    assert json.loads(json.dumps(result.to_dict()))==result.to_dict()

@pytest.mark.parametrize('fault',['last-hash','duplicate','query','mixed-kb','versions','limit','request-limit','not-list'])
def test_whole_preflight_failure_makes_no_calls(fault):
    cfg=config(runtime={'max_inputs':4}) if fault=='limit' else config(runtime={'max_requests':2}) if fault=='request-limit' else config()
    job,dense,sparse=setup(cfg);items=inputs(cfg)
    if fault=='last-hash':items[-1].embedding_text=PRIVATE
    elif fault=='duplicate':items[-1]=copy.deepcopy(items[0])
    elif fault=='query':
        from naiyue_rag.encoding import prepare_query_encoding_input
        items[-1]=prepare_query_encoding_input('query',cfg)
    elif fault=='mixed-kb':items[-1].knowledge_base_id='other'
    elif fault=='versions':items[-1].source_sha256=text_sha('new');items[-1].source_span['source_sha256']=text_sha('new')
    elif fault=='not-list':items=tuple(items)
    with pytest.raises(EncodingJobError) as caught:job.process(items)
    assert dense.calls==[] and sparse.calls==[]
    assert caught.value.report['error']['stage']=='preflight'
    assert caught.value.report['requests']['attempted_requests']==0

@pytest.mark.parametrize('stage',['dense','sparse','pairing'])
def test_second_batch_failure_stops_third_and_keeps_usage(stage,caplog):
    job,dense,sparse=setup()
    if stage=='dense':
        def fault(batch,n):
            if n==2:
                report=new_report();report.update(attempted_requests=1,http_status=503,error_code='embedding_request_failed')
                raise EmbeddingExecutionError('embedding_request_failed',report)
        dense.hook=fault
    elif stage=='sparse':
        def fault(batch,n):
            if n==2:raise RuntimeError(PRIVATE)
        sparse.hook=fault
    else:
        original=sparse.encode_batch
        def bad(batch):
            rows=original(batch)
            return rows[:-1] if len(sparse.calls)==2 else rows
        sparse.encode_batch=bad
    with pytest.raises(EncodingJobError) as caught:job.process(inputs())
    error=caught.value;report=error.report
    assert len(dense.calls)==2 and len(sparse.calls)==(1 if stage=='dense' else 2)
    assert report['completed_batch_count']==1 and report['paired_input_count']==2
    assert report['error']['stage']==stage and not hasattr(error,'records')
    assert report['requests']['attempted_requests']==2
    assert report['usage']['known_prompt_tokens_sum']==(7 if stage=='dense' else 12)
    assert report['usage']['total_tokens']==(None if stage=='dense' else 12)
    assert PRIVATE not in json.dumps(report)+str(error)+caplog.text

@pytest.mark.parametrize('usages,expected',[( [7,None,3],'partial'),([None,None,None],'unknown'),([0,0,0],'complete')])
def test_missing_and_zero_usage_are_distinguished(usages,expected):
    job,dense,_=setup();dense.usages=usages;report=job.process(inputs()).report.to_dict()
    assert report['usage']['status']==expected
    assert report['usage']['total_tokens']==(0 if expected=='complete' else None)
    assert report['usage']['known_prompt_tokens_sum']==(10 if expected=='partial' else None if expected=='unknown' else 0)

@pytest.mark.parametrize('fault',['exception','bad-report','bad-code','too-many-requests'])
def test_unknown_observation_does_not_invent_zero(fault,caplog):
    cfg=config(runtime={'max_requests':3});job,dense,_=setup(cfg);original=dense.encode_batch
    def bad(batch,**kwargs):
        if fault=='exception':dense.calls.append(([],0));raise OSError(PRIVATE)
        result,report=original(batch,**kwargs)
        if fault=='bad-report':report['url']=PRIVATE
        elif fault=='bad-code':report['error_code']=PRIVATE
        else:report['attempted_requests']=4
        return result,report
    dense.encode_batch=bad
    with pytest.raises(EncodingJobError) as caught:job.process(inputs(cfg))
    report=caught.value.report
    assert len(dense.calls)==1
    if fault=='too-many-requests':assert report['requests']['attempted_requests']==4
    else:
        assert report['requests']['attempted_requests'] is None
        assert report['requests']['observation_unknown_dense_calls']==1
    assert PRIVATE not in json.dumps(report)+caplog.text

def test_empty_is_no_requests_not_zero_tokens():
    job,dense,sparse=setup();result=job.process([]);report=result.report.to_dict()
    assert result.records==[] and result.knowledge_base_id is None and report['status']=='empty'
    assert report['usage']['status']=='no_requests' and report['usage']['total_tokens'] is None
    assert dense.calls==sparse.calls==[]

def test_input_snapshot_survives_callers_mutation():
    job,dense,_=setup();source=inputs();before=[i.to_dict() for i in source]
    dense.hook=lambda batch,n:setattr(source[-1],'retrieval_text',PRIVATE)
    result=job.process(source)
    assert [r.input.to_dict() for r in result.records]==before

@pytest.mark.parametrize('stage',['dense','sparse','pairing','finalize'])
def test_cooperative_deadline_checks_after_stages(monkeypatch,stage):
    import naiyue_rag.encoding.batch_processor as module
    clock=[0.];monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    job,dense,sparse=setup(config(runtime={'deadline_seconds':10}));items=inputs(job.settings,2)
    if stage=='dense':dense.hook=lambda batch,n:clock.__setitem__(0,11.)
    elif stage=='sparse':sparse.hook=lambda batch,n:clock.__setitem__(0,11.)
    elif stage=='pairing':
        original=job._pair
        def late(*args):result=original(*args);clock[0]=11.;return result
        monkeypatch.setattr(job,'_pair',late)
    else:
        original=module.EncodingResult
        def late(*args,**kwargs):result=original(*args,**kwargs);clock[0]=11.;return result
        monkeypatch.setattr(module,'EncodingResult',late)
    with pytest.raises(EncodingJobError,match='encoding_deadline_exceeded') as caught:job.process(items)
    assert caught.value.report['error']['stage']==stage and len(dense.calls)==1
    assert dense.calls[0][1]==10.

def test_remaining_deadline_is_not_reset(monkeypatch):
    import naiyue_rag.encoding.batch_processor as module
    clock=[0.];monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    cfg=config(runtime={'deadline_seconds':10});job,dense,_=setup(cfg)
    dense.hook=lambda batch,n:clock.__setitem__(0,clock[0]+2.)
    job.process(inputs(cfg));assert [c[1] for c in dense.calls]==[10.,8.,6.]

def test_baseexception_propagates_and_resources_remain_callers():
    job,dense,sparse=setup();dense.hook=lambda batch,n:(_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):job.process(inputs())
    assert len(dense.calls)==1 and sparse.calls==[]

@pytest.mark.parametrize('which',['dense','sparse'])
def test_constructor_requires_same_settings(which):
    cfg=config();dense=Dense(cfg);sparse=Sparse(cfg)
    if which=='dense':dense.settings=config(runtime={'batch_size':3})
    else:sparse.encoding_settings=config(runtime={'batch_size':3})
    with pytest.raises(EncodingError,match='encoding_settings_mismatch'):BatchProcessor(cfg,dense,sparse)

@pytest.mark.parametrize('fault',['ids','dense-hash','dimension','model-space','sparse-duplicate','sparse-hash','tokenizer'])
def test_pairing_faults_do_not_return_partial_records(fault):
    job,dense,sparse=setup();original_dense=dense.encode_batch;original_sparse=sparse.encode_batch
    def bad_dense(batch,**kwargs):
        result,report=original_dense(batch,**kwargs)
        if fault=='ids':result.input_ids[0]='other'
        elif fault=='dense-hash':result.input_hashes[0]='0'*64
        elif fault=='dimension':result.vectors=[v[:2] for v in result.vectors]
        elif fault=='model-space':result.model_space_id='0'*64
        return result,report
    def bad_sparse(batch):
        rows=original_sparse(batch)
        if fault=='sparse-duplicate':rows[-1]=copy.deepcopy(rows[0])
        elif fault=='sparse-hash':rows[0].retrieval_text_sha256='0'*64
        elif fault=='tokenizer':rows[0].tokenizer_id='0'*64
        return rows
    dense.encode_batch=bad_dense;sparse.encode_batch=bad_sparse
    with pytest.raises(EncodingJobError,match='encoding_pairing_failed') as caught:job.process(inputs())
    assert caught.value.report['error']['stage']=='pairing'
    assert caught.value.report['usage']['total_tokens']==7 and len(dense.calls)==1

@pytest.mark.parametrize('count',[0,2])
def test_success_with_impossible_request_count_still_returns_safe_job_error(count):
    job,dense,_=setup();original=dense.encode_batch
    def bad(batch,**kwargs):
        result,report=original(batch,**kwargs);report['attempted_requests']=count;report['http_status']=None
        return result,report
    dense.encode_batch=bad
    with pytest.raises(EncodingJobError,match='invalid_encoding_report') as caught:job.process(inputs())
    assert caught.value.report['requests']['attempted_requests']==count
    assert caught.value.report['usage']['total_tokens'] is None


def test_unknown_second_call_preserves_first_observation():
    job,dense,_=setup();original=dense.encode_batch
    def broken(batch,**kwargs):
        if len(dense.calls)==1:dense.calls.append(([],0));raise RuntimeError(PRIVATE)
        return original(batch,**kwargs)
    dense.encode_batch=broken
    with pytest.raises(EncodingJobError) as caught:job.process(inputs())
    report=caught.value.report
    assert report['requests']['dense_calls_started']==2 and report['requests']['attempted_requests'] is None
    assert report['requests']['attempted_requests_known_sum']==1
    assert report['usage']['status']=='partial' and report['usage']['known_prompt_tokens_sum']==7
    assert report['usage']['unknown_usage_requests'] is None and report['usage']['total_tokens'] is None


def test_final_validation_failure_keeps_all_issued_usage(monkeypatch):
    import naiyue_rag.encoding.batch_processor as module
    def broken(*args,**kwargs):raise EncodingError('invalid_encoding_result')
    monkeypatch.setattr(module,'EncodingResult',broken);job,dense,sparse=setup()
    with pytest.raises(EncodingJobError) as caught:job.process(inputs())
    report=caught.value.report
    assert report['error']['stage']=='finalize' and report['completed_batch_count']==3
    assert report['usage']['total_tokens']==15 and not hasattr(caught.value,'records')


def test_encoder_cannot_reassign_source_identity_after_preflight():
    job,dense,_=setup()
    dense.hook=lambda batch,n:[setattr(i,'source_document_id','another-doc') for i in batch]
    with pytest.raises(EncodingJobError,match='invalid_encoding_result') as caught:job.process(inputs())
    assert caught.value.report['error']['stage']=='finalize'
