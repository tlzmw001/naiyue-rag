"""Contract tests with injected SDK doubles; not native database evidence."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from naiyue_rag.chroma_store import ChromaStore
from naiyue_rag.retrieval import RetrievalError


def units():
    return {f'u{i}': {'unit_id': f'u{i}', 'document_id': f'd{i}', 'source_sha256': f'v{i}',
        'role': 'test_case' if i == 1 else 'requirement', 'kind': 'test_case' if i == 1 else 'text',
        'body': f'正文 {i} | 前置条件 <br> 步骤', 'contexts': [{'text': '维度说明', 'span': {'line_start': 1}}],
        'body_span': {'line_start': 3, 'line_end': 3}, 'case_fields': ['TC-01', '前置条件']}
        for i in [1, 2]}


def settings(tmp_path):
    return {'persist_directory': str(tmp_path/'database'), 'collection_name': 'knowledge_hub',
        'embedding_identity': {'endpoint': 'mock://explicit', 'model': 'mock', 'dimensions': 3,
                               'policy_id': 'context-body-v1'}, 'corpus_id': 'corpus', 'index_id': 'index',
        'authorized_document_ids': ['d1', 'd2'], 'excluded_document_ids': ['new-task']}


@pytest.fixture
def sdk():
    records = {}
    collection = Mock()
    collection.configuration = {'hnsw': {'space': 'cosine'}, 'embedding_function': None}
    def upsert(**kw):
        for uid, vector, metadata, document in zip(kw['ids'], kw['embeddings'], kw['metadatas'], kw['documents'], strict=True):
            records[uid] = (vector, metadata, document)
    def get(**kw):
        ids = list(reversed(kw['ids']))
        return {'ids': ids, 'embeddings': [records[i][0] for i in ids],
                'metadatas': [records[i][1] for i in ids], 'documents': [records[i][2] for i in ids]}
    collection.upsert.side_effect = upsert
    collection.get.side_effect = get
    collection.count.side_effect = lambda: len(records)
    client = Mock()
    def create(**kw):
        collection.metadata = kw['metadata']
        return collection
    client.get_or_create_collection.side_effect = create
    client.get_collection.side_effect = lambda **kw: collection
    return SimpleNamespace(client=client, collection=collection, records=records)


@pytest.fixture
def store(tmp_path, sdk):
    result = ChromaStore(settings(tmp_path), units(), create=True, client=sdk.client)
    result.upsert({'u1': [1., 0., 0.], 'u2': [0., 1., 0.]})
    return result


def response(sdk, uid='u1', distance=0.):
    _, metadata, document = sdk.records[uid]
    return {'ids': [[uid]], 'distances': [[distance]], 'metadatas': [[copy.deepcopy(metadata)]],
            'documents': [[document]]}


def test_explicit_vectors_lossless_metadata_and_repeat(store, sdk):
    store.upsert({'u1': [1., 0., 0.]})
    assert store.count() == 2
    assert store.get_by_ids(['u1', 'u2'])['u1']['unit'] == units()['u1']
    assert store.get_by_ids(['u2', 'u1'])['u2']['unit'] == units()['u2']
    call = sdk.client.get_or_create_collection.call_args.kwargs
    assert call['embedding_function'] is None
    assert call['configuration'] == {'hnsw': {'space': 'cosine'}}
    assert json.loads(call['metadata']['embedding_identity']) == {
        'endpoint':'mock://explicit', 'model':'mock', 'dimensions':3, 'policy_id':'context-body-v1'}
    assert sdk.records['u1'][1]['canonical_json'] == json.dumps(units()['u1'], ensure_ascii=False, sort_keys=True, allow_nan=False)


def test_query_authorization_filter_before_recall(store, sdk):
    sdk.collection.query.return_value = response(sdk, distance=1.)
    result = store.query([1., 0., 0.], ['d1'], [], 20)
    kw = sdk.collection.query.call_args.kwargs
    assert kw['where'] == {'document_id': {'$in': ['d1']}}
    assert kw['query_embeddings'] == [[1., 0., 0.]]
    assert kw['include'] == ['metadatas', 'distances', 'documents']
    assert result['compared_count'] == 1
    row = result['candidates'][0]
    assert row['score'] == 0. and row['distance'] == 1. and row['reference_similarity'] == .5
    assert row['score_kind'] == 'cosine' and row['body'] == units()['u1']['body']
    assert row['case_fields'] == units()['u1']['case_fields']


def test_no_implicit_create_on_reload(tmp_path, sdk, store):
    sdk.client.reset_mock()
    reopened = ChromaStore(settings(tmp_path), units(), client=sdk.client)
    assert reopened.count() == 2
    sdk.client.get_collection.assert_called_once_with(name='knowledge_hub', embedding_function=None)
    sdk.client.get_or_create_collection.assert_not_called()
    with pytest.raises(RetrievalError, match='write_not_allowed'):
        reopened.upsert({'u1': [1., 0., 0.]})


@pytest.mark.parametrize('scope,exclude', [(['other'], []), (['d1','d1'], []), ([], []), (None, ['other'])])
def test_invalid_scope_rejected_before_sdk(store, sdk, scope, exclude):
    with pytest.raises(RetrievalError, match='invalid_scope'):
        store.query([1., 0., 0.], scope, exclude, 20)
    sdk.collection.query.assert_not_called()


def test_authorized_subset_cannot_be_expanded(tmp_path, sdk):
    cfg = settings(tmp_path); cfg['authorized_document_ids'] = ['d1']
    limited = ChromaStore(cfg, units(), create=True, client=sdk.client)
    with pytest.raises(RetrievalError, match='invalid_scope'):
        limited.query([1., 0., 0.], ['d2'], [], 20)
    sdk.collection.query.assert_not_called()


def test_exclusion_empty_is_success(store, sdk):
    assert store.query([1., 0., 0.], None, ['d1','d2'], 20) == {'candidates': [], 'compared_count': 0}
    sdk.collection.query.assert_not_called()


@pytest.mark.parametrize('vector', [[1.,0.], [0.,0.,0.], [float('nan'),0.,1.], [True,0.,1.]])
def test_invalid_vectors_fail_before_io(store, sdk, vector):
    with pytest.raises(RetrievalError, match='invalid_vector'):
        store.query(vector, None, [], 20)
    sdk.collection.query.assert_not_called()


@pytest.mark.parametrize('k', [0, 21, True])
def test_invalid_k(store, sdk, k):
    with pytest.raises(RetrievalError, match='invalid_candidate_k'):
        store.query([1.,0.,0.], None, [], k)
    sdk.collection.query.assert_not_called()


@pytest.mark.parametrize('fault', ['missing_distance','unknown_id','wrong_body','wrong_version',
                                 'wrong_metadata','duplicate','out_of_scope','nan_distance','short_array'])
def test_sdk_result_binding_rejects_malformed(store, sdk, fault):
    result = response(sdk, uid='u2' if fault=='out_of_scope' else 'u1')
    if fault == 'missing_distance': del result['distances']
    elif fault == 'unknown_id': result['ids'][0][0] = 'unknown'
    elif fault == 'wrong_body': result['documents'][0][0] = 'wrong'
    elif fault == 'wrong_version': result['metadatas'][0][0]['source_sha256'] = 'wrong'
    elif fault == 'wrong_metadata': result['metadatas'][0][0]['canonical_json'] = '{}'
    elif fault == 'duplicate':
        for values in result.values(): values[0] *= 2
    elif fault == 'nan_distance': result['distances'][0][0] = float('nan')
    elif fault == 'short_array': result['documents'][0] = []
    sdk.collection.query.return_value = result
    with pytest.raises(RetrievalError, match='invalid_chroma_result'):
        store.query([1.,0.,0.], ['d1'], [], 20)


@pytest.mark.parametrize('fault', ['metadata','space','embedding_function'])
def test_reload_checks_actual_configuration(tmp_path, sdk, store, fault):
    if fault == 'metadata': sdk.collection.metadata['index_id'] = 'wrong'
    elif fault == 'space': sdk.collection.configuration['hnsw']['space'] = 'l2'
    else: sdk.collection.configuration['embedding_function'] = {'name':'default'}
    with pytest.raises(RetrievalError, match='collection_mismatch'):
        ChromaStore(settings(tmp_path), units(), client=sdk.client)


def test_failure_is_logged_without_provider_text(store, sdk, caplog):
    sdk.collection.query.side_effect = RuntimeError('secret-provider-text')
    with pytest.raises(RetrievalError, match='chroma_query_failed') as error:
        store.query([1.,0.,0.], None, [], 20)
    assert 'secret-provider-text' not in str(error.value) + caplog.text
    assert 'chroma_query_failed' in caplog.text


def test_no_partial_upsert_on_invalid_batch(store, sdk):
    sdk.collection.upsert.reset_mock()
    with pytest.raises(RetrievalError, match='invalid_vector'):
        store.upsert({'u1':[1.,0.,0.], 'u2':[0.,0.,0.]})
    sdk.collection.upsert.assert_not_called()


def test_get_binding_and_defensive_copy(store, sdk):
    result = store.get_by_ids(['u1']); result['u1']['unit']['contexts'].clear()
    assert store.get_by_ids(['u1'])['u1']['unit'] == units()['u1']
    sdk.collection.get.return_value = None
    sdk.collection.get.side_effect = lambda **kw: {'ids':['u1'], 'documents':['bad'], 'metadatas':[{}], 'embeddings':[[1.,0.,0.]]}
    with pytest.raises(RetrievalError, match='invalid_chroma_result'):
        store.get_by_ids(['u1'])
