"""Offline request, scope and evidence contracts; fake vectors are not service results."""
import copy
import hashlib
import json
import socket

import pytest

from vector_fixtures import config, vector


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)
    monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY', raising=False)


@pytest.fixture
def api():
    from types import SimpleNamespace
    from naiyue_rag.a2_snapshot import load_snapshot
    from naiyue_rag.retrieval import retrieve_once, RetrievalError
    return SimpleNamespace(load_snapshot=load_snapshot, retrieve_once=retrieve_once, RetrievalError=RetrievalError)


@pytest.fixture
def resource_config(tmp_path):
    from experiments.vector_index import load_corpus, write_index
    cfg = config(tmp_path)
    corpus = load_corpus(cfg['corpus_run'], cfg['dataset'])
    folder = tmp_path / 'vectors'
    folder.mkdir()
    write_index(folder, corpus, [], [vector(i) for i in range(len(corpus['units']))], [], cfg)
    return {k: cfg[k] for k in ['dataset', 'corpus_run', 'endpoint', 'model', 'dimensions']} | {
        'vector_run': str(folder), 'rrf_k': 60, 'bm25_k1': 1.5, 'bm25_b': .75,
        'bm25_method': 'lucene', 'backend': 'numpy', 'tokenizer_policy': 'zh-search-ascii-ident-v1'}


@pytest.fixture
def resources(api, resource_config, tmp_path):
    from experiments.vector_index import load_corpus
    corpus = load_corpus(resource_config['corpus_run'], resource_config['dataset'])
    return api.load_snapshot(resource_config, sorted(corpus['sources']), tmp_path / 'tokenizer')


def request(**changes):
    return {'query': '请解释联合模型的历史前置条件', 'scope_document_ids': None,
            'exclude_document_ids': ['MOCK-TASK-004'], 'candidate_k': 20,
            'max_context_chars': 8000} | changes


def provider(calls, alter=None):
    def embed(query, identity):
        calls.append((query, copy.deepcopy(identity)))
        result = {'query_sha256': hashlib.sha256(query.encode()).hexdigest(),
                  'embedding_identity': copy.deepcopy(identity), 'vector': vector(),
                  'source_kind': 'simulated', 'usage': None}
        if alter:
            alter(result)
        return result
    return embed


def test_new_query_without_task_or_query_vector_cache(api, resources):
    calls = []
    result = api.retrieve_once(request(), resources, provider(calls))
    assert len(calls) == 1
    assert calls[0][0] == request()['query']
    assert result['query'] == request()['query']
    assert result['status'] == 'retrieved' and result['answerability'] == 'unknown'
    assert result['dense']['compared_count'] == result['sparse']['compared_count'] == 52
    assert result['selected'] == result['hybrid']['selected']
    assert result['context_characters'] <= 8000
    assert result['embedding_adapter_calls'] == 1
    assert result['embedding']['source_kind'] == 'simulated'
    assert result['embedding']['usage'] is None
    assert [row['stage'] for row in result['trace']] == [
        'request', 'resources', 'embedding', 'dense', 'sparse', 'fusion', 'packing']
    assert all(row['elapsed_ms'] >= 0 for row in result['trace'])
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('changes', [
    {'query': ''}, {'query': '  '}, {'query': None}, {'query': '\ud800'},
    {'query': '汉' * 1025}, {'scope_document_ids': []},
    {'scope_document_ids': ['missing']}, {'scope_document_ids': ['MOCK-TASK-004']},
    {'scope_document_ids': ['MOCK-CASE-001', 'MOCK-CASE-001']},
    {'exclude_document_ids': ['missing']}, {'exclude_document_ids': None},
    {'candidate_k': True}, {'candidate_k': 0}, {'candidate_k': 21},
    {'max_context_chars': False}, {'max_context_chars': 0}, {'max_context_chars': 8001},
    {'extra': 'not permitted'},
])
def test_invalid_request_rejected_before_embedding(api, resources, changes):
    calls = []
    with pytest.raises(api.RetrievalError):
        api.retrieve_once(request(**changes), resources, provider(calls))
    assert calls == []


def test_authorized_subset_controls_both_routes_and_statistics(api, resource_config, tmp_path):
    resource = api.load_snapshot(resource_config, ['MOCK-CASE-001'], tmp_path / 'subset-tokenizer')
    calls = []
    result = api.retrieve_once(request(), resource, provider(calls))
    assert result['scope_document_ids'] == ['MOCK-CASE-001']
    assert result['dense']['compared_count'] == result['sparse']['compared_count'] == 10
    assert {row['document_id'] for row in result['hybrid']['candidates']} == {'MOCK-CASE-001'}
    calls.clear()
    with pytest.raises(api.RetrievalError, match='invalid_scope'):
        api.retrieve_once(request(scope_document_ids=['MOCK-L0-001']), resource, provider(calls))
    assert calls == []


@pytest.mark.parametrize('fault', ['hash', 'identity', 'dimension', 'nan', 'zero', 'kind', 'usage'])
def test_embedding_binding_and_values_must_match(api, resources, fault):
    def alter(result):
        if fault == 'hash': result['query_sha256'] = 'wrong'
        elif fault == 'identity': result['embedding_identity']['policy_id'] = 'different'
        elif fault == 'dimension': result['vector'] = [1.0]
        elif fault == 'nan': result['vector'][0] = float('nan')
        elif fault == 'zero': result['vector'] = [0.0] * 2048
        elif fault == 'kind': result['source_kind'] = 'proven_correct'
        else: result['usage'] = {'prompt_tokens': -1, 'total_tokens': -1}
    with pytest.raises(api.RetrievalError, match='invalid_query_embedding'):
        api.retrieve_once(request(), resources, provider([], alter))


def test_callback_failure_is_observable_and_not_empty(api, resources, caplog):
    def fail(query, identity):
        raise OSError('secret-provider-body')
    with pytest.raises(api.RetrievalError, match='embedding_failed') as error:
        api.retrieve_once(request(), resources, fail)
    assert error.value.stage == 'embedding'
    assert 'embedding_failed' in caplog.text
    assert 'secret-provider-body' not in str(error.value) + caplog.text


def test_empty_pool_and_budget_exclusion_are_distinct(api, resources):
    from experiments.vector_index import load_corpus
    cfg = resources.config
    corpus = load_corpus(cfg['corpus_run'], cfg['dataset'])
    empty = api.retrieve_once(request(exclude_document_ids=sorted(corpus['sources'])), resources, provider([]))
    assert empty['status'] == 'empty' and empty['selected'] == []
    tiny = api.retrieve_once(request(max_context_chars=1), resources, provider([]))
    assert tiny['status'] == 'no_evidence_fits' and tiny['selected'] == []
    assert tiny['budget_excluded'] and tiny['answerability'] == 'unknown'


def test_result_mutation_cannot_corrupt_snapshot(api, resources):
    first = api.retrieve_once(request(), resources, provider([]))
    expected = copy.deepcopy(first['selected'])
    first['selected'][0]['body'] = 'changed by caller'
    first['selected'][0]['contexts'].clear()
    second = api.retrieve_once(request(), resources, provider([]))
    assert second['selected'] == expected


def test_case_body_and_location_survive_packing(api, resources):
    result = api.retrieve_once(request(scope_document_ids=['MOCK-CASE-001']), resources, provider([]))
    cases = [row for row in result['selected'] if row['kind'] == 'test_case']
    assert cases
    for row in cases:
        assert row['body'].startswith('|') and row['case_fields'][0] == row['case_id']
        assert row['body'] in row['rendered_text']
        assert row['body_span']['line_start'] == row['body_span']['line_end']
        assert row['source_sha256'] and row['contexts']


def test_retrieval_does_not_load_task_labels(api, resources, monkeypatch):
    import experiments.vector_eval as evaluation
    def forbidden(*args, **kwargs): raise AssertionError('labels must not be consumed')
    monkeypatch.setattr(evaluation, 'load_queries', forbidden)
    monkeypatch.setattr(evaluation, 'load_labels', forbidden)
    assert api.retrieve_once(request(), resources, provider([]))['selected']
