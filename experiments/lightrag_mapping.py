"""B0 scope-specific native IDs and exact evidence mapping; no SDK imports."""
import math

from experiments.embedding_probe import ProbeError
from experiments.vector_index import digest, make_index_text, validate_scope


def make_payload(corpus, index, queries):
    pools = []
    for query in queries:
        validate_scope(index['source_ids'], index['excluded_ids'], query['scope_ids'], query['exclude_ids'])
        pools.append(sorted(k for k in corpus['sources']
                            if (query['scope_ids'] is None or k in query['scope_ids']) and k not in query['exclude_ids']))
    if not pools or any(pool != pools[0] for pool in pools):
        raise ProbeError('mapping', 'mixed_scope')
    sources = pools[0]
    scope_key = digest(('\n'.join(sources) + corpus['fingerprint']).encode())
    documents = [{'document_id': k, 'native_id': 'doc-'+k, 'native_file_path': 'doc-'+k+'.md',
                  'content': corpus['sources'][k]['text'], 'source_sha256': corpus['sources'][k]['source_sha256']}
                 for k in sources]
    units = [dict(u, native_id='doc-'+u['document_id']+'-'+u['unit_id'],
                  native_file_path='doc-'+u['document_id']+'.md', content=make_index_text(u),
                  input_sha256=digest(make_index_text(u).encode()))
             for u in corpus['units'] if u['document_id'] in sources]
    return {'scope_key': scope_key, 'fingerprint': corpus['fingerprint'], 'documents': documents, 'units': units,
            'vectors': {u['input_sha256']: index['vectors'][u['unit_id']] for u in units},
            'query_vectors': {digest(q['query'].encode()): index['query_vectors'][q['task_id']] for q in queries},
            'queries': queries, 'index_id': index['index_id']}


def map_results(payload, raw, chunks, index, candidate_k):
    try:
        units = {u['native_id']: u for u in payload['units']}
        raw_ids = [r['id'] for r in raw]
        ids = [r['chunk_id'] for r in chunks]
        if len(raw) > candidate_k or len(set(raw_ids)) != len(raw_ids) or len(set(ids)) != len(ids):
            raise ValueError('count')
        if any(i not in units for i in raw_ids + ids) or ids != [i for i in raw_ids if i in ids]:
            raise ValueError('scope/order')
        scores = {r['id']: r['distance'] for r in raw}
        if any(type(s) not in (int, float) or not math.isfinite(s) or not -1.000001 <= s <= 1.000001
               for s in scores.values()):
            raise ValueError('score')
        result = []
        for rank, chunk in enumerate(chunks, 1):
            unit = units[chunk['chunk_id']]
            if chunk['content'] != unit['content'] or chunk['file_path'] != unit['native_file_path']:
                raise ValueError('content/source')
            original = index['units'][unit['unit_id']]
            result.append(dict(original, score=scores[chunk['chunk_id']], rank=rank, retrieval_method='vector',
                               retrieval_info={'native_chunk_id': chunk['chunk_id'], 'native_rank': rank,
                                               'native_raw_rank': raw_ids.index(chunk['chunk_id'])+1,
                                               'score_kind': 'cosine', 'storage_dtype': 'float32'}))
        return result
    except (ValueError, TypeError, KeyError):
        raise ProbeError('query', 'native_query_mismatch') from None
