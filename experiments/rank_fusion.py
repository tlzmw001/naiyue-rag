"""Equal-weight RRF with canonical evidence and one contribution per route."""
import math

from experiments.embedding_probe import ProbeError


def fuse(dense, sparse, units, rrf_k, candidate_k):
    if type(rrf_k) is not int or rrf_k != 60 or type(candidate_k) is not int or not 0 < candidate_k <= 20:
        raise ProbeError('fusion', 'invalid_fusion_config')
    accumulated = {}
    try:
        for method, rows in [('vector', dense), ('sparse', sparse)]:
            if not isinstance(rows, list) or len(rows) > 20:
                raise ValueError('invalid route')
            seen = set()
            for rank, row in enumerate(rows, 1):
                uid = row['unit_id']
                if uid in seen or uid not in units or type(row['rank']) is not int or row['rank'] != rank or \
                        row['retrieval_method'] != method or type(row['score']) not in (int, float) or \
                        not math.isfinite(row['score']) or any(row.get(k) != v for k, v in units[uid].items()):
                    raise ValueError('invalid candidate')
                seen.add(uid)
                if uid not in accumulated:
                    accumulated[uid] = dict(units[uid], score=0.0, retrieval_method='hybrid', score_kind='rrf',
                        retrieval_info={'dense_rank': None, 'cosine': None, 'dense_contribution': None,
                                        'sparse_rank': None, 'bm25_score': None, 'sparse_contribution': None})
                result = accumulated[uid]
                contribution = 1/(rrf_k+rank)
                result['score'] += contribution
                prefix, field = ('dense', 'cosine') if method == 'vector' else ('sparse', 'bm25_score')
                result['retrieval_info'].update({prefix+'_rank': rank, field: row['score'],
                                                 prefix+'_contribution': contribution})
        ordered = sorted(accumulated.values(), key=lambda row: (-row['score'], row['unit_id']))
        union = [dict(row, rank=i+1) for i, row in enumerate(ordered)]
        return {'candidates': union[:candidate_k], 'union_candidates': union}
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ProbeError('fusion', 'invalid_candidates') from None
