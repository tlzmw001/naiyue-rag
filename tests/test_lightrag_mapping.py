import copy
import importlib

import pytest

from experiments.vector_index import load_corpus, load_index, make_index_text
from experiments.vector_eval import load_queries
from vector_fixtures import config

VECTOR_RUN = 'data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e'


def inputs(tmp_path):
    cfg = config(tmp_path)
    corpus = load_corpus(cfg['corpus_run'], cfg['dataset'])
    index = load_index(VECTOR_RUN, corpus['fingerprint'], cfg)
    queries = load_queries(cfg['tasks'], corpus)
    return corpus, index, queries


@pytest.fixture
def mod(): return importlib.import_module('experiments.lightrag_mapping')


def test_scope_mapping_keeps_whole_cases_and_original_positions(mod, tmp_path):
    corpus, index, queries = inputs(tmp_path)
    full = mod.make_payload(corpus, index, queries[:2] + queries[3:])
    scoped = mod.make_payload(corpus, index, [queries[2]])
    assert len(full['documents']) == 11 and len(full['units']) == 52
    assert len(scoped['documents']) == 1 and len(scoped['units']) == 10
    assert full['scope_key'] != scoped['scope_key']
    for unit in full['units']:
        original = index['units'][unit['unit_id']]
        assert unit['content'] == make_index_text(original)
        assert unit['body_span'] == original['body_span']
        assert unit['contexts'] == original['contexts']
        assert unit['native_id'] == 'doc-' + original['document_id'] + '-' + original['unit_id']
    assert sum(u['kind'] == 'test_case' for u in full['units']) == 12
    assert 'candidate_required_evidence' not in str(full)


def test_mixed_scope_rejected(mod, tmp_path):
    corpus, index, queries = inputs(tmp_path)
    with pytest.raises(mod.ProbeError, match='mixed_scope'):
        mod.make_payload(corpus, index, queries)


@pytest.mark.parametrize('fault', ['unknown', 'partial', 'duplicate', 'wrong_source', 'nonfinite'])
def test_native_results_cannot_invent_or_expand_evidence(mod, tmp_path, fault):
    corpus, index, queries = inputs(tmp_path)
    payload = mod.make_payload(corpus, index, [queries[2]])
    unit = payload['units'][0]
    raw = [{'id': unit['native_id'], 'distance': .4}]
    chunks = [{'chunk_id': unit['native_id'], 'content': unit['content'], 'file_path': unit['native_file_path']}]
    if fault == 'unknown': chunks[0]['chunk_id'] = 'absent'
    elif fault == 'partial': chunks[0]['content'] = chunks[0]['content'][:10]
    elif fault == 'duplicate': chunks.append(copy.deepcopy(chunks[0]))
    elif fault == 'wrong_source': chunks[0]['file_path'] = 'other.md'
    else: raw[0]['distance'] = float('nan')
    with pytest.raises(mod.ProbeError, match='native_query_mismatch'):
        mod.map_results(payload, raw, chunks, index, 20)


def test_native_order_and_cosine_are_preserved(mod, tmp_path):
    corpus, index, queries = inputs(tmp_path)
    payload = mod.make_payload(corpus, index, [queries[2]])
    selected = payload['units'][3:5][::-1]
    raw = [{'id': u['native_id'], 'distance': .8 - i*.1} for i,u in enumerate(selected)]
    chunks = [{'chunk_id': u['native_id'], 'content': u['content'], 'file_path': u['native_file_path']} for u in selected]
    result = mod.map_results(payload, raw, chunks, index, 20)
    assert [r['unit_id'] for r in result] == [u['unit_id'] for u in selected]
    assert [r['score'] for r in result] == [.8, .8-.1]
    assert mod.map_results(payload, [], [], index, 20) == []
