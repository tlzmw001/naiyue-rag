"""Reuse saved global weights or rebuild scoped statistics in memory only."""
import copy
import numpy as np
from ..core.errors import StorageError
from . import bm25_backend as backend


def query_index(store,bundle_id,query_terms,*,document_ids,top_k,statistics_scope):
    path,header,rows,records=store._prepare(bundle_id)
    bundle=store.bundles.load(bundle_id);known={d.id for d in bundle.documents}
    try:
        if type(top_k) is not int or not 0<top_k<=store.settings.max_chunks or \
                type(statistics_scope) is not str or statistics_scope not in ('global','scope') or \
                type(document_ids) is not list or any(type(d) is not str or d not in known for d in document_ids) or \
                len(set(document_ids))!=len(document_ids) or type(query_terms) is not list:raise ValueError()
        if any(type(t) is not str or not t.strip() for t in query_terms) or len(set(query_terms))!=len(query_terms):raise ValueError()
        for term in query_terms:term.encode('utf-8')
    except Exception:raise StorageError('bm25_invalid_request') from None
    model=store._load_index(path,header,rows,records);scope=set(document_ids)
    selected=[i for i,row in enumerate(rows) if row['source_document_id'] in scope]
    if not selected or not query_terms or model is None:return []
    mapping=list(range(len(records))) if statistics_scope=='global' else selected
    try:
        if statistics_scope=='scope':
            local=[records[i] for i in selected]
            if not any(r.tokens for r in local):return []
            model=backend._sdk().BM25(**backend.parameters(store.config))
            model.index([list(r.tokens) for r in local],create_empty_token=False,show_progress=False)
        scores=model.get_scores(list(query_terms))
    except StorageError:raise
    except Exception:raise StorageError('bm25_query_failed') from None
    if type(scores) is not np.ndarray or scores.dtype!=np.dtype('float64') or scores.shape!=(len(mapping),) or \
            not np.isfinite(scores).all() or np.any(scores<0):raise StorageError('bm25_integrity_failed')
    selected=set(selected);chunks={c.id:c for c in bundle.chunks};hits=[]
    for index,score in zip(mapping,scores,strict=True):
        if index in selected and score>0:
            hits.append(dict(chunk=copy.deepcopy(chunks[rows[index]['item_id']]),score=float(score)))
    return sorted(hits,key=lambda hit:(-hit['score'],hit['chunk'].id))[:top_k]
