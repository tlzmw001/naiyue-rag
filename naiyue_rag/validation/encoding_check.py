"""Preflight and supervise one isolated synthetic encoding acceptance run."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from .. import (EncodingSettings,load_encoding_settings,load_sparse_encoding_settings,MarkdownLoader,
                DocumentChunker,IngestionSettings,prepare_knowledge_base,prepare_document_encoding_inputs,
                prepare_query_encoding_input,plan_encoding_batches)
from ..core.credentials import resolve_api_key
from ..core.encoding_report import input_fingerprint
from ..encoding.openai_embedding import _check_environment
from ..encoding.execution_report import new_report
from .check_report import CheckError,read_journal,safe_code

QUERY='feature_x=1且threshold=0.5时应关注哪些边界？'
KEY_NAME='NAIYUE_RAG_VALIDATION_KEY'
DESCRIPTOR_LIMIT=16384
# Dataset identities, not model/runtime settings: this tool may send only these public synthetic files.
EXPECTED_SOURCES={'feature.md':'433693302b7bda0dc6d7fd643c270673d3023f224b66b11bba955756ff28247b',
                  'threshold.md':'0e73e5ca355df3c80c4dd326f5978fe7ed025e6e3b33c95dd32deaa3981876b5'}


def checked_path(path,root):
    try:
        value=Path(path).absolute()
        if '..' in value.parts or not value.is_relative_to(root):raise ValueError()
        for part in [value,*value.parents]:
            if part.is_symlink():raise ValueError()
            if part==root:break
        return value
    except Exception:raise CheckError('check_path_invalid') from None


def _write_new(path,payload):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:
        stream.write(payload);stream.flush();os.fsync(stream.fileno())


def _plan(inputs,cfg):
    return dict(input_count=len(inputs),input_fingerprint=input_fingerprint(inputs),batches=[
        dict(input_count=len(batch),input_fingerprint=input_fingerprint(batch)) for batch in plan_encoding_batches(inputs,cfg)])


def prepare_job(encoding_settings_path,sparse_settings_path,output_dir,*,project_root,key_env,
                cleanup_seconds,max_checkpoint_bytes,max_checkpoint_records):
    start=time.monotonic()
    try:
        if type(cleanup_seconds) not in (int,float) or not math.isfinite(cleanup_seconds) or cleanup_seconds<=0:
            raise CheckError('check_limits_invalid')
        if any(type(v) is not int or v<=0 for v in [max_checkpoint_bytes,max_checkpoint_records]):raise CheckError('check_limits_invalid')
        root=Path(project_root).absolute();checked_path(root,root)
        if not root.is_dir():raise CheckError('check_path_invalid')
        cfg_path=checked_path(encoding_settings_path,root);sparse_path=checked_path(sparse_settings_path,root)
        output=checked_path(output_dir,root)
        if not output.is_relative_to(root/'data/validation') or output==root/'data/validation':raise CheckError('check_path_invalid')
        if output.exists():raise CheckError('check_output_exists')
        cfg=load_encoding_settings(cfg_path);load_sparse_encoding_settings(sparse_path)
        key=resolve_api_key(root,key_env);_check_environment(new_report())
        source=checked_path(root/'examples/encoding-check',root)
        docs=MarkdownLoader(source,'encoding-check',4096).load_all()
        if len(docs)!=2 or {d.metadata['source_path']:d.metadata['source_sha256'] for d in docs}!=EXPECTED_SOURCES:
            raise CheckError('check_preflight_failed')
        chunks,relations,issues=prepare_knowledge_base(docs,DocumentChunker(IngestionSettings(1000,200)),text_mode=cfg.representation.document_text_mode)
        if issues or relations['edges'] or relations['diagnostics'] or len(chunks)!=2:raise CheckError('check_preflight_failed')
        inputs=prepare_document_encoding_inputs(docs,chunks,cfg);query=prepare_query_encoding_input(QUERY,cfg)
        plans=dict(documents=_plan(inputs,cfg),query=_plan([query],cfg))
        if sum(len(p['batches']) for p in plans.values())>cfg.runtime.max_requests:raise CheckError('check_budget_exceeded')
        # Copy the validated templates verbatim; relative Sparse cache now belongs to this run.
        output.parent.mkdir(mode=0o700,parents=True,exist_ok=True);output.mkdir(mode=0o700)
        for original,name in [(cfg_path,'encoding.yaml'),(sparse_path,'sparse.yaml')]:
            payload=original.read_bytes()
            if len(payload)>65536:raise CheckError('check_preflight_failed')
            _write_new(output/name,payload)
        actual=load_encoding_settings(output/'encoding.yaml');sparse=load_sparse_encoding_settings(output/'sparse.yaml')
        if actual.to_dict()!=cfg.to_dict():raise CheckError('check_preflight_failed')
        checked_path(sparse.cache_dir,output)
        _write_new(output/'checkpoints.jsonl',b'')
        job=dict(run_id=uuid.uuid4().hex,project_root=str(root),run_dir=str(output),settings=cfg.to_dict(),
                 sparse_settings=sparse.to_dict(),inputs=[i.to_dict() for i in inputs],query=QUERY,plans=plans,
                 model_space_id=cfg.model_space_id,representation_id=cfg.representation_id,
                 max_checkpoint_bytes=max_checkpoint_bytes,max_checkpoint_records=max_checkpoint_records)
        payload=json.dumps(job,ensure_ascii=True,allow_nan=False).encode()
        if len(payload)>DESCRIPTOR_LIMIT:raise CheckError('check_descriptor_invalid')
        return job,key,time.monotonic()-start
    except CheckError:raise
    except Exception:raise CheckError('check_preflight_failed') from None


def run_check(encoding_settings_path,sparse_settings_path,output_dir,*,project_root,key_env,
              cleanup_seconds,max_checkpoint_bytes,max_checkpoint_records):
    job,key,preparation=prepare_job(encoding_settings_path,sparse_settings_path,output_dir,
        project_root=project_root,key_env=key_env,cleanup_seconds=cleanup_seconds,
        max_checkpoint_bytes=max_checkpoint_bytes,max_checkpoint_records=max_checkpoint_records)
    start=time.monotonic();child=None;error=None;cleanup_error=None;reaped=False;kill_requested=False;exit_code=None
    # Only runtime essentials; no proxy, Python startup injection, SDK settings or other account keys.
    environment={name:os.environ[name] for name in ['PATH','SYSTEMROOT','WINDIR','LANG','LC_ALL','TMPDIR','TEMP','TMP'] if name in os.environ}
    environment[KEY_NAME]=key
    try:
        child=subprocess.Popen([sys.executable,'-m','naiyue_rag.validation.encoding_worker'],
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parents[2],env=environment)
        remaining=job['settings']['runtime']['deadline_seconds']-(time.monotonic()-start)
        if remaining<=0:raise subprocess.TimeoutExpired('encoding_worker',0)
        child.communicate(input=json.dumps(job,ensure_ascii=True,allow_nan=False).encode(),timeout=remaining)
        exit_code=child.returncode;reaped=True
    except subprocess.TimeoutExpired:error='worker_deadline_exceeded'
    except Exception:error='worker_start_failed' if child is None else 'worker_supervision_failed'
    finally:
        environment.pop(KEY_NAME,None);key=None
        if child is not None and not reaped:
            try:
                if child.poll() is None:
                    kill_requested=True;child.kill()
            except Exception:cleanup_error='worker_kill_failed'
            try:
                exit_code=child.wait(timeout=cleanup_seconds);reaped=True
            except subprocess.TimeoutExpired:cleanup_error='worker_reap_timeout'
            except Exception:cleanup_error=cleanup_error or 'worker_reap_failed'
            try:
                if child.stdin is not None:child.stdin.close()
            except Exception:cleanup_error=cleanup_error or 'worker_reap_failed'
    ledger,protocol_error,truncated=read_journal(job)
    if error is None:
        if protocol_error:error=protocol_error
        elif truncated or not reaped or ledger.final is None:error='worker_failed'
        elif ledger.final['status']=='failed':error=ledger.final['error_code'] if exit_code!=0 else 'checkpoint_protocol_invalid'
        elif exit_code!=0:error='worker_failed'
    result=dict(run_id=job['run_id'],status='failed' if error or cleanup_error else 'complete',
        terminal_stage=ledger.final['stage'] if ledger.final else ledger.stage or 'initialize',error_code=error or cleanup_error,
        worker_exit_code=exit_code,kill_requested=kill_requested,reaped=reaped,cleanup_error=cleanup_error,
        persistence_error=None,protocol_error_code=protocol_error,checkpoint_truncated=truncated,
        checkpoint_count=ledger.seq,elapsed_seconds=time.monotonic()-start,preparation_seconds=preparation,
        model_space_id=job['model_space_id'],representation_id=job['representation_id'],
        tokenizer_id=ledger.identity['tokenizer_id'] if ledger.identity else None,
        documents=ledger.tasks.get('documents',{}).get('report'),query=ledger.tasks.get('query',{}).get('report'),
        validation={stage:ledger.tasks.get(stage,{}).get('summary') for stage in ('documents','query')},
        client_cleanup=ledger.cleanup,billing_cost=None,**ledger.summary())
    if protocol_error or truncated:
        result['attempted_requests']=None;result['usage']['status']='partial' if ledger.observations else 'unknown'
        result['usage']['total_tokens']=result['usage']['total_prompt_tokens']=None
    try:_write_new(Path(job['run_dir'])/'report.json',(json.dumps(result,ensure_ascii=True,allow_nan=False,indent=2)+'\n').encode())
    except Exception:
        result['status']='failed';result['persistence_error']='report_write_failed'
        result['error_code']=result['error_code'] or 'report_write_failed'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['encoding-settings','sparse-settings','output-dir','project-root','key-env']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--cleanup-seconds',type=float,required=True)
    parser.add_argument('--max-checkpoint-bytes',type=int,required=True)
    parser.add_argument('--max-checkpoint-records',type=int,required=True)
    args=vars(parser.parse_args());encoding=args.pop('encoding_settings');sparse=args.pop('sparse_settings');output=args.pop('output_dir')
    try:result=run_check(encoding,sparse,output,**args)
    except CheckError as error:result=dict(status='failed',error_code=error.code)
    print(json.dumps(result,ensure_ascii=True,allow_nan=False,indent=2))
    return 0 if result['status']=='complete' else 1

if __name__=='__main__':sys.exit(main())
