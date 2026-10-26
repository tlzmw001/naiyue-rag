"""Native subprocess integration and unchanged keyword/evidence baseline."""
import copy
import json
from pathlib import Path

import pytest

from experiments.chroma_probe import run, launch_worker
from experiments.embedding_probe import ProbeError
from experiments.vector_index import read_rows

BASELINE = Path('data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55')


def config(tmp_path):
    cfg = json.loads((BASELINE/'summary.json').read_text())['config']
    return {**cfg, 'keyword_run':str(BASELINE.resolve()),
            'output_root':str(tmp_path), 'collection_name':'knowledge_hub',
            'runtime_lock':str(Path('requirements-chroma.lock.txt').resolve()),
            'worker_timeout_seconds':60, 'deadline_seconds':180}


@pytest.fixture(scope='module')
def native_result(tmp_path_factory):
    return run(config(tmp_path_factory.mktemp('native-chroma')))


def test_real_native_persistence_and_guards(native_result):
    assert native_result['status'] == 'complete', native_result.get('sanitized_error')
    build, query = native_result['workers']['build'], native_result['workers']['query']
    assert build['pid'] != query['pid']
    assert build['count'] == build['repeat_count'] == query['count'] == 52
    assert query['audit']['unit_count'] == 52
    assert query['audit']['max_vector_error'] <= 1e-6
    assert query['settings']['allow_reset'] is False
    assert query['settings']['anonymized_telemetry'] is False
    assert query['configuration']['hnsw']['space'] == 'cosine'
    assert query['configuration']['embedding_function'] is None
    assert query['reset_denied'] and query['missing_collection_denied']
    assert query['creation_calls'] == 0 and query['upsert_calls'] == 0
    assert all(w['trace']['python_network_attempts'] == 0 for w in [build,query])
    assert native_result['attempt_count'] == 0


def test_fixed_two_profiles_and_source_evidence(native_result):
    assert native_result['status'] == 'complete'
    root = Path(native_result['output_dir'])
    rows = read_rows(root/'results.jsonl')
    old = {row['task_id']:row for row in read_rows(BASELINE/'results.jsonl')}
    assert len(rows) == 4
    for row in rows:
        assert row['sparse'] == old[row['task_id']]['sparse']
        assert row['distance_audit']['max_error'] <= 1e-6
        for name, limit in [('a2',20),('reference',10)]:
            result = row['profiles'][name]
            assert len(result['candidates']) <= limit
            assert result['context_characters'] <= 8000
            assert result['answerability'] == 'unknown'
            for unit in result['selected']:
                canonical = native_result['source_units'][unit['unit_id']]
                assert all(unit[k] == v for k,v in canonical.items())
        if row['task_id'] == 'Q03':
            assert row['dense']['compared_count'] == 10
            assert {u['document_id'] for u in row['dense']['candidates']} == {'MOCK-CASE-001'}


def test_worker_identity_mismatch_is_not_empty(tmp_path, native_result):
    assert native_result['status'] == 'complete'
    job = copy.deepcopy(native_result['worker_job'])
    job['store_config']['embedding_identity']['model'] = 'different'
    with pytest.raises(ProbeError, match='collection_mismatch'):
        launch_worker(job, 'query', tmp_path/'mismatch', 60)


def test_worker_timeout_is_observable(tmp_path):
    with pytest.raises(ProbeError, match='worker_timeout'):
        launch_worker({}, 'query', tmp_path, 0)


def test_invalid_config_fails_before_worker(tmp_path, monkeypatch):
    import experiments.chroma_probe as probe
    calls=[]; monkeypatch.setattr(probe,'launch_worker',lambda *a: calls.append(a))
    cfg = config(tmp_path); cfg['collection_name'] = '../unsafe'
    with pytest.raises(ProbeError, match='invalid_chroma_config'): run(cfg)
    assert calls == []


def test_reset_io_failure_cannot_be_reported_as_denial(tmp_path, monkeypatch):
    """Expected security denial and unexpected IO failure are distinct outcomes."""
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock
    import experiments.chroma_worker as worker
    monkeypatch.chdir(tmp_path)
    class NotFoundError(Exception): pass
    class AuthorizationError(Exception): pass
    monkeypatch.setitem(sys.modules,'chromadb.api.client',SimpleNamespace(Client=type('Client',(),{})))
    monkeypatch.setitem(sys.modules,'chromadb.api.models.Collection',SimpleNamespace(Collection=type('Collection',(),{})))
    monkeypatch.setitem(sys.modules,'chromadb.errors',SimpleNamespace(NotFoundError=NotFoundError,AuthorizationError=AuthorizationError))
    client=Mock()
    client.get_settings.return_value=SimpleNamespace(allow_reset=False,anonymized_telemetry=False)
    client.reset.side_effect=OSError('unexpected IO failure')
    client.get_collection.side_effect=NotFoundError()
    store=SimpleNamespace(client=client,count=lambda:0,
        collection=SimpleNamespace(configuration={'hnsw':{'space':'cosine'},'embedding_function':None}))
    monkeypatch.setattr(worker,'ChromaStore',lambda *a,**kw:store)
    monkeypatch.setattr(worker,'verify_runtime',lambda *a:{})
    monkeypatch.setattr(worker,'load_corpus',lambda *a:{'fingerprint':'c'})
    monkeypatch.setattr(worker,'load_index',lambda *a:{'query_hashes':{},'units':{},'vectors':{}})
    monkeypatch.setattr(worker,'load_queries',lambda *a:[])
    monkeypatch.setattr(worker,'audit',lambda *a:{'unit_count':0})
    job={'runtime_lock':'unused','config':dict.fromkeys(['corpus_run','dataset','vector_run','tasks'],'unused'),
         'action':'query','store_config':{'collection_name':'knowledge_hub'}}
    with pytest.raises(ProbeError,match='reset_check_failed'):
        worker.execute(job,[0])
