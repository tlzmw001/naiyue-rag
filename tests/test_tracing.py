"""Trace lifecycle, strict payload boundaries and real temporary JSONL writes."""
import copy
import json
import logging
from pathlib import Path
import traceback
from uuid import UUID

import pytest

from naiyue_rag.core.errors import TraceError
from naiyue_rag.core.trace_context import TraceContext, validate_trace_report
from naiyue_rag.core.trace_collector import TraceCollector


def report():
    trace = TraceContext()
    trace.record_stage('request', {'status':'validated'})
    trace.finish('error', error_stage='resources', error_code='invalid_resources')
    return trace.to_dict()


def test_monotonic_clock_and_closed_lifecycle(monkeypatch):
    from naiyue_rag.core import trace_context as module
    ticks = iter([10., 10.125, 10.5])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(ticks))
    trace = TraceContext()
    elapsed = trace.record_stage('request', {'status':'validated'})
    trace.finish('success')
    data = trace.to_dict()
    assert elapsed == 125.0 and data['total_elapsed_ms'] == 500.0
    assert UUID(data['trace_id']).version == 4
    assert data['trace_type'] == 'query' and data['schema_version'] == 1
    assert data['status'] == 'success' and data['error'] is None
    assert data['started_at'].endswith('+00:00') and data['finished_at'].endswith('+00:00')
    assert trace.to_legacy_stages() == [{'stage':'request','elapsed_ms':125.,'status':'validated'}]
    with pytest.raises(TraceError): trace.finish('success')
    with pytest.raises(TraceError): trace.record_stage('request', {'status':'validated'})


def test_unique_contexts_and_defensive_copies():
    first = TraceContext(); second = TraceContext()
    raw = {'adapter_calls':1,'source_kind':'simulated','usage':{'prompt_tokens':3,'total_tokens':3}}
    first.record_stage('embedding', raw)
    raw['usage']['prompt_tokens'] = 99
    first.finish('success'); second.finish('success')
    exported = first.to_dict(); exported['stages'][0]['data']['usage']['prompt_tokens'] = 50
    legacy = first.to_legacy_stages(); legacy[0]['usage'].clear()
    assert first.to_dict()['stages'][0]['data']['usage']['prompt_tokens'] == 3
    assert second.to_dict()['stages'] == []
    assert first.to_dict()['trace_id'] != second.to_dict()['trace_id']
    assert 'prompt_tokens' not in repr(first)


def test_unfinished_report_and_invalid_lifecycle_are_rejected():
    trace = TraceContext()
    with pytest.raises(TraceError): trace.to_dict()
    with pytest.raises(TraceError): trace.finish('other')
    with pytest.raises(TraceError): trace.finish('error')
    with pytest.raises(TraceError): trace.finish('success', error_stage='dense', error_code='retrieval_failed')
    with pytest.raises(TraceError): TraceContext(trace_type='ingestion')


def test_unknown_error_code_is_not_persisted():
    trace = TraceContext()
    trace.finish('error', error_stage='dense', error_code='SYNTHETIC_SECRET_CODE')
    assert trace.to_dict()['error'] == {'stage':'dense','code':'unknown_failure'}


@pytest.mark.parametrize('code', ['invalid_corpus_unit_identity','invalid_corpus_body_span',
                                  'invalid_corpus_context_span'])
def test_current_source_integrity_codes_are_recognized(code):
    trace = TraceContext()
    trace.finish('error', error_stage='resources', error_code=code)
    assert trace.to_dict()['error'] == {'stage':'resources','code':code}


@pytest.mark.parametrize('stage,data', [
    ('unknown', {}), ('request', {'status':'secret'}),
    ('request', {'status':'validated','query':'secret'}),
    ('dense', {'compared_count':True,'candidate_count':1}),
    ('sparse', {'compared_count':1,'candidate_count':-1}),
    ('resources', {'status':'verified','corpus_id':'secret','index_id':'0'*64}),
    ('embedding', {'adapter_calls':1,'source_kind':'other','usage':None}),
    ('embedding', {'adapter_calls':1,'source_kind':'cached','usage':{'prompt_tokens':1,'total_tokens':0}}),
    ('embedding', {'adapter_calls':1,'source_kind':'cached','usage':{'prompt_tokens':1,'total_tokens':1,'query':'secret'}}),
    ('fusion', {'union_count':float('nan'),'candidate_count':1}),
    ('packing', {'selected_count':1,'status':'other','context_characters':1}),
])
def test_sensitive_or_invalid_stage_payload_rejected(stage, data):
    trace = TraceContext()
    with pytest.raises(TraceError, match='^invalid_trace$'): trace.record_stage(stage, data)
    assert trace.to_legacy_stages() == []


@pytest.mark.parametrize('elapsed', [-1, True, float('nan'), float('inf'), '1'])
def test_invalid_explicit_timings_rejected(elapsed):
    trace = TraceContext()
    with pytest.raises(TraceError): trace.record_stage('request', {'status':'validated'}, elapsed_ms=elapsed)


@pytest.mark.parametrize('change', [
    {'query':'secret'}, {'schema_version':True}, {'trace_id':'secret'}, {'trace_type':'ingestion'},
    {'total_elapsed_ms':float('nan')}, {'status':'other'}, {'error':{'stage':'secret','code':'invalid_query'}},
    {'error':{'stage':'resources','code':'secret'}}, {'finished_at':None}, {'started_at':'secret'},
    {'status':'success'}, {'stages':[{'stage':'request','timestamp':'secret','elapsed_ms':0,'data':{'status':'validated'}}]},
])
def test_collector_validates_report_before_io(tmp_path, change):
    collector = TraceCollector(tmp_path / 'events.jsonl')
    invalid = report() | change
    with pytest.raises(TraceError): collector.collect(invalid)
    assert not collector.path.exists()


def test_real_append_and_independent_json_readback(tmp_path):
    path = tmp_path / 'nested/events.jsonl'
    collector = TraceCollector(path)
    first = report(); second = report()
    collector.collect(first)
    before = path.read_bytes()
    collector.collect(second)
    assert path.read_bytes().startswith(before)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows == [first, second] and rows[0]['trace_id'] != rows[1]['trace_id']
    assert validate_trace_report(rows[0]) is None
    assert collector.path == path.resolve()


def test_validation_rejects_non_mapping_and_nested_mutations(tmp_path):
    collector = TraceCollector(tmp_path / 'events.jsonl')
    for value in [None, [], 'secret']:
        with pytest.raises(TraceError): collector.collect(value)
    data = report(); data['stages'][0]['data']['body'] = 'secret'
    with pytest.raises(TraceError): collector.collect(data)
    assert not collector.path.exists()


def test_init_path_failure_safe_before_query(tmp_path, caplog):
    blocker = tmp_path / 'SYNTHETIC_PRIVATE_PATH'; blocker.write_text('existing')
    with caplog.at_level(logging.ERROR), pytest.raises(TraceError, match='^trace_write_failed$') as caught:
        TraceCollector(blocker / 'events.jsonl')
    assert 'SYNTHETIC_PRIVATE_PATH' not in caplog.text + ''.join(traceback.format_exception(caught.value))
    assert blocker.read_text() == 'existing'


def test_write_and_close_errors_observable_and_no_retry(tmp_path, monkeypatch, caplog):
    collector = TraceCollector(tmp_path / 'events.jsonl'); calls = []
    def fail(*args, **kwargs):
        calls.append(args); raise OSError('SYNTHETIC_PROVIDER_SECRET')
    monkeypatch.setattr(Path, 'open', fail)
    with caplog.at_level(logging.ERROR), pytest.raises(TraceError, match='^trace_write_failed$') as caught:
        collector.collect(report())
    assert len(calls) == 1
    assert 'SYNTHETIC_PROVIDER_SECRET' not in caplog.text + ''.join(traceback.format_exception(caught.value))
    assert 'code=trace_write_failed' in caplog.text


def test_short_write_is_not_reported_as_success(tmp_path, monkeypatch):
    collector = TraceCollector(tmp_path / 'events.jsonl')
    class ShortWriter:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def write(self, text): return len(text) - 1
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: ShortWriter())
    with pytest.raises(TraceError, match='^trace_write_failed$'): collector.collect(report())


def test_equal_comparison_cannot_bypass_string_type_contract():
    class EqualToEverything:
        def __eq__(self, other): return True
    trace = TraceContext()
    with pytest.raises(TraceError, match='^invalid_trace$'):
        trace.record_stage('request', {'status':EqualToEverything()})
    for key in ['trace_type','status']:
        data = report(); data[key] = EqualToEverything()
        with pytest.raises(TraceError, match='^invalid_trace$'): validate_trace_report(data)
    with pytest.raises(TraceError, match='^invalid_trace$'): trace.finish(EqualToEverything())
