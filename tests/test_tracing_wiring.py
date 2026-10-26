"""Actual A2 stages and persistence success/failure, without live providers."""
import json
from pathlib import Path
import socket
from uuid import UUID

import pytest

from naiyue_rag.retrieval import retrieve_once, RetrievalError
from naiyue_rag.tracing import retrieve_with_trace
from naiyue_rag.core.errors import ContractError, TraceError
from naiyue_rag.core.trace_context import TraceContext, validate_trace_report
from naiyue_rag.core.trace_collector import TraceCollector
from experiments.embedding_probe import ProbeError
from test_retrieval_once import api, resource_config, resources, request, provider
from test_a2_snapshot import VECTOR_RUN, HYBRID_RUN, settings, allowed


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)
    monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY', raising=False)


def test_real_seven_stages_and_success_report(resources, tmp_path, monkeypatch):
    original = TraceContext.record_stage; stages = []
    existing_jsonl = set(tmp_path.rglob('*.jsonl'))
    def observe(self, name, data, **kwargs):
        stages.append(name); return original(self, name, data, **kwargs)
    monkeypatch.setattr(TraceContext, 'record_stage', observe)
    result = retrieve_once(request(), resources, provider([]))
    report = result['trace_report']; validate_trace_report(report)
    assert stages == ['request','resources','embedding','dense','sparse','fusion','packing']
    assert [row['stage'] for row in report['stages']] == stages
    assert UUID(report['trace_id']).version == 4
    assert report['status'] == 'success' and report['error'] is None
    assert report['total_elapsed_ms'] >= 0
    assert report['stages'][2]['data']['usage'] is None
    assert [row['elapsed_ms'] for row in report['stages']] == [row['elapsed_ms'] for row in result['trace']]
    assert set(tmp_path.rglob('*.jsonl')) == existing_jsonl


def test_jsonl_written_matches_result_report(resources, tmp_path):
    collector = TraceCollector(tmp_path / 'traces/events.jsonl')
    result = retrieve_with_trace(request(), resources, provider([]), collector)
    assert result['selected']
    assert result['trace_persistence'] == {'status':'written','code':None}
    assert json.loads(collector.path.read_text()) == result['trace_report']


def test_invalid_request_has_report_and_persists_before_embedding(resources, tmp_path):
    calls = []; collector = TraceCollector(tmp_path / 'events.jsonl')
    with pytest.raises(RetrievalError, match='invalid_query') as caught:
        retrieve_with_trace(request(query=''), resources, provider(calls), collector)
    error = caught.value; report = error.trace_report
    assert calls == [] and report['stages'] == []
    assert report['status'] == 'error' and report['error'] == {'stage':'request','code':'invalid_query'}
    assert error.trace_persistence == {'status':'written','code':None}
    assert json.loads(collector.path.read_text()) == report
    assert str(error) == 'request: invalid_query'


def test_invalid_resources_has_report_before_embedding():
    calls = []
    with pytest.raises(RetrievalError, match='invalid_resources') as caught:
        retrieve_once(request(), object(), provider(calls))
    assert calls == [] and caught.value.trace_report['stages'] == []
    assert caught.value.trace_report['error'] == {'stage':'resources','code':'invalid_resources'}


@pytest.mark.parametrize('stage', ['resources','embedding','dense','sparse','fusion','packing'])
def test_stage_failure_preserves_completed_prefix(resources, monkeypatch, stage):
    import naiyue_rag.retrieval as module
    calls = []
    def fail(*args, **kwargs): raise OSError('SYNTHETIC_RAW_ERROR')
    embed = provider(calls)
    if stage == 'resources': monkeypatch.setattr(resources, 'verify_current', fail)
    elif stage == 'embedding': embed = fail
    elif stage in ['dense','sparse']: monkeypatch.setattr(resources, stage, fail)
    elif stage == 'fusion': monkeypatch.setattr(module, 'fuse', fail)
    else: monkeypatch.setattr(module, 'pack_evidence', fail)
    with pytest.raises(RetrievalError) as caught: retrieve_once(request(), resources, embed)
    report = caught.value.trace_report
    order = ['request','resources','embedding','dense','sparse','fusion','packing']
    assert [row['stage'] for row in report['stages']] == order[:order.index(stage)]
    assert report['error']['stage'] == stage and report['status'] == 'error'
    assert 'SYNTHETIC_RAW_ERROR' not in json.dumps(report)
    assert len(calls) == (0 if stage in ['resources','embedding'] else 1)


@pytest.mark.parametrize('failure', [ProbeError('keyword','keyword_query_error'),
                                   ContractError('invalid_result'), RetrievalError('dense','invalid_candidates')])
def test_known_errors_have_safe_reports_and_original_identity(resources, monkeypatch, failure):
    def fail(*args): raise failure
    monkeypatch.setattr(resources, 'dense', fail)
    with pytest.raises(RetrievalError) as caught: retrieve_once(request(), resources, provider([]))
    assert caught.value.trace_report['error']['code'] in ['keyword_query_error','invalid_result','invalid_candidates']
    if isinstance(failure, RetrievalError): assert caught.value is failure


def test_unknown_error_codes_are_safe_in_logs_and_report(resources, monkeypatch, caplog):
    original = RetrievalError('dense','SYNTHETIC_PRIVATE_CODE')
    def fail(*args): raise original
    monkeypatch.setattr(resources, 'dense', fail)
    with pytest.raises(RetrievalError) as caught: retrieve_once(request(), resources, provider([]))
    assert caught.value is original
    assert caught.value.trace_report['error'] == {'stage':'dense','code':'unknown_failure'}
    assert 'SYNTHETIC_PRIVATE_CODE' not in caplog.text
    assert caught.value.trace_report['trace_id'] in caplog.text


def test_write_failure_keeps_success_and_marks_persistence(resources, tmp_path, monkeypatch):
    collector = TraceCollector(tmp_path / 'events.jsonl'); calls = []
    def fail(report): calls.append(report); raise TraceError('trace_write_failed')
    monkeypatch.setattr(collector, 'collect', fail)
    result = retrieve_with_trace(request(), resources, provider([]), collector)
    assert result['selected'] and result['status'] == 'retrieved'
    assert result['trace_report']['status'] == 'success'
    assert result['trace_persistence'] == {'status':'failed','code':'trace_write_failed'}
    assert len(calls) == 1


@pytest.mark.parametrize('fault', ['open','write','close'])
def test_real_io_boundary_failure_preserves_result(resources, tmp_path, monkeypatch, caplog, fault):
    collector = TraceCollector(tmp_path / 'events.jsonl'); original = Path.open; calls = []
    class FailingWriter:
        def __enter__(self): return self
        def __exit__(self, *args):
            if fault == 'close': raise OSError('SYNTHETIC_IO_SECRET')
            return False
        def write(self, text):
            if fault == 'write': raise OSError('SYNTHETIC_IO_SECRET')
            return len(text)
    def open_file(path, *args, **kwargs):
        if path == collector.path:
            calls.append(path)
            if fault == 'open': raise OSError('SYNTHETIC_IO_SECRET')
            return FailingWriter()
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', open_file)
    result = retrieve_with_trace(request(), resources, provider([]), collector)
    assert result['selected'] and result['trace_report']['status'] == 'success'
    assert result['trace_persistence'] == {'status':'failed','code':'trace_write_failed'}
    assert len(calls) == 1
    assert 'SYNTHETIC_IO_SECRET' not in caplog.text
    assert result['trace_report']['trace_id'] in caplog.text


def test_double_failure_does_not_mask_retrieval_error(resources, tmp_path, monkeypatch):
    collector = TraceCollector(tmp_path / 'events.jsonl')
    original = RetrievalError('dense','invalid_candidates')
    def retrieval_fail(*args): raise original
    def write_fail(report): raise TraceError('trace_write_failed')
    monkeypatch.setattr(resources, 'dense', retrieval_fail)
    monkeypatch.setattr(collector, 'collect', write_fail)
    with pytest.raises(RetrievalError) as caught:
        retrieve_with_trace(request(), resources, provider([]), collector)
    assert caught.value is original and str(caught.value) == 'dense: invalid_candidates'
    assert caught.value.trace_persistence == {'status':'failed','code':'trace_write_failed'}
    assert caught.value.trace_report['status'] == 'error'


def test_legacy_usage_extensions_not_leaked_to_safe_trace(resources, tmp_path, caplog):
    sentinel = 'SYNTHETIC_PRIVATE_USAGE_NOTE'
    def alter(payload):
        payload['usage'] = {'prompt_tokens':2,'total_tokens':2,'private_note':sentinel}
    collector = TraceCollector(tmp_path / 'events.jsonl')
    result = retrieve_with_trace(request(query=sentinel), resources, provider([], alter), collector)
    assert result['trace'][2]['usage']['private_note'] == sentinel
    assert result['embedding']['usage']['private_note'] == sentinel
    assert sentinel not in json.dumps(result['trace_report']) + collector.path.read_text() + caplog.text


def test_empty_and_no_fit_are_successful_queries(resources):
    empty = retrieve_once(request(exclude_document_ids=sorted(resources._documents)), resources, provider([]))
    small = retrieve_once(request(max_context_chars=1), resources, provider([]))
    assert empty['status'] == 'empty' and small['status'] == 'no_evidence_fits'
    assert empty['trace_report']['status'] == small['trace_report']['status'] == 'success'


def test_four_queries_preserve_baseline_and_write_four_reports(tmp_path, api):
    import hashlib
    cfg = settings(tmp_path); resource = api.load_snapshot(cfg, allowed(cfg), tmp_path / 'tokenizer')
    vectors = {row['query_sha256']:row['vector'] for row in json.loads((VECTOR_RUN/'query_vectors.json').read_text())}
    collector = TraceCollector(tmp_path / 'events.jsonl')
    def cached(query, identity):
        key = hashlib.sha256(query.encode()).hexdigest()
        return {'query_sha256':key,'embedding_identity':identity,'vector':vectors[key],
                'source_kind':'cached','usage':None}
    old_rows = [json.loads(line) for line in (HYBRID_RUN/'results.jsonl').read_text().splitlines()]
    results = []
    for old in old_rows:
        result = retrieve_with_trace(request(query=old['query'],scope_document_ids=old['scope_ids'],
                                             exclude_document_ids=old['exclude_ids']), resource, cached, collector)
        results.append(result)
        for route in ['dense','sparse','hybrid']:
            for key in ['candidates','selected','budget_excluded','context_text','context_characters',
                        'max_context_chars','status','answerability']:
                assert result[route][key] == old[route][key], (old['task_id'],route,key)
        assert result['union_candidates'] == old['union_candidates']
    persisted = [json.loads(line) for line in collector.path.read_text().splitlines()]
    assert persisted == [result['trace_report'] for result in results]
    assert len({row['trace_id'] for row in persisted}) == 4
