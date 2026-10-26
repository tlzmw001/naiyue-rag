"""Snapshot integrity and exact parity with the original real-vector A2 run."""
import copy
import hashlib
import json
import shutil
import socket
from pathlib import Path

import pytest

from vector_fixtures import config

VECTOR_RUN = Path('data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e')
HYBRID_RUN = Path('data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55')


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)
    monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY', raising=False)


@pytest.fixture
def api():
    from types import SimpleNamespace
    from naiyue_rag.a2_snapshot import load_snapshot
    from naiyue_rag.retrieval import retrieve_once, RetrievalError
    return SimpleNamespace(load_snapshot=load_snapshot, retrieve_once=retrieve_once, RetrievalError=RetrievalError)


def settings(tmp_path):
    cfg = config(tmp_path)
    return {k: cfg[k] for k in ['dataset', 'corpus_run', 'endpoint', 'model', 'dimensions']} | {
        'vector_run': str(VECTOR_RUN.resolve()), 'rrf_k': 60, 'bm25_k1': 1.5, 'bm25_b': .75,
        'bm25_method': 'lucene', 'backend': 'numpy', 'tokenizer_policy': 'zh-search-ascii-ident-v1'}


def allowed(cfg):
    from experiments.vector_index import load_corpus
    return sorted(load_corpus(cfg['corpus_run'], cfg['dataset'])['sources'])


def test_original_four_queries_match_real_cached_a2_exactly(api, tmp_path):
    cfg = settings(tmp_path)
    resource = api.load_snapshot(cfg, allowed(cfg), tmp_path / 'tokenizer')
    vectors = json.loads((VECTOR_RUN / 'query_vectors.json').read_text())
    by_hash = {row['query_sha256']: row['vector'] for row in vectors}
    calls = []
    def cached(query, identity):
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        calls.append(query_hash)
        return {'query_sha256': query_hash, 'embedding_identity': identity,
                'vector': by_hash[query_hash], 'source_kind': 'cached', 'usage': None}
    rows = [json.loads(line) for line in (HYBRID_RUN / 'results.jsonl').read_text().splitlines()]
    for old in rows:
        request = {'query': old['query'], 'scope_document_ids': old['scope_ids'],
                   'exclude_document_ids': old['exclude_ids'], 'candidate_k': 20, 'max_context_chars': 8000}
        new = api.retrieve_once(request, resource, cached)
        for route in ['dense', 'sparse', 'hybrid']:
            for field in ['candidates', 'selected', 'budget_excluded', 'context_text',
                          'context_characters', 'max_context_chars', 'status', 'answerability']:
                assert new[route][field] == old[route][field], (old['task_id'], route, field)
        assert new['union_candidates'] == old['union_candidates']
        assert new['embedding']['source_kind'] == 'cached'
    assert len(calls) == 4


@pytest.mark.parametrize('change', [
    {'dimensions': 1}, {'rrf_k': 61}, {'bm25_k1': 1.4}, {'model': 'other-model'},
    {'api_key': 'not-accepted'}, {'vector_run': '/nonexistent/snapshot'},
])
def test_bad_resource_configuration_or_identity_rejected(api, tmp_path, change):
    cfg = settings(tmp_path)
    ids = allowed(cfg)
    with pytest.raises(api.RetrievalError):
        api.load_snapshot(cfg | change, ids, tmp_path / 'tokenizer')


@pytest.mark.parametrize('ids', [[], ['missing'], ['MOCK-TASK-004'], ['MOCK-CASE-001'] * 2])
def test_authorization_is_explicit_and_valid(api, tmp_path, ids):
    with pytest.raises(api.RetrievalError):
        api.load_snapshot(settings(tmp_path), ids, tmp_path / 'tokenizer')


def test_mutating_callers_configuration_does_not_change_resources(api, tmp_path):
    cfg = settings(tmp_path)
    resource = api.load_snapshot(cfg, allowed(cfg), tmp_path / 'tokenizer')
    original = copy.deepcopy(resource.config)
    cfg['rrf_k'] = 61
    exposed = resource.config
    exposed['model'] = 'changed'
    assert resource.config == original


def test_changed_index_is_rejected_before_embedding(api, tmp_path):
    cfg = settings(tmp_path)
    destination = tmp_path / 'vector-copy'
    shutil.copytree(VECTOR_RUN, destination)
    cfg['vector_run'] = str(destination)
    resource = api.load_snapshot(cfg, allowed(cfg), tmp_path / 'tokenizer')
    (destination / 'index_vectors.jsonl').write_text('corrupted')
    calls = []
    def embed(*args): calls.append(args); raise AssertionError('must not call')
    request = {'query': '新问题', 'scope_document_ids': None, 'exclude_document_ids': [],
               'candidate_k': 20, 'max_context_chars': 8000}
    with pytest.raises(api.RetrievalError):
        api.retrieve_once(request, resource, embed)
    assert calls == []


def test_changed_source_is_rejected_before_embedding(api, tmp_path):
    cfg = settings(tmp_path)
    destination = tmp_path / 'dataset-copy'
    shutil.copytree(cfg['dataset'], destination)
    cfg['dataset'] = str(destination)
    resource = api.load_snapshot(cfg, allowed(cfg), tmp_path / 'tokenizer')
    source = destination / 'knowledge/L0/L0_demo_system.md'
    source.write_text(source.read_text() + '\nsource changed\n')
    calls = []
    def embed(*args): calls.append(args); raise AssertionError('must not call')
    request = {'query': '新问题', 'scope_document_ids': None, 'exclude_document_ids': [],
               'candidate_k': 20, 'max_context_chars': 8000}
    with pytest.raises(api.RetrievalError):
        api.retrieve_once(request, resource, embed)
    assert calls == []
