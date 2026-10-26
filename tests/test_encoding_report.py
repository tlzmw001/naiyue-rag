"""Safe fixed observation fields and consistent known/unknown usage, no payload logs."""
import copy
import json
import pytest
from naiyue_rag.core.encoding_report import EncodingReport,validate_request_report
from naiyue_rag.core.errors import EncodingError,EncodingJobError
from test_batch_processor import setup,inputs,PRIVATE


def test_report_roundtrip_and_error_copy():
    report=setup()[0].process(inputs()).report;raw=report.to_dict()
    cloned=EncodingReport.from_dict(json.loads(json.dumps(raw)))
    assert cloned.to_dict()==raw and 'C1' not in json.dumps(raw)
    raw['batches'][0]['usage']['prompt_tokens']=999
    assert cloned.batches[0]['usage']['prompt_tokens']==7
    job,dense,sparse=setup();sparse.hook=lambda batch,n:(_ for _ in ()).throw(RuntimeError(PRIVATE))
    with pytest.raises(EncodingJobError) as caught:job.process(inputs())
    error=caught.value;fresh=EncodingJobError(error.code,error.report)
    error.report['usage']['total_tokens']=999
    assert fresh.report['usage']['total_tokens']==7
    assert PRIVATE not in str(fresh)+repr(cloned)

@pytest.mark.parametrize('fault',['extra','job','negative','bool','nan','counter','total','unknown','range','code','request-field','usage-field','stage','status'])
def test_malformed_report_rejected_without_payload(fault,caplog):
    raw=setup()[0].process(inputs()).report.to_dict()
    if fault=='extra':raw['text']=PRIVATE
    elif fault=='job':raw['job_id']=PRIVATE
    elif fault=='negative':raw['elapsed_seconds']=-1
    elif fault=='bool':raw['requests']['attempted_requests']=True
    elif fault=='nan':raw['batches'][0]['elapsed_seconds']=float('nan')
    elif fault=='counter':raw['paired_input_count']=4
    elif fault=='total':raw['usage']['total_tokens']=999
    elif fault=='unknown':raw['usage']['observation_unknown_dense_calls']=1
    elif fault=='range':raw['batches'][1]['input_start']=0
    elif fault=='code':raw['batches'][0]['request_report']['error_code']=PRIVATE
    elif fault=='request-field':raw['batches'][0]['request_report']['url']=PRIVATE
    elif fault=='usage-field':raw['batches'][0]['usage']['text']=PRIVATE
    elif fault=='stage':raw['batches'][0]['stage']='sparse'
    else:raw['status']='failed'
    with pytest.raises(EncodingError,match='invalid_encoding_report'):EncodingReport.from_dict(raw)
    assert PRIVATE not in caplog.text

@pytest.mark.parametrize('key,value',[('attempted_requests',True),('http_status',True),('response_bytes',-1),
    ('elapsed_seconds',float('inf')),('http_status',600),('error_code',PRIVATE)])
def test_invalid_request_report_is_not_an_observation(key,value):
    from naiyue_rag.encoding.execution_report import new_report
    raw=new_report();raw[key]=value
    with pytest.raises(EncodingError,match='invalid_encoding_report'):validate_request_report(raw)


def test_report_mutation_is_revalidated():
    report=setup()[0].process(inputs()).report;report.usage['status']='complete-but-guessed'
    with pytest.raises(EncodingError,match='invalid_encoding_report'):report.to_dict()

@pytest.mark.parametrize('fault',['complete-zero-request','preflight-after-batches','finalize-incomplete','planned-without-hash'])
def test_terminal_state_must_match_observed_path(fault):
    from naiyue_rag.core.encoding_report import summarize_observations
    raw=setup()[0].process(inputs()).report.to_dict()
    if fault=='complete-zero-request':
        raw['batches'][0]['request_report']['attempted_requests']=0
        raw['batches'][0]['request_report']['http_status']=None
        raw['batches'][0]['usage']=None;raw['batches'][0]['usage_status']='unknown_missing'
        raw['requests'],raw['usage']=summarize_observations(raw['batches'],3)
    elif fault=='planned-without-hash':raw['input_fingerprint']=None;raw['status']='failed';raw['error']=dict(stage='finalize',code='encoding_stage_failed',batch_index=None)
    else:
        raw['status']='failed';raw['error']=dict(stage='preflight' if fault=='preflight-after-batches' else 'finalize',code='encoding_stage_failed',batch_index=None)
        if fault=='finalize-incomplete':
            raw['batches'][-1]['stage']='sparse';raw['batches'][-1]['error_code']='encoding_stage_failed'
            raw['completed_batch_count']=2;raw['paired_input_count']=4
    with pytest.raises(EncodingError,match='invalid_encoding_report'):EncodingReport.from_dict(raw)
