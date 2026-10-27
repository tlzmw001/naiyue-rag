"""One problem to a complete query representation with whole-job observations."""
import copy
import json
from types import SimpleNamespace
import pytest
from naiyue_rag import QueryEncoder,QueryEncodingResult
from naiyue_rag.core.errors import EncodingError,EmbeddingExecutionError,EncodingJobError
from naiyue_rag.core.sparse_types import SparseRecord
from naiyue_rag.encoding.validation import ProviderBatchResult
from naiyue_rag.encoding.execution_report import new_report
from test_encoding_settings import config
from test_document_chunker import offline

TOKENIZER='a'*64
PRIVATE='SYNTHETIC_PRIVATE'
QUERY='  开关 关 开关 TC-01 cvr_ltv 0.5  '

class Dense:
    def __init__(self,cfg):self.settings=cfg;self.calls=[];self.hook=None;self.usage=7
    def encode_batch(self,batch,*,remaining_seconds):
        self.calls.append(([i.to_dict() for i in batch],remaining_seconds))
        if self.hook:self.hook(batch)
        item=batch[0];usage=None if self.usage is None else dict(prompt_tokens=self.usage,total_tokens=self.usage)
        result=ProviderBatchResult([[1.,2.,3.]],[item.item_id],[item.embedding_text_sha256],
            self.settings.model_space_id,'synthetic-model','simulated',usage,'known' if usage is not None else 'unknown_missing')
        report=new_report();report.update(attempted_requests=1,http_status=200)
        return result,report

class Sparse:
    def __init__(self,cfg):self.encoding_settings=cfg;self.tokenizer_id=TOKENIZER;self.calls=[];self.hook=None;self.empty=False
    def encode_batch(self,batch):
        self.calls.append([i.to_dict() for i in batch])
        if self.hook:self.hook(batch)
        item=batch[0];tokens=[] if self.empty else ['开关','开关','tc-01','cvr_ltv','0.5']
        tf={} if self.empty else {'开关':2,'tc-01':1,'cvr_ltv':1,'0.5':1}
        return [SparseRecord(item.item_id,'query',item.retrieval_text_sha256,tokens,tf,len(tokens),len(tf),TOKENIZER)]

def setup(cfg=None):
    cfg=cfg or config();dense=Dense(cfg);sparse=Sparse(cfg)
    return QueryEncoder(cfg,dense,sparse),dense,sparse


def test_query_retains_raw_input_pair_and_stable_terms():
    encoder,dense,sparse=setup();result=encoder.encode(QUERY)
    assert result.input.kind=='query' and result.input.retrieval_text==QUERY.strip()
    assert result.input.embedding_text=='query: '+QUERY.strip()
    assert result.input.embedding_text_sha256!=result.input.retrieval_text_sha256
    assert result.input.knowledge_base_id is None and result.input.source_span is None
    assert result.query_terms==['开关','tc-01','cvr_ltv','0.5'] and result.sparse.term_frequencies['开关']==2
    assert len(dense.calls)==len(sparse.calls)==1
    assert result.report.status=='success' and result.report.paired_input_count==1
    assert result.report.usage['total_tokens']==7
    assert result.input.item_id=='query-'+result.input.query_sha256
    assert QueryEncodingResult.from_dict(json.loads(json.dumps(result.to_dict()))).to_dict()==result.to_dict()
    assert QUERY not in json.dumps(result.report.to_dict(),ensure_ascii=False)

@pytest.mark.parametrize('query',['',' \n ',None,True,[],123,'\ud800'])
def test_invalid_query_fails_before_both_encoders(query,caplog):
    encoder,dense,sparse=setup()
    with pytest.raises(EncodingJobError) as caught:encoder.encode(query)
    assert dense.calls==sparse.calls==[]
    report=caught.value.report
    assert report['error']['stage']=='preflight' and report['input_count']==1
    assert report['requests']['attempted_requests']==0 and report['usage']['status']=='no_requests'


def test_utf8_limit_is_checked_before_network():
    encoder,dense,sparse=setup(config(runtime={'max_input_utf8_bytes':10}))
    with pytest.raises(EncodingJobError,match='encoding_input_limit'):encoder.encode(QUERY)
    assert dense.calls==sparse.calls==[]

@pytest.mark.parametrize('stage',['dense','sparse','pairing','finalize'])
def test_failure_keeps_request_and_usage_with_no_query_result(monkeypatch,stage,caplog):
    import naiyue_rag.encoding.query_encoder as module
    encoder,dense,sparse=setup()
    if stage=='dense':
        def broken(batch):
            report=new_report();report.update(attempted_requests=1,http_status=429,error_code='embedding_http_429')
            raise EmbeddingExecutionError('embedding_http_429',report)
        dense.hook=broken
    elif stage=='sparse':sparse.hook=lambda batch:(_ for _ in ()).throw(OSError(PRIVATE))
    elif stage=='pairing':sparse.encode_batch=lambda batch:[]
    else:
        def broken(*args,**kwargs):raise EncodingError('invalid_query_encoding_result')
        monkeypatch.setattr(module,'QueryEncodingResult',broken)
    with pytest.raises(EncodingJobError) as caught:encoder.encode(QUERY)
    report=caught.value.report
    assert report['error']['stage']==stage and report['requests']['attempted_requests']==1
    assert report['usage']['total_tokens']==(None if stage=='dense' else 7)
    assert not hasattr(caught.value,'dense_vector') and not hasattr(caught.value,'query_terms')
    assert len(dense.calls)==1 and len(sparse.calls)==(0 if stage in ('dense','pairing') else 1)
    assert PRIVATE not in json.dumps(report)+caplog.text

@pytest.mark.parametrize('fault',['id','hash','model-space','dimension','sparse-id','sparse-hash','sparse-kind','tokenizer','sparse-extra'])
def test_query_pairing_checks_both_roles(fault):
    encoder,dense,sparse=setup();normal_dense=dense.encode_batch;normal_sparse=sparse.encode_batch
    def bad_dense(batch,**kwargs):
        result,report=normal_dense(batch,**kwargs)
        if fault=='id':result.input_ids[0]='other'
        elif fault=='hash':result.input_hashes[0]='0'*64
        elif fault=='model-space':result.model_space_id='0'*64
        elif fault=='dimension':result.vectors=[[1.,2.]]
        return result,report
    def bad_sparse(batch):
        rows=normal_sparse(batch)
        if fault=='sparse-id':rows[0].item_id='other'
        elif fault=='sparse-hash':rows[0].retrieval_text_sha256='0'*64
        elif fault=='sparse-kind':rows[0].kind='document'
        elif fault=='tokenizer':rows[0].tokenizer_id='0'*64
        elif fault=='sparse-extra':rows.append(copy.deepcopy(rows[0]))
        return rows
    dense.encode_batch=bad_dense;sparse.encode_batch=bad_sparse
    with pytest.raises(EncodingJobError,match='encoding_pairing_failed') as caught:encoder.encode(QUERY)
    assert caught.value.report['usage']['total_tokens']==7

@pytest.mark.parametrize('fault',['missing-report','unknown-exception','unknown-code','count-zero','count-two','model-alias'])
def test_dense_protocol_observation_is_safe(fault,caplog):
    encoder,dense,sparse=setup();normal=dense.encode_batch
    def bad(batch,**kwargs):
        if fault=='unknown-exception':raise RuntimeError(PRIVATE)
        result,report=normal(batch,**kwargs)
        if fault=='missing-report':report=None
        elif fault=='unknown-code':report['error_code']=PRIVATE
        elif fault=='count-zero':report['attempted_requests']=0;report['http_status']=None
        elif fault=='count-two':report['attempted_requests']=2
        elif fault=='model-alias':result.returned_model=PRIVATE
        return result,report
    dense.encode_batch=bad
    with pytest.raises(EncodingJobError) as caught:encoder.encode(QUERY)
    report=caught.value.report
    assert sparse.calls==[] and report['usage']['total_tokens'] is None
    if fault in ('missing-report','unknown-exception','unknown-code'):
        assert report['requests']['attempted_requests'] is None
    else:assert report['requests']['attempted_requests']==(0 if fault=='count-zero' else 2 if fault=='count-two' else 1)
    assert PRIVATE not in json.dumps(report)+caplog.text

@pytest.mark.parametrize('usage',[None,0])
def test_unknown_usage_and_zero_are_distinct(usage):
    encoder,dense,_=setup();dense.usage=usage;report=encoder.encode(QUERY).report.to_dict()
    assert report['usage']['status']==('unknown' if usage is None else 'complete')
    assert report['usage']['total_tokens']==usage


def test_empty_sparse_is_valid_representation():
    encoder,_,sparse=setup();sparse.empty=True;result=encoder.encode('关')
    assert result.query_terms==[] and result.sparse.doc_length==0 and result.dense_vector==[1.,2.,3.]

@pytest.mark.parametrize('stage',['preflight','dense','sparse','pairing','finalize'])
def test_deadline_covers_stages_with_actual_remaining_time(monkeypatch,stage):
    import naiyue_rag.encoding.query_encoder as module
    clock=[0.];monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    import naiyue_rag.encoding.batch_report as report_module
    monkeypatch.setattr(report_module,'time',module.time)
    encoder,dense,sparse=setup(config(runtime={'deadline_seconds':10}))
    if stage=='preflight':
        normal=module.prepare_query_encoding_input
        def late(*args):result=normal(*args);clock[0]=11.;return result
        monkeypatch.setattr(module,'prepare_query_encoding_input',late)
    elif stage=='dense':dense.hook=lambda batch:clock.__setitem__(0,11.)
    elif stage=='sparse':sparse.hook=lambda batch:clock.__setitem__(0,11.)
    elif stage=='pairing':
        normal=encoder._pair
        def late(*args):result=normal(*args);clock[0]=11.;return result
        monkeypatch.setattr(encoder,'_pair',late)
    else:
        normal=module.QueryEncodingResult
        def late(*args,**kwargs):result=normal(*args,**kwargs);clock[0]=11.;return result
        monkeypatch.setattr(module,'QueryEncodingResult',late)
    with pytest.raises(EncodingJobError,match='encoding_deadline_exceeded') as caught:encoder.encode(QUERY)
    assert caught.value.report['error']['stage']==stage
    assert len(dense.calls)==(0 if stage=='preflight' else 1)
    if dense.calls:assert dense.calls[0][1]==10.


def test_deadline_consumed_by_preflight_is_not_reset(monkeypatch):
    import naiyue_rag.encoding.query_encoder as module
    clock=[0.];monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    import naiyue_rag.encoding.batch_report as report_module
    monkeypatch.setattr(report_module,'time',module.time)
    normal=module.prepare_query_encoding_input
    def prepare(*args):result=normal(*args);clock[0]=3.;return result
    monkeypatch.setattr(module,'prepare_query_encoding_input',prepare)
    encoder,dense,_=setup(config(runtime={'deadline_seconds':10}));encoder.encode(QUERY)
    assert dense.calls[0][1]==7.


def test_baseexception_propagates_without_running_sparse():
    encoder,dense,sparse=setup();dense.hook=lambda batch:(_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):encoder.encode(QUERY)
    assert sparse.calls==[]

@pytest.mark.parametrize('fault',['extra','vector-bool','zero','dimension','id','kind','hash','terms-order','terms-extra','tokenizer','failed-report','fingerprint','report-range'])
def test_query_dto_strict_binding_and_copy(fault):
    raw=setup()[0].encode(QUERY).to_dict()
    if fault=='extra':raw['text']=PRIVATE
    elif fault=='vector-bool':raw['dense_vector'][0]=True
    elif fault=='zero':raw['dense_vector']=[0.,0.,0.]
    elif fault=='dimension':raw['dimensions']=2
    elif fault=='id':raw['input']['item_id']='other';raw['sparse']['item_id']='other'
    elif fault=='kind':raw['sparse']['kind']='document'
    elif fault=='hash':raw['sparse']['retrieval_text_sha256']='0'*64
    elif fault=='terms-order':raw['query_terms'].reverse()
    elif fault=='terms-extra':raw['query_terms'].append('new')
    elif fault=='tokenizer':raw['tokenizer_id']='0'*64
    elif fault=='failed-report':raw['report']['status']='failed'
    elif fault=='fingerprint':raw['report']['input_fingerprint']='0'*64
    else:raw['report']['batches'][0]['input_end']=2
    with pytest.raises(EncodingError,match='invalid_query_encoding_result'):QueryEncodingResult.from_dict(raw)


def test_returned_data_does_not_alias_serialized_input():
    result=setup()[0].encode(QUERY);raw=result.to_dict();restored=QueryEncodingResult.from_dict(raw)
    raw['dense_vector'][0]=99;raw['query_terms'].append('new');raw['sparse']['tokens'].clear()
    assert restored.to_dict()==result.to_dict()
    restored.sparse.tokens.append('new')
    with pytest.raises(EncodingError,match='invalid_query_encoding_result'):restored.to_dict()

@pytest.mark.parametrize('which',['dense','sparse'])
def test_constructor_settings_must_match(which):
    cfg=config();dense=Dense(cfg);sparse=Sparse(cfg)
    if which=='dense':dense.settings=config(runtime={'batch_size':3})
    else:sparse.encoding_settings=config(runtime={'batch_size':3})
    with pytest.raises(EncodingError,match='encoding_settings_mismatch'):QueryEncoder(cfg,dense,sparse)
