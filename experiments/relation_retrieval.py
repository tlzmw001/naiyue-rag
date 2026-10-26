"""Document-local recall on source-grounded neighbors, then A2/route RRF."""
import copy
import math

from experiments.embedding_probe import ProbeError
from experiments.keyword_index import score_all
from experiments.rank_fusion import fuse
from experiments.vector_index import search, validate_scope
from experiments.relation_index import limit


def build_route(vector_index, keyword_index, query_vector, query, related_documents, tokenizer, config):
    per_doc = limit(config, 'per_document_k', 4); route_k = limit(config, 'relation_k', 20)
    if config.get('rrf_k') != 60 or type(config.get('rrf_k')) is not int:
        raise ProbeError('config', 'invalid_rrf_k')
    validate_scope(vector_index['source_ids'], vector_index['excluded_ids'], query['scope_ids'], query['exclude_ids'])
    allowed = set(query['scope_ids'] if query['scope_ids'] is not None else vector_index['source_ids'])-set(query['exclude_ids'])
    expected = {'scope_ids': sorted(query['scope_ids']) if query['scope_ids'] is not None else None,
                'exclude_ids': sorted(query['exclude_ids'])}
    ids = [r['document_id'] for r in related_documents]
    if keyword_index['scope'] != expected or not set(ids) <= allowed or len(set(ids)) != len(ids) or len(ids) > 8:
        raise ProbeError('relation-recall', 'invalid_related_scope')
    complete = score_all(keyword_index, query['query'], tokenizer)
    docs, pooled = [], []
    for document in related_documents:
        did = document['document_id']
        dense = search(vector_index, query_vector, [did], query['exclude_ids'], per_doc)
        filtered = [u for u in complete['candidates'] if u['document_id'] == did][:per_doc]
        sparse = [dict(u, rank=i+1) for i, u in enumerate(filtered)]
        local = fuse(dense['candidates'], sparse, vector_index['units'], config['rrf_k'], per_doc)
        docs.append({'document_id': did, 'best_path': document['best_path'],
                     'status': 'retrieved' if local['candidates'] else 'empty_document',
                     'dense_candidates': dense['candidates'], 'sparse_candidates': sparse,
                     'local_union': local['union_candidates'], 'local_candidates': local['candidates']})
        for row in local['candidates']:
            info = row['retrieval_info']
            pooled.append(dict(row, relation_info={'local_dense_rank': info['dense_rank'], 'cosine': info['cosine'],
                                'local_sparse_rank': info['sparse_rank'], 'bm25_score': info['bm25_score'],
                                'doc_local_rrf_score': row['score'], 'best_path': document['best_path']}))
    pooled.sort(key=lambda u: (-u['score'], u['unit_id']))
    numbered = [dict(u, rank=i+1) for i, u in enumerate(pooled)]
    return {'candidates': numbered[:route_k], 'route_limit_excluded': numbered[route_k:],
            'documents': docs, 'pool_candidates': numbered, 'query_tokens': complete['query_tokens'],
            'N': complete['N'], 'avgdl': complete['avgdl'], 'vocab_count': complete['vocab_count']}


def combine_routes(a2, related, units, rrf_k, candidate_k):
    if type(rrf_k) is not int or rrf_k != 60 or type(candidate_k) is not int or not 0 < candidate_k <= 20:
        raise ProbeError('fusion', 'invalid_fusion_config')
    accumulated = {}
    try:
        for name, rows in [('a2', a2), ('relation', related)]:
            if not isinstance(rows, list) or len(rows) > 20:
                raise ValueError('route length')
            seen = set()
            for rank, row in enumerate(rows, 1):
                uid = row['unit_id']
                if uid not in units or uid in seen or type(row['rank']) is not int or row['rank'] != rank or \
                        row.get('retrieval_method') != 'hybrid' or row.get('score_kind') != 'rrf' or \
                        type(row['score']) not in (int, float) or not math.isfinite(row['score']) or \
                        any(row.get(k) != v for k, v in units[uid].items()):
                    raise ValueError('invalid candidate')
                seen.add(uid)
                if uid not in accumulated:
                    accumulated[uid] = dict(units[uid], score=0.0, retrieval_method='hybrid', score_kind='rrf',
                        retrieval_stage='relation_augmented', retrieval_info={'a2_rank': None, 'a2_rrf_score': None,
                        'a2_contribution': None, 'relation_rank': None, 'doc_rrf_score': None,
                        'relation_contribution': None, 'a2_info': None, 'relation_info': None, 'best_path': None})
                out = accumulated[uid]; info = out['retrieval_info']; contribution = 1/(rrf_k+rank)
                out['score'] += contribution
                info[name+'_rank'] = rank; info[name+'_contribution'] = contribution
                if name == 'a2':
                    info.update(a2_rrf_score=row['score'], a2_info=copy.deepcopy(row.get('retrieval_info')))
                else:
                    relation = copy.deepcopy(row.get('relation_info'))
                    info.update(doc_rrf_score=row['score'], relation_info=relation,
                                best_path=relation.get('best_path') if relation else None)
        if not related:
            unchanged = copy.deepcopy(a2)
            return {'candidates': unchanged[:candidate_k], 'union_candidates': unchanged}
        ordered = sorted(accumulated.values(), key=lambda u: (-u['score'], u['unit_id']))
        union = [dict(u, rank=i+1) for i, u in enumerate(ordered)]
        return {'candidates': union[:candidate_k], 'union_candidates': union}
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ProbeError('fusion', 'invalid_candidates') from None
