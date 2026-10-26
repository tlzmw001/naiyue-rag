"""Request-local timing and strictly bounded, source-free query reports."""
import copy
from datetime import datetime, timezone
import math
import re
import time
from uuid import UUID, uuid4

from .errors import TraceError

STAGES = ('request', 'resources', 'embedding', 'dense', 'sparse', 'fusion', 'packing')
FIELDS = {
    'request': {'status'},
    'resources': {'status', 'corpus_id', 'index_id'},
    'embedding': {'adapter_calls', 'source_kind', 'usage'},
    'dense': {'compared_count', 'candidate_count'},
    'sparse': {'compared_count', 'candidate_count'},
    'fusion': {'union_count', 'candidate_count'},
    'packing': {'selected_count', 'status', 'context_characters'},
}
ERROR_CODES = {
    'unknown_failure', 'invalid_query', 'invalid_request', 'invalid_scope', 'invalid_candidate_k',
    'invalid_context_budget', 'invalid_resources', 'invalid_resource_config', 'invalid_authorization',
    'snapshot_changed', 'snapshot_load_failed', 'invalid_embedding_adapter', 'embedding_failed',
    'invalid_query_embedding', 'invalid_vectors', 'invalid_vector', 'invalid_norm', 'usage_unknown',
    'invalid_file', 'cache_mismatch', 'invalid_keyword_config', 'tokenizer_error', 'tokenization_error',
    'invalid_units', 'keyword_index_error', 'keyword_query_error', 'invalid_fusion_config',
    'invalid_candidates', 'invalid_score_kind', 'invalid_score_prefix', 'invalid_result',
    'invalid_document', 'invalid_chunk', 'invalid_span', 'retrieval_failed',
    'invalid_corpus_source', 'invalid_corpus_state', 'invalid_corpus_registry', 'invalid_corpus_unit_identity',
    'invalid_corpus_body_span', 'invalid_corpus_context_span', 'invalid_corpus_render', 'invalid_corpus_counts',
}
REPORT_FIELDS = {'schema_version', 'trace_id', 'trace_type', 'started_at', 'finished_at',
                 'total_elapsed_ms', 'status', 'error', 'stages'}


def _invalid():
    raise TraceError('invalid_trace') from None


def _number(value):
    try:
        valid = type(value) in (int, float) and value >= 0 and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        _invalid()


def _count(value):
    if type(value) is not int or value < 0:
        _invalid()


def _timestamp(value):
    if type(value) is not str or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00', value):
        _invalid()
    try:
        datetime.fromisoformat(value)
    except ValueError:
        _invalid()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _stage_data(name, data):
    if type(name) is str and name in ('dense','sparse') and type(data) is dict and \
            set(data)=={'eligible_count','candidate_count'}:
        for value in data.values():_count(value)
        return
    if type(name) is not str or name not in FIELDS or type(data) is not dict or set(data) != FIELDS[name]:
        _invalid()
    if name == 'request':
        if type(data['status']) is not str or data['status'] != 'validated': _invalid()
    elif name == 'resources':
        if type(data['status']) is not str or data['status'] != 'verified': _invalid()
        for key in ['corpus_id', 'index_id']:
            if type(data[key]) is not str or not re.fullmatch('[0-9a-f]{64}', data[key]): _invalid()
    elif name == 'embedding':
        _count(data['adapter_calls'])
        if type(data['source_kind']) is not str or data['source_kind'] not in ('cached','simulated','service','unknown'):
            _invalid()
        usage = data['usage']
        if usage is not None:
            required = {'prompt_tokens', 'total_tokens'}
            if type(usage) is not dict or not required <= set(usage) or set(usage) - required - {'completion_tokens'}:
                _invalid()
            for value in usage.values(): _count(value)
            if usage['total_tokens'] < usage['prompt_tokens']: _invalid()
    else:
        for key in FIELDS[name] - {'status'}: _count(data[key])
        if name == 'packing' and (type(data['status']) is not str or
                                  data['status'] not in ('retrieved','empty','no_evidence_fits')):
            _invalid()


def validate_trace_report(report):
    """Validate a closed report without accepting arbitrary metadata or text."""
    if type(report) is not dict or set(report) != REPORT_FIELDS:
        _invalid()
    if type(report['schema_version']) is not int or report['schema_version'] != 1 or \
            type(report['trace_type']) is not str or report['trace_type'] != 'query' or \
            type(report['status']) is not str:
        _invalid()
    try:
        trace_id = UUID(report['trace_id'])
        if trace_id.version != 4 or str(trace_id) != report['trace_id']: _invalid()
    except (ValueError, TypeError, AttributeError):
        _invalid()
    _timestamp(report['started_at']); _timestamp(report['finished_at'])
    _number(report['total_elapsed_ms'])
    error = report['error']
    if report['status'] == 'success':
        if error is not None: _invalid()
    elif report['status'] == 'error':
        if type(error) is not dict or set(error) != {'stage','code'}:
            _invalid()
        if type(error['stage']) is not str or error['stage'] not in STAGES or \
                type(error['code']) is not str or error['code'] not in ERROR_CODES:
            _invalid()
    else:
        _invalid()
    if type(report['stages']) is not list or len(report['stages']) > len(STAGES):
        _invalid()
    seen = set()
    for entry in report['stages']:
        if type(entry) is not dict or set(entry) != {'stage','timestamp','elapsed_ms','data'}:
            _invalid()
        _stage_data(entry['stage'], entry['data'])
        if entry['stage'] in seen: _invalid()
        seen.add(entry['stage'])
        _timestamp(entry['timestamp']); _number(entry['elapsed_ms'])


class TraceContext:
    """One query only; monotonic durations and UTC event timestamps."""

    def __init__(self, trace_type='query'):
        if type(trace_type) is not str or trace_type != 'query': _invalid()
        self._trace_id = str(uuid4())
        self._started_at = _utc_now()
        self._start_mono = time.monotonic()
        self._previous_mono = self._start_mono
        self._stages = []
        self._report = None

    @property
    def trace_id(self):
        return self._trace_id

    def record_stage(self, stage_name, data, elapsed_ms=None):
        if self._report is not None or any(row['stage'] == stage_name for row in self._stages):
            _invalid()
        _stage_data(stage_name, data)
        now = time.monotonic()
        elapsed = (now - self._previous_mono) * 1000 if elapsed_ms is None else elapsed_ms
        _number(elapsed)
        elapsed = round(elapsed, 3)
        self._stages.append({'stage':stage_name, 'timestamp':_utc_now(),
                             'elapsed_ms':elapsed, 'data':copy.deepcopy(data)})
        self._previous_mono = now
        return elapsed

    def finish(self, status, *, error_stage=None, error_code=None):
        if self._report is not None or type(status) is not str or status not in ('success','error'):
            _invalid()
        error = None
        if status == 'success':
            if error_stage is not None or error_code is not None: _invalid()
        else:
            if type(error_stage) is not str or error_stage not in STAGES or error_code is None: _invalid()
            code = error_code if type(error_code) is str and error_code in ERROR_CODES else 'unknown_failure'
            error = {'stage':error_stage, 'code':code}
        elapsed = (time.monotonic() - self._start_mono) * 1000
        _number(elapsed)
        report = {'schema_version':1, 'trace_id':self._trace_id, 'trace_type':'query',
                  'started_at':self._started_at, 'finished_at':_utc_now(), 'total_elapsed_ms':round(elapsed,3),
                  'status':status, 'error':error, 'stages':copy.deepcopy(self._stages)}
        validate_trace_report(report)
        self._report = report

    def to_dict(self):
        if self._report is None: _invalid()
        return copy.deepcopy(self._report)

    def to_legacy_stages(self):
        return [{'stage':row['stage'], 'elapsed_ms':row['elapsed_ms'], **copy.deepcopy(row['data'])}
                for row in self._stages]
