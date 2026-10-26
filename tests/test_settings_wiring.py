"""Actual YAML-to-snapshot consumers and cached retrieval, no live model."""
import hashlib
import json
import shutil
import socket

import pytest

from naiyue_rag.bootstrap import load_snapshot_from_settings
from naiyue_rag.retrieval import retrieve_once, RetrievalError
from naiyue_rag.core.errors import SettingsError
from test_settings import configuration, write_settings
from test_a2_snapshot import VECTOR_RUN, HYBRID_RUN, settings
from test_retrieval_once import request, provider


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)
    monkeypatch.delenv('NAIYUE_RAG_ZHIPU_API_KEY', raising=False)


def test_actual_settings_reach_existing_resource_loader(tmp_path, monkeypatch):
    from naiyue_rag import bootstrap
    original = bootstrap.load_snapshot; observed = []
    def observe(config, ids, cache):
        observed.append((config, ids, str(cache)))
        return original(config, ids, cache)
    monkeypatch.setattr(bootstrap, 'load_snapshot', observe)
    path = write_settings(tmp_path)
    resource = load_snapshot_from_settings(path)
    assert observed[0][0] == settings(tmp_path)
    assert len(observed[0][1]) == 11
    assert observed[0][2] == str(tmp_path / 'tokenizer')
    assert len(resource.canonical_units()) == 52
    assert resource.resolve_scope(None, []) is None
    assert resource.embedding_identity['model'] == 'embedding-3'
    assert (tmp_path / 'tokenizer/jieba.cache').is_file()


def test_full_library_and_task_filters_apply_to_both_routes(tmp_path):
    resource = load_snapshot_from_settings(write_settings(tmp_path))
    all_result = retrieve_once(request(exclude_document_ids=[]), resource, provider([]))
    assert all_result['scope_document_ids'] is None
    assert all_result['dense']['compared_count'] == 52
    assert all_result['sparse']['compared_count'] == 52
    filtered = retrieve_once(request(scope_document_ids=['MOCK-CASE-001'], exclude_document_ids=[]),
                             resource, provider([]))
    for route in ['dense','sparse','hybrid']:
        assert filtered[route]['candidates']
        assert all(row['document_id'] == 'MOCK-CASE-001' for row in filtered[route]['candidates'])
    excluded = retrieve_once(request(exclude_document_ids=['MOCK-CASE-001']), resource, provider([]))
    for route in ['dense','sparse','hybrid']:
        assert all(row['document_id'] != 'MOCK-CASE-001' for row in excluded[route]['candidates'])
    calls = []
    with pytest.raises(RetrievalError, match='invalid_scope'):
        retrieve_once(request(scope_document_ids=['missing']), resource, provider(calls))
    assert calls == []


def test_yaml_entry_matches_original_four_cached_queries(tmp_path):
    resource = load_snapshot_from_settings(write_settings(tmp_path))
    by_hash = {row['query_sha256']:row['vector'] for row in
               json.loads((VECTOR_RUN / 'query_vectors.json').read_text())}
    calls = []
    def cached(query, identity):
        key = hashlib.sha256(query.encode()).hexdigest(); calls.append(key)
        return {'query_sha256':key, 'embedding_identity':identity,
                'vector':by_hash[key], 'source_kind':'cached', 'usage':None}
    rows = [json.loads(line) for line in (HYBRID_RUN / 'results.jsonl').read_text().splitlines()]
    for old in rows:
        result = retrieve_once(request(query=old['query'],scope_document_ids=old['scope_ids'],
                                       exclude_document_ids=old['exclude_ids']), resource, cached)
        for route in ['dense','sparse','hybrid']:
            for key in ['candidates','selected','budget_excluded','context_text','context_characters',
                        'max_context_chars','status','answerability']:
                assert result[route][key] == old[route][key], (old['task_id'],route,key)
        assert result['union_candidates'] == old['union_candidates']
        assert result['embedding']['source_kind'] == 'cached'
    assert len(calls) == 4


@pytest.mark.parametrize('field,value', [('model','other-model'),('dimensions',1)])
def test_config_identity_mismatch_fails_before_tokenizer(tmp_path, field, value):
    raw = configuration(tmp_path); raw['embedding'][field] = value
    with pytest.raises(RetrievalError): load_snapshot_from_settings(write_settings(tmp_path, raw))
    assert not (tmp_path / 'tokenizer').exists()


def test_invalid_yaml_fails_before_any_resource_loading(tmp_path, monkeypatch):
    from naiyue_rag import bootstrap
    calls = []
    def forbid(*args, **kwargs): calls.append(args); raise AssertionError('must not load')
    monkeypatch.setattr(bootstrap, 'load_corpus', forbid)
    monkeypatch.setattr(bootstrap, 'load_snapshot', forbid)
    path = tmp_path / 'bad.yaml'; path.write_text('unknown: value')
    with pytest.raises(SettingsError): load_snapshot_from_settings(path)
    assert calls == [] and not (tmp_path / 'tokenizer').exists()


def test_corrupt_source_loading_is_explicit_and_safe(tmp_path, caplog):
    raw = configuration(tmp_path)
    raw['snapshot']['dataset'] = str(tmp_path / 'SYNTHETIC_PRIVATE_MISSING_PATH')
    with pytest.raises(RetrievalError) as caught:
        load_snapshot_from_settings(write_settings(tmp_path, raw))
    assert caught.value.stage == 'resources'
    assert 'snapshot_failed stage=resources code=' in caplog.text
    assert 'SYNTHETIC_PRIVATE_MISSING_PATH' not in caplog.text + str(caught.value)
    assert not (tmp_path / 'tokenizer').exists()


def test_index_changes_still_fail_before_embedding(tmp_path):
    raw = configuration(tmp_path); destination = tmp_path / 'index-copy'
    shutil.copytree(VECTOR_RUN, destination)
    raw['snapshot']['vector_run'] = str(destination)
    resource = load_snapshot_from_settings(write_settings(tmp_path, raw))
    (destination / 'index_vectors.jsonl').write_text('corrupt')
    calls = []
    with pytest.raises(RetrievalError): retrieve_once(request(), resource, provider(calls))
    assert calls == []


def test_existing_cache_fails_without_overwrite(tmp_path):
    cache = tmp_path / 'tokenizer'; cache.mkdir()
    sentinel = cache / 'existing.txt'; sentinel.write_text('existing')
    with pytest.raises(RetrievalError, match='tokenizer_error'):
        load_snapshot_from_settings(write_settings(tmp_path))
    assert sentinel.read_text() == 'existing'
    assert not (cache / 'jieba.cache').exists()


def test_custom_cache_path_is_really_consumed(tmp_path):
    raw = configuration(tmp_path); raw['runtime']['tokenizer_cache_dir'] = 'alternate/cache'
    load_snapshot_from_settings(write_settings(tmp_path, raw))
    assert (tmp_path / 'alternate/cache/jieba.cache').is_file()
    assert not (tmp_path / 'tokenizer').exists()
