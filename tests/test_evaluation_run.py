import csv
import json
import os
from pathlib import Path
import stat
import pytest
from test_application_runtime import runtime_job,native_query,safe_ambient,offline


def prepare(runtime_job,tmp_path,monkeypatch,*,fault=None):
    import naiyue_rag.validation.evaluation_run as module
    from naiyue_rag.local_client import LocalServiceError
    from naiyue_rag.service_protocol import configuration_identity
    runtime,_,settings=runtime_job;runtime.ingest(expected_revision=0);seen=[]
    class Connection:
        def __init__(self,cfg):self.client=self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def health(self):
            if fault=='unauthorized' and seen:raise LocalServiceError('service_unauthorized')
            return {'protocol':1,'instance_id':'a'*32,'config_identity':configuration_identity(settings)}
        def request(self,operation,data):
            if operation=='documents':return {'active':None,'documents':[]} if fault=='empty' else runtime.documents()
            seen.append(data)
            if len(seen)==1 and fault in ('interrupt','changed','resources','unavailable','timeout'):
                if fault=='interrupt':raise KeyboardInterrupt()
                if fault=='changed':raise LocalServiceError('catalog_revision_conflict')
                if fault=='resources':raise LocalServiceError('retrieval_resources_changed')
                if fault=='unavailable':raise LocalServiceError('service_unavailable')
                raise LocalServiceError('retrieval_timeout')
            result=runtime.query(**data)
            if fault=='mismatch':result['active']['revision']+=1
            if fault=='malformed':del result['evidence'][0]['body']
            return result
    monkeypatch.setattr(module,'ManagedConnection',Connection)
    questions=tmp_path/'questions.jsonl'
    questions.write_text('\n'.join(json.dumps({'id':f'Q{i}','query':query,
        'reference_notes':'PRIVATE_LABEL','checkpoints':['必须检查']},ensure_ascii=False)
        for i,query in enumerate(['feature_x','threshold'],1)),encoding='utf-8')
    return module,settings,questions,seen


def test_run_exports_real_evidence_and_blank_review_without_credentials(runtime_job,tmp_path,monkeypatch):
    module,cfg,questions,seen=prepare(runtime_job,tmp_path,monkeypatch)
    output=tmp_path/'run'
    assert module.run_evaluation(cfg,questions,output)==0
    meta=json.loads((output/'run.json').read_text())
    rows=[json.loads(line) for line in (output/'results.jsonl').read_text().splitlines()]
    assert meta['status']=='completed' and meta['completed']==2 and meta['failed']==0
    assert meta['active']['revision']==1 and meta['stage']=='final_evidence'
    assert meta['source_manifest'] and meta['rank_limit']==min(cfg.hybrid.fusion_top_k,cfg.rerank.settings.top_k)
    assert all(set(body)=={'query','expected_revision'} and body['expected_revision']==1 for body in seen)
    assert all(row['result']['evidence'] and row['request_sha256'] for row in rows)
    assert 'PRIVATE_LABEL' in (output/'report.md').read_text()
    with (output/'review.csv').open(newline='',encoding='utf-8-sig') as stream:review=list(csv.DictReader(stream))
    assert len(review)==2 and all(row['judgment']==row['notes']=='' for row in review)
    for path in output.iterdir():
        text=path.read_text(encoding='utf-8-sig')
        assert 'SYNTHETIC_PRIVATE_KEY' not in text and 'SYNTHETIC_SECOND_KEY' not in text
        assert cfg.service.access_token not in text and 'api_key' not in text and 'api_key_env' not in text
    if os.name!='nt':
        assert stat.S_IMODE(output.stat().st_mode)==0o700
        assert all(stat.S_IMODE(path.stat().st_mode)==0o600 for path in output.iterdir())


@pytest.mark.parametrize('fault,status,attempted,code',[
    ('timeout','partial',2,2),('changed','aborted',1,2),
    ('unavailable','aborted',1,2),('interrupt','aborted',1,130),
    ('resources','aborted',1,2),
])
def test_failure_and_interrupt_preserve_progress(runtime_job,tmp_path,monkeypatch,fault,status,attempted,code):
    module,cfg,questions,seen=prepare(runtime_job,tmp_path,monkeypatch,fault=fault)
    output=tmp_path/'run'
    assert module.run_evaluation(cfg,questions,output)==code
    meta=json.loads((output/'run.json').read_text())
    assert meta['status']==status and len(seen)==attempted
    assert meta['remaining_ids']==([] if status=='partial' else ['Q2'])
    assert meta['failed']==1 and (output/'report.md').is_file()


def test_changed_result_version_is_not_saved_as_success(runtime_job,tmp_path,monkeypatch):
    module,cfg,questions,seen=prepare(runtime_job,tmp_path,monkeypatch,fault='mismatch')
    # Trigger the response check after an ordinary first request rather than a provider failure.
    from naiyue_rag.validation.evaluation_run import ManagedConnection
    original=ManagedConnection.request
    def request(self,operation,data):
        if operation=='query':
            result=runtime_job[0].query(**data);result['active']['revision']+=1;seen.append(data);return result
        return original(self,operation,data)
    monkeypatch.setattr(ManagedConnection,'request',request)
    output=tmp_path/'run'
    assert module.run_evaluation(cfg,questions,output)==2
    meta=json.loads((output/'run.json').read_text())
    assert meta['completed']==0 and meta['status']=='aborted' and len(seen)==1
    row=json.loads((output/'results.jsonl').read_text())
    assert row['error']['code']=='evaluation_version_changed' and 'result' not in row


def test_unactivated_library_is_explicit_and_never_queries(runtime_job,tmp_path,monkeypatch):
    module,cfg,questions,seen=prepare(runtime_job,tmp_path,monkeypatch,fault='empty')
    output=tmp_path/'run'
    assert module.run_evaluation(cfg,questions,output)==2
    meta=json.loads((output/'run.json').read_text())
    assert meta['error']['code']=='evaluation_no_active_version' and seen==[]
    assert meta['remaining_ids']==['Q1','Q2']


def test_malformed_evidence_never_becomes_a_success_row(runtime_job,tmp_path,monkeypatch):
    module,cfg,questions,_=prepare(runtime_job,tmp_path,monkeypatch,fault='malformed')
    output=tmp_path/'run'
    assert module.run_evaluation(cfg,questions,output)==2
    meta=json.loads((output/'run.json').read_text())
    assert meta['status']=='aborted' and meta['completed']==0
    row=json.loads((output/'results.jsonl').read_text())
    assert row['error']['code']=='evaluation_invalid_response' and 'result' not in row


def test_evaluation_accepts_core_legal_colon_in_source_path(runtime_job):
    from naiyue_rag.validation.evaluation_run import _validate_result
    runtime,_,cfg=runtime_job
    (Path(cfg.knowledge_base_root)/'case:phase.md').write_text('# phase\n\nfeature_x threshold\n',encoding='utf-8')
    runtime.ingest(expected_revision=0)
    document=next(d for d in runtime.documents()['documents'] if d['source_path']=='case:phase.md')
    result=runtime.query('feature_x',scope_document_ids=[document['document_id']])
    assert result['evidence'] and result['evidence'][0]['source_path']=='case:phase.md'
    _validate_result(result,{'query':'feature_x'})


def test_output_io_failure_aborts_before_queries(runtime_job,tmp_path,monkeypatch):
    module,cfg,questions,seen=prepare(runtime_job,tmp_path,monkeypatch)
    original=module.create_text
    def fail_results(path,*args,**kwargs):
        if path.name=='results.jsonl':raise OSError('PRIVATE_IO_FAILURE')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(module,'create_text',fail_results)
    output=tmp_path/'run'
    assert module.run_evaluation(cfg,questions,output)==2
    meta=json.loads((output/'run.json').read_text())
    assert meta['status']=='aborted' and seen==[] and 'PRIVATE_IO_FAILURE' not in str(meta)


def test_report_write_failure_cannot_leave_a_completed_run(runtime_job,tmp_path,monkeypatch):
    module,cfg,questions,_=prepare(runtime_job,tmp_path,monkeypatch)
    from naiyue_rag.validation.evaluation_inputs import EvaluationError
    def fail(*args):raise EvaluationError('evaluation_output_failed')
    monkeypatch.setattr(module,'write_reports',fail)
    output=tmp_path/'run'
    assert module.run_evaluation(cfg,questions,output)==2
    meta=json.loads((output/'run.json').read_text())
    assert meta['status']=='aborted' and meta['error']['code']=='evaluation_output_failed'


def test_interrupt_during_report_preserves_aborted_manifest(runtime_job,tmp_path,monkeypatch):
    module,cfg,questions,_=prepare(runtime_job,tmp_path,monkeypatch)
    def interrupt(*args):raise KeyboardInterrupt()
    monkeypatch.setattr(module,'write_reports',interrupt)
    output=tmp_path/'run'
    assert module.run_evaluation(cfg,questions,output)==130
    assert json.loads((output/'run.json').read_text())['status']=='aborted'


def test_changed_authentication_stops_remaining_questions(runtime_job,tmp_path,monkeypatch):
    module,cfg,questions,seen=prepare(runtime_job,tmp_path,monkeypatch,fault='unauthorized')
    output=tmp_path/'run'
    assert module.run_evaluation(cfg,questions,output)==2
    meta=json.loads((output/'run.json').read_text())
    assert meta['status']=='aborted' and len(seen)==1
    assert meta['remaining_ids']==['Q2'] and meta['error']['code']=='service_unauthorized'


@pytest.mark.parametrize('root_name',['knowledge_base_root','storage'])
@pytest.mark.parametrize('traversal',[False,True])
def test_output_cannot_pollute_knowledge_or_index_directories(tmp_path,monkeypatch,root_name,traversal):
    import naiyue_rag.validation.evaluation_run as module
    from naiyue_rag.validation.evaluation_inputs import EvaluationError
    from test_model_registry import settings_at
    cfg=settings_at(tmp_path);question=tmp_path/'q.jsonl'
    question.write_text('{"id":"Q1","query":"q"}')
    root=Path(cfg.knowledge_base_root if root_name=='knowledge_base_root' else cfg.storage.storage_root)
    output=(root.parent/'scratch'/'..'/root.name/'eval-results') if traversal else root/'eval-results'
    with pytest.raises(EvaluationError,match='evaluation_output_invalid'):
        module.run_evaluation(cfg,question,output)
    assert not output.exists()


def test_invalid_input_or_existing_output_never_connects(tmp_path,monkeypatch):
    import naiyue_rag.validation.evaluation_run as module
    from naiyue_rag.validation.evaluation_inputs import EvaluationError
    from test_model_registry import settings_at
    cfg=settings_at(tmp_path);seen=[]
    monkeypatch.setattr(module,'ManagedConnection',lambda cfg:seen.append(cfg))
    bad=tmp_path/'bad';bad.write_text('{')
    with pytest.raises(EvaluationError):module.run_evaluation(cfg,bad,tmp_path/'out')
    assert not (tmp_path/'out').exists() and seen==[]
    good=tmp_path/'good';good.write_text('{"id":"Q1","query":"q"}')
    output=tmp_path/'keep';output.mkdir();(output/'review.csv').write_text('human review')
    with pytest.raises(EvaluationError,match='evaluation_output_exists'):module.run_evaluation(cfg,good,output)
    assert seen==[] and (output/'review.csv').read_text()=='human review'


def test_report_escapes_document_markup_and_keeps_full_json(tmp_path):
    from naiyue_rag.validation.evaluation_report import write_reports
    row={'id':'Q1','request_sha256':'a'*64,'status':'success','elapsed_seconds':0.2,
        'query':'<script>bad</script>','reference_notes':'[click](https://example.test)',
        'checkpoints':[],'result':{'status':'retrieved','evidence':[{'rank':3,'source_path':'x.md',
        'body_span':{'line_start':1,'line_end':2},'body':'<img src=x onerror=bad>',
        'contexts':[],'retrieval':{}}],'omitted':[]}}
    write_reports(tmp_path,{'status':'completed','stage':'final_evidence','rank_limit':5},[row])
    text=(tmp_path/'report.md').read_text()
    assert '<script>' not in text and '<img' not in text and '&lt;img' in text
    assert '\\[click\\]' in text and '3' in text
