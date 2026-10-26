"""Strict, payload-free observations for one encoding job; no storage side effect."""
import copy
from dataclasses import dataclass,asdict
import hashlib
import json
import math
import re
from .encoding_types import fail_encoding

# These codes are local identities, never provider text or unconstrained exceptions.
ERROR_CODES=frozenset('''invalid_encoding_input encoding_identity_mismatch encoding_input_limit
encoding_request_limit invalid_embedding_response invalid_provider_batch_result invalid_sparse_record
invalid_sparse_batch sparse_encoding_failed sparse_term_limit sparse_tokenization_failed
sparse_resource_limit sparse_resource_path_invalid sparse_cache_invalid sparse_cache_load_failed
sparse_cache_initialization_failed sparse_dictionary_read_failed sparse_jieba_initialization_failed
embedding_deadline_exceeded embedding_encoding_failed embedding_invalid_batch embedding_invalid_timeout
embedding_provider_settings_mismatch embedding_response_too_large embedding_timeout
embedding_connection_failed embedding_request_failed embedding_invalid_json embedding_provider_busy
embedding_provider_closed embedding_unsafe_sdk_environment embedding_invalid_response_headers
embedding_transport_not_bound embedding_unsupported_content_encoding embedding_response_close_failed
embedding_client_close_failed encoding_stage_failed encoding_deadline_exceeded encoding_pairing_failed
encoding_settings_mismatch encoding_document_scope_mismatch invalid_encoding_report
invalid_encoded_record invalid_encoding_result invalid_query_encoding_result'''.split())
ERROR_CODES=ERROR_CODES | frozenset(f'embedding_http_{status}' for status in range(100,600))
STAGES=frozenset(['preflight','dense','sparse','pairing','complete','finalize'])
REQUEST_FIELDS={'attempted_requests','http_status','response_bytes','elapsed_seconds','error_code',
                'response_close_error_code','client_close_error_code'}
BATCH_FIELDS={'index','input_start','input_end','input_count','input_fingerprint','stage','elapsed_seconds',
              'request_report','returned_model','source_kind','usage','usage_status','error_code'}


def safe_code(code):return code if type(code) is str and code in ERROR_CODES else 'encoding_stage_failed'


def _integer(value):return type(value) is int and value>=0


def _seconds(value):
    try:return type(value) in (int,float) and math.isfinite(value) and value>=0
    except OverflowError:return False


def _hash(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None


def _code(value):return value is None or (type(value) is str and value in ERROR_CODES)


def input_fingerprint(inputs):
    fields=['item_id','kind','knowledge_base_id','source_document_id','source_span','source_sha256','retrieval_text_sha256','embedding_text_sha256',
            'model_space_id','representation_id']
    payload=[[getattr(item,key) for key in fields] for item in inputs]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_request_report(data):
    """Reject extra fields; retaining only selected keys would silently hide bad observations."""
    try:
        if type(data) is not dict or set(data)!=REQUEST_FIELDS:raise ValueError()
        if not _integer(data['attempted_requests']) or not _integer(data['response_bytes']) or not _seconds(data['elapsed_seconds']):raise ValueError()
        status=data['http_status']
        if status is not None and (type(status) is not int or not 100<=status<=599 or data['attempted_requests']==0):raise ValueError()
        if any(not _code(data[key]) for key in ['error_code','response_close_error_code','client_close_error_code']):raise ValueError()
        return copy.deepcopy(data)
    except Exception:fail_encoding('invalid_encoding_report')


def _validate_usage(batch):
    usage=batch['usage'];status=batch['usage_status']
    if status=='known':
        if type(usage) is not dict or set(usage) not in ({'prompt_tokens','total_tokens'},
                {'prompt_tokens','total_tokens','completion_tokens'}):raise ValueError()
        if any(not _integer(v) for v in usage.values()) or usage['total_tokens']<usage['prompt_tokens']:raise ValueError()
        if batch['returned_model'] is None:raise ValueError()
        request=batch['request_report']
        if request is not None and request['attempted_requests']!=1:raise ValueError()
    elif status not in ('unknown_missing','unknown_invalid') or usage is not None:raise ValueError()


def summarize_observations(batches,dense_calls_started):
    """Known subtotals are observations; an unobserved call never becomes zero requests."""
    reports=[b['request_report'] for b in batches if b['request_report'] is not None]
    unknown=dense_calls_started-len(reports)
    known_sum=sum(r['attempted_requests'] for r in reports)
    known=[b['usage'] for b in batches if b['usage_status']=='known']
    known_count=len(known)
    prompt=sum(u['prompt_tokens'] for u in known) if known else None
    total=sum(u['total_tokens'] for u in known) if known else None
    unknown_usage=None if unknown else known_sum-known_count
    status=('no_requests' if not unknown and known_sum==0 else
            'complete' if not unknown and unknown_usage==0 else 'partial' if known else 'unknown')
    requests=dict(dense_calls_started=dense_calls_started,attempted_requests=None if unknown else known_sum,
        attempted_requests_known_sum=known_sum,observation_unknown_dense_calls=unknown,
        http_responses_observed=sum(r['http_status'] is not None for r in reports))
    usage=dict(known_usage_requests=known_count,known_prompt_tokens_sum=prompt,known_total_tokens_sum=total,
        unknown_usage_requests=unknown_usage,observation_unknown_dense_calls=unknown,status=status,
        total_prompt_tokens=prompt if status=='complete' else None,total_tokens=total if status=='complete' else None)
    return requests,usage


@dataclass(repr=False)
class EncodingReport:
    job_id:str
    status:str
    input_count:int|None
    input_fingerprint:str|None
    planned_batch_count:int|None
    completed_batch_count:int
    paired_input_count:int
    elapsed_seconds:float
    requests:dict
    usage:dict
    batches:list
    error:dict|None

    def __post_init__(self):
        try:
            if type(self.job_id) is not str or re.fullmatch('[0-9a-f]{32}',self.job_id) is None:raise ValueError()
            if self.status not in ('success','empty','failed') or not _seconds(self.elapsed_seconds):raise ValueError()
            for value in [self.input_count,self.planned_batch_count]:
                if value is not None and not _integer(value):raise ValueError()
            if self.input_fingerprint is not None and not _hash(self.input_fingerprint):raise ValueError()
            if any(not _integer(v) for v in [self.completed_batch_count,self.paired_input_count]):raise ValueError()
            if type(self.batches) is not list:raise ValueError()
            end=0
            for index,batch in enumerate(self.batches):
                if type(batch) is not dict or set(batch)!=BATCH_FIELDS:raise ValueError()
                if type(batch['index']) is not int or batch['index']!=index:raise ValueError()
                if any(not _integer(batch[k]) for k in ['input_start','input_end','input_count']):raise ValueError()
                if batch['input_start']!=end or batch['input_count']<=0 or batch['input_end']-end!=batch['input_count']:raise ValueError()
                end=batch['input_end']
                if not _hash(batch['input_fingerprint']) or not _seconds(batch['elapsed_seconds']):raise ValueError()
                if batch['stage'] not in ('dense','sparse','pairing','complete') or not _code(batch['error_code']):raise ValueError()
                if batch['request_report'] is not None:validate_request_report(batch['request_report'])
                model=batch['returned_model']
                if model is not None and (type(model) is not str or not model or any(ord(c)<32 for c in model)):raise ValueError()
                if (model is None)!=(batch['source_kind'] is None) or batch['source_kind'] not in (None,'service','simulated'):raise ValueError()
                _validate_usage(batch)
                if batch['stage']=='complete':
                    if batch['error_code'] is not None or model is None or batch['request_report'] is None:raise ValueError()
                    if batch['request_report']['attempted_requests']!=1 or batch['request_report']['error_code'] is not None:raise ValueError()
                elif index!=len(self.batches)-1 or batch['error_code'] is None:raise ValueError()
            if self.completed_batch_count!=sum(b['stage']=='complete' for b in self.batches):raise ValueError()
            if self.paired_input_count!=sum(b['input_count'] for b in self.batches if b['stage']=='complete'):raise ValueError()
            if self.input_count is not None and end>self.input_count:raise ValueError()
            if self.planned_batch_count is None:
                if self.batches or self.completed_batch_count:raise ValueError()
            elif len(self.batches)>self.planned_batch_count or self.input_fingerprint is None:raise ValueError()
            if type(self.requests) is not dict or not _integer(self.requests.get('dense_calls_started')):raise ValueError()
            started=self.requests['dense_calls_started']
            # The last batch can expire before its Dense call starts.
            if not 0<=len(self.batches)-started<=1:raise ValueError()
            if len([b for b in self.batches if b['request_report'] is not None])>started:raise ValueError()
            expected_requests,expected_usage=summarize_observations(self.batches,started)
            if self.requests!=expected_requests or self.usage!=expected_usage:raise ValueError()
            # Python dict equality equates bool and int: enforce shapes via canonical JSON.
            if json.dumps(self.requests,sort_keys=True)!=json.dumps(expected_requests,sort_keys=True) or \
                    json.dumps(self.usage,sort_keys=True)!=json.dumps(expected_usage,sort_keys=True):raise ValueError()
            if self.status=='failed':
                if type(self.error) is not dict or set(self.error)!={'stage','code','batch_index'}:raise ValueError()
                if self.error['stage'] not in STAGES-{'complete'} or not _code(self.error['code']) or self.error['code'] is None:raise ValueError()
                index=self.error['batch_index']
                if index is not None and (type(index) is not int or not self.batches or index!=len(self.batches)-1):raise ValueError()
                if self.error['stage'] in ('dense','sparse','pairing'):
                    if index is None or self.batches[-1]['stage']!=self.error['stage'] or self.batches[-1]['error_code']!=self.error['code']:raise ValueError()
                elif index is not None:raise ValueError()
                if self.error['stage']=='preflight' and self.batches:raise ValueError()
                if self.error['stage']=='finalize' and any(b['stage']!='complete' for b in self.batches):raise ValueError()
            else:
                if self.error is not None or self.input_count is None or self.input_fingerprint is None or self.planned_batch_count is None:raise ValueError()
                if self.completed_batch_count!=self.planned_batch_count or self.paired_input_count!=self.input_count:raise ValueError()
                if self.status=='empty' and (self.input_count!=0 or started!=0) or self.status=='success' and self.input_count==0:raise ValueError()
            self.requests=copy.deepcopy(self.requests);self.usage=copy.deepcopy(self.usage)
            self.batches=copy.deepcopy(self.batches);self.error=copy.deepcopy(self.error)
        except Exception:fail_encoding('invalid_encoding_report')

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):fail_encoding('invalid_encoding_report')
        return cls(**copy.deepcopy(data))
