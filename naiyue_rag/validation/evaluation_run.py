"""Sequential evaluations through the same authenticated service as nyr query."""
import copy
from datetime import datetime,timezone
import hashlib
import json
import logging
import os
from pathlib import Path,PurePosixPath
import re
import time
from .._version import __version__
from ..core.model_registry import load_model_registry
from ..local_client import LocalServiceError
from ..managed_service import ManagedConnection
from ..service_protocol import configuration_identity
from ..storage.document_views import DocumentList,_valid_document_id
from ..storage.version_types import MAX_REVISION
from .evaluation_inputs import EvaluationError,read_questions
from .evaluation_report import create_text,write_json,write_reports

LOGGER=logging.getLogger(__name__)
STOP_CODES=frozenset({'catalog_revision_conflict','service_identity_mismatch','service_unavailable',
    'service_unauthorized','service_local_access_required','retrieval_closed',
    'retrieval_resources_changed','query_identity_mismatch','catalog_identity_mismatch',
    'service_invalid_response','evaluation_version_changed','evaluation_invalid_response'})


def _now():return datetime.now(timezone.utc).isoformat()


def _validate_result(result,question):
    try:
        fields={'schema_version','status','answerability','active','query_sha256','raw_query_sha256',
            'context_text','evidence','omitted','observations'}
        if type(result) is not dict or set(result)!=fields or result['schema_version']!=2:raise ValueError()
        if result['status'] not in ('retrieved','empty','no_evidence_fits') or result['answerability']!='unknown':raise ValueError()
        for name,text in (('query_sha256',question['query'].strip()),('raw_query_sha256',question['query'])):
            if result[name]!=hashlib.sha256(text.encode('utf-8')).hexdigest():raise ValueError()
        if type(result['context_text']) is not str or type(result['observations']) is not dict:raise ValueError()
        if type(result['evidence']) is not list or type(result['omitted']) is not list:raise ValueError()
        ids=set();previous=0
        for evidence in result['evidence']:
            if type(evidence) is not dict:raise ValueError()
            rank=evidence['rank'];uid=evidence['chunk_id'];source=evidence['source_path']
            if type(rank) is not int or rank<=previous or type(uid) is not str or not uid or uid in ids:raise ValueError()
            ids.add(uid);previous=rank
            if not _valid_document_id(evidence['document_id']):raise ValueError()
            if type(source) is not str or not source or '\\' in source or '\x00' in source:raise ValueError()
            source_path=PurePosixPath(source)
            if source_path.is_absolute() or '..' in source_path.parts or re.match(r'^[A-Za-z]:',source) or source_path.as_posix()!=source:raise ValueError()
            if type(evidence['source_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',evidence['source_sha256']) is None:raise ValueError()
            if type(evidence['body']) is not str or type(evidence['retrieval']) is not dict:raise ValueError()
            span=evidence['body_span']
            if type(span) is not dict or any(type(span.get(k)) is not int for k in ('start_char','end_char','line_start','line_end')):raise ValueError()
            if not 0<=span['start_char']<=span['end_char'] or not 1<=span['line_start']<=span['line_end']:raise ValueError()
            if type(evidence['contexts']) is not list:raise ValueError()
            for context in evidence['contexts']:
                if type(context) is not dict or type(context.get('text')) is not str:raise ValueError()
        for omitted in result['omitted']:
            if type(omitted) is not dict or set(omitted)!={'chunk_id','reason'} or \
                    type(omitted['chunk_id']) is not str or omitted['reason']!='context_budget':raise ValueError()
        if (result['status']=='retrieved')!=bool(result['evidence']):raise ValueError()
        json.dumps(result,allow_nan=False)
    except Exception:raise EvaluationError('evaluation_invalid_response') from None


def _configuration(settings,registry):
    cfg=settings;encoding=registry.encoding_settings();rerank=cfg.rerank
    selected={'selection':cfg.encoding.model,'model':encoding.embedding.model,
        'model_revision':encoding.embedding.model_revision,'dimensions':encoding.embedding.expected_dimensions}
    rank={'selection':rerank.model,'backend':rerank.backend,'settings':rerank.settings.to_dict()}
    if rerank.backend=='llm':
        backend=registry.llm_settings(rerank.model)
        rank.update({name:getattr(backend,name) for name in
            ('model','temperature','max_output_tokens','timeout_seconds','deadline_seconds')})
    elif rerank.backend=='cross_encoder':
        backend=registry.local_settings(rerank.model)
        rank.update({name:getattr(backend,name) for name in
            ('model_id','model_revision','device','batch_size','max_pair_tokens')})
    return dict(embedding=selected,representation=encoding.to_dict()['representation'],
        encoding_runtime=encoding.to_dict()['runtime'],ingestion=cfg.ingestion.to_dict(),
        hybrid=cfg.hybrid.to_dict(),rerank=rank,evidence=cfg.evidence.to_dict(),
        retrieval=cfg.retrieval.to_dict(),http_request_timeout_seconds=cfg.service.request_timeout_seconds)


def _output_directory(output,settings):
    try:
        path=Path(output).expanduser().absolute()
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError()
        path=path.resolve()
        for protected in (settings.knowledge_base_root,settings.storage.storage_root):
            if path.is_relative_to(Path(protected).resolve()):raise EvaluationError('evaluation_output_invalid')
        if path.exists():raise EvaluationError('evaluation_output_exists')
        path.mkdir(mode=0o700,parents=True,exist_ok=False)
        return path
    except EvaluationError:raise
    except Exception:raise EvaluationError('evaluation_output_failed') from None


def run_evaluation(settings,questions_path,output,*,max_questions=1000,max_input_bytes=16777216):
    source=read_questions(questions_path,max_questions=max_questions,max_input_bytes=max_input_bytes)
    questions=source['questions'];registry=load_model_registry(settings)
    for question in questions:
        body=dict(question['request'],expected_revision=MAX_REVISION)
        if len(json.dumps(body,ensure_ascii=False,separators=(',',':')).encode())>settings.service.max_request_bytes:
            raise EvaluationError('evaluation_request_limit')
    path=_output_directory(output,settings)
    meta=dict(schema_version=1,package_version=__version__,started_at=_now(),finished_at=None,
        status='running',questions_sha256=source['sha256'],
        questions=[{'id':q['id'],'request_sha256':q['request_sha256']} for q in questions],
        stage='final_evidence',rank_limit=min(settings.hybrid.fusion_top_k,settings.rerank.settings.top_k),
        configuration=_configuration(settings,registry),active=None,source_manifest=[],service_identity=None,
        completed=0,failed=0,remaining_ids=[q['id'] for q in questions])
    rows=[];exit_code=0
    write_json(path/'run.json',meta)
    try:
        with create_text(path/'results.jsonl') as stream:
            with ManagedConnection(settings) as connection:
                client=connection.client;identity=client.health()
                if identity['config_identity']!=configuration_identity(settings,registry):
                    raise EvaluationError('service_identity_mismatch')
                meta['service_identity']=identity
                listed=DocumentList.from_dict(client.request('documents',{}))
                if listed.active is None:raise EvaluationError('evaluation_no_active_version')
                meta['active']=listed.active.to_dict()
                meta['source_manifest']=[{'source_path':d.source_path,'source_sha256':d.source_sha256}
                    for d in listed.documents]
                write_json(path/'run.json',meta)
                for question in questions:
                    if client.health()!=identity:raise EvaluationError('service_identity_mismatch')
                    started=time.monotonic();abort=False
                    row={key:copy.deepcopy(value) for key,value in question.items() if key!='request'}
                    try:
                        result=client.request('query',dict(question['request'],expected_revision=listed.active.revision))
                        if type(result) is not dict:raise EvaluationError('evaluation_invalid_response')
                        if result.get('active')!=meta['active']:raise EvaluationError('evaluation_version_changed')
                        _validate_result(result,question)
                        row.update(status='success',result=result);meta['completed']+=1
                    except KeyboardInterrupt:
                        row.update(status='error',error={'code':'evaluation_interrupted'})
                        meta['failed']+=1;abort=True;exit_code=130
                    except LocalServiceError as error:
                        row.update(status='error',error={'code':error.code})
                        meta['failed']+=1;abort=error.code in STOP_CODES;exit_code=2
                    row['elapsed_seconds']=max(0.,time.monotonic()-started)
                    stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())
                    rows.append(row);meta['remaining_ids'].remove(question['id'])
                    LOGGER.info('evaluation_progress question_id=%s status=%s',question['id'],row['status'])
                    write_json(path/'run.json',meta)
                    if abort:meta['status']='aborted';break
                if meta['status']=='running':meta['status']='partial' if meta['failed'] else 'completed'
    except KeyboardInterrupt:
        meta['status']='aborted';meta['error']={'code':'evaluation_interrupted'};exit_code=130
    except LocalServiceError as error:
        meta['status']='aborted';meta['error']={'code':error.code};exit_code=2
    except Exception:
        LOGGER.error('evaluation_failed code=evaluation_run_failed')
        meta['status']='aborted';meta['error']={'code':'evaluation_run_failed'};exit_code=2
    meta['finished_at']=_now()
    try:write_reports(path,meta,rows)
    except KeyboardInterrupt:
        meta['status']='aborted';meta['error']={'code':'evaluation_interrupted'};exit_code=130
    except EvaluationError as error:
        meta['status']='aborted';meta['error']={'code':error.code};exit_code=2
    except Exception:
        LOGGER.error('evaluation_failed code=evaluation_report_failed')
        meta['status']='aborted';meta['error']={'code':'evaluation_report_failed'};exit_code=2
    write_json(path/'run.json',meta)
    print(json.dumps({'status':meta['status'],'completed':meta['completed'],'failed':meta['failed'],
        'remaining':len(meta['remaining_ids']),'output':str(path)},ensure_ascii=False))
    return exit_code
