"""Private worker: existing M3 encoders, durable Dense observations, owned resources."""
import json
import os
from pathlib import Path
import sys
from .. import (EncodingSettings,SparseEncodingSettings,OpenAICompatibleEmbedding,DenseEncoder,SparseEncoder,
                BatchProcessor,QueryEncoder,EncodingResult,QueryEncodingResult,prepare_query_encoding_input)
from ..core.encoding_types import EncodingInput,fail_encoding
from ..core.encoding_report import validate_request_report,input_fingerprint
from ..core.errors import EmbeddingExecutionError,EncodingJobError
from ..encoding.validation import ProviderBatchResult
from .check_report import CheckError,Journal,safe_code
from .encoding_check import checked_path,_plan,DESCRIPTOR_LIMIT,KEY_NAME,QUERY,EXPECTED_SOURCES


def _components(job,key):
    cfg=EncodingSettings.from_dict(job['settings']);sparse_cfg=SparseEncodingSettings.from_dict(job['sparse_settings'])
    provider=OpenAICompatibleEmbedding(cfg,api_key=key)
    try:return provider,DenseEncoder(cfg,provider),SparseEncoder(cfg,sparse_cfg)
    except Exception as error:
        code=safe_code(getattr(error,'code',None),'worker_initialization_failed')
        failure=CheckError(code)
        try:
            provider.close();failure.cleanup=dict(attempted=True,closed=provider.closed,error_code=None)
        except Exception:failure.cleanup=dict(attempted=True,closed=False,error_code='worker_close_failed')
        raise failure from None


class ObservedDense:
    """Only the validation worker consumes this adapter; production APIs stay unchanged."""
    def __init__(self,dense,journal):self.dense=dense;self.settings=dense.settings;self.journal=journal;self.stage=None

    def encode_batch(self,inputs,*,remaining_seconds):
        ordinal=len(self.journal.ledger.reservations)+1
        if ordinal>self.settings.runtime.max_requests:fail_encoding('encoding_request_limit')
        self.journal.emit('request_reserved',dict(ordinal=ordinal,stage=self.stage,
            input_count=len(inputs),input_fingerprint=input_fingerprint(inputs)))
        try:result,report=self.dense.encode_batch(inputs,remaining_seconds=remaining_seconds)
        except EmbeddingExecutionError as error:
            report=validate_request_report(error.report)
            self.journal.emit('request_observed',dict(ordinal=ordinal,report=report,returned_model=None,
                source_kind=None,usage=None,usage_status='unknown_missing'))
            raise
        report=validate_request_report(report)
        result=ProviderBatchResult.from_dict(result.to_dict())
        if result.returned_model not in self.settings.embedding.allowed_response_models:fail_encoding('invalid_provider_batch_result')
        if report['attempted_requests']!=1 or report['error_code'] is not None:fail_encoding('invalid_encoding_report')
        self.journal.emit('request_observed',dict(ordinal=ordinal,report=report,returned_model=result.returned_model,
            source_kind=result.source_kind,usage=result.usage,usage_status=result.usage_status))
        return result,report


def _validate_job(job):
    fields={'run_id','project_root','run_dir','settings','sparse_settings','inputs','query','plans',
            'model_space_id','representation_id','max_checkpoint_bytes','max_checkpoint_records'}
    try:
        import re
        if type(job) is not dict or set(job)!=fields or re.fullmatch('[0-9a-f]{32}',job['run_id']) is None:raise ValueError()
        root=Path(job['project_root']).absolute();checked_path(root,root)
        output=checked_path(job['run_dir'],root/'data/validation')
        if output==root/'data/validation' or not output.is_dir():raise ValueError()
        cfg=EncodingSettings.from_dict(job['settings']);sparse=SparseEncodingSettings.from_dict(job['sparse_settings'])
        checked_path(sparse.cache_dir,output)
        if any(type(job[k]) is not int or job[k]<=0 for k in ['max_checkpoint_bytes','max_checkpoint_records']):raise ValueError()
        if job['model_space_id']!=cfg.model_space_id or job['representation_id']!=cfg.representation_id or job['query']!=QUERY:raise ValueError()
        inputs=[EncodingInput.from_dict(i) for i in job['inputs']]
        if len(inputs)!=2 or any(i.kind!='document' or i.knowledge_base_id!='encoding-check' for i in inputs):raise ValueError()
        if {i.source_sha256 for i in inputs}!=set(EXPECTED_SOURCES.values()):raise ValueError()
        query=prepare_query_encoding_input(job['query'],cfg)
        plans=dict(documents=_plan(inputs,cfg),query=_plan([query],cfg))
        if json.dumps(plans,sort_keys=True)!=json.dumps(job['plans'],sort_keys=True):raise ValueError()
        if sum(len(p['batches']) for p in plans.values())>cfg.runtime.max_requests:raise ValueError()
        return cfg,inputs
    except Exception:raise CheckError('check_descriptor_invalid') from None


def _summary(result,stage,job):
    # The actual DTO validation checks finite/nonzero vectors, paired source IDs/hashes and dimensions.
    data=result.to_dict();cls=EncodingResult if stage=='documents' else QueryEncodingResult
    if cls.from_dict(json.loads(json.dumps(data,allow_nan=False))).to_dict()!=data:fail_encoding('encoding_pairing_failed')
    return dict(count=job['plans'][stage]['input_count'],dimensions=result.dimensions,
        model_space_id=job['model_space_id'],representation_id=job['representation_id'],
        tokenizer_id=result.tokenizer_id,input_fingerprint=result.report.input_fingerprint,json_roundtrip=True)


def run_job(job,key):
    cfg,inputs=_validate_job(job);journal=Journal(job);provider=None;error=None;stage='initialize';cleanup=None
    try:
        provider,dense,sparse=_components(job,key)
        journal.emit('worker_started',dict(model_space_id=cfg.model_space_id,representation_id=cfg.representation_id,
            tokenizer_id=sparse.tokenizer_id,dimensions=cfg.embedding.expected_dimensions))
        observed=ObservedDense(dense,journal)
        for stage in ['documents','query']:
            observed.stage=stage;journal.emit('task_started',dict(stage=stage))
            try:
                result=BatchProcessor(cfg,observed,sparse).process(inputs) if stage=='documents' else QueryEncoder(cfg,observed,sparse).encode(job['query'])
            except EncodingJobError as failure:
                journal.emit('task_result',dict(stage=stage,report=failure.report,summary=None));raise
            summary=_summary(result,stage,job)
            journal.emit('task_result',dict(stage=stage,report=result.report.to_dict(),summary=summary))
    except Exception as failure:
        error=safe_code(getattr(failure,'code',None),'worker_initialization_failed' if stage=='initialize' else 'worker_failed')
        cleanup=getattr(failure,'cleanup',None) if stage=='initialize' else None
    finally:
        if provider is not None:
            try:
                provider.close()
                cleanup=dict(attempted=True,closed=provider.closed,error_code=None if provider.closed else 'worker_close_failed')
            except Exception:cleanup=dict(attempted=True,closed=False,error_code='worker_close_failed')
        if cleanup is None:cleanup=dict(attempted=False,closed=False,error_code=None)
    try:
        journal.emit('cleanup',cleanup)
        if error is None and cleanup['error_code'] is not None:error=cleanup['error_code'];stage='cleanup'
        journal.emit('final',dict(status='failed' if error else 'complete',stage=stage if error else 'cleanup',error_code=error))
    except Exception:return 1
    return 1 if error else 0


def main():
    try:
        raw=sys.stdin.buffer.read(DESCRIPTOR_LIMIT+1)
        if len(raw)>DESCRIPTOR_LIMIT:raise CheckError('check_descriptor_invalid')
        job=json.loads(raw);key=os.environ.pop(KEY_NAME,'')
        return run_job(job,key)
    except Exception:return 1

if __name__=='__main__':sys.exit(main())
