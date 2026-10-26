"""Native cosine queries with explicit document scope and source-bound hits."""
import copy
import math
import numpy as np
from ..core.errors import StorageError
from .bundle_store import _json_bytes
from .chroma_backend import call,open_collection


def query_index(store,bundle_id,query_vector,*,document_ids,top_k):
    path,header,identity,rows,chunks=store._prepare(bundle_id)
    try:
        if type(top_k) is not int or not 0<top_k<=store.settings.max_chunks or type(document_ids) is not list:
            raise ValueError()
        known={c.source_ref for c in chunks.values()}
        # Blank documents have no chunks but remain valid scope members.
        known.update(d.id for d in store.bundles.load(bundle_id).documents)
        if any(type(d) is not str or d not in known for d in document_ids) or len(set(document_ids))!=len(document_ids):
            raise ValueError()
        if type(query_vector) is not list or len(query_vector)!=header['dimensions'] or \
                any(type(v) not in (int,float) or not math.isfinite(v) for v in query_vector) or math.hypot(*query_vector)==0:
            raise ValueError()
        with np.errstate(over='raise',invalid='raise'):
            vec=np.asarray(query_vector,dtype=np.float32)
        if not np.isfinite(vec).all() or math.hypot(*vec)==0:raise ValueError()
    except Exception:raise StorageError('chroma_invalid_request') from None
    marker=store._marker(path,header);scope=set(document_ids)
    eligible={uid for uid,c in chunks.items() if c.source_ref in scope};limit=min(top_k,len(eligible))
    if not limit:
        store._audit_native(path,identity,rows,configuration=marker['configuration'])
        return []
    with open_collection(path/'chroma',store.project_root,store.config.collection_name,identity,store.config.batch_size) as collection:
        if _json_bytes(collection.configuration,store.settings.max_manifest_bytes)!= \
                _json_bytes(marker['configuration'],store.settings.max_manifest_bytes):raise StorageError('chroma_identity_mismatch')
        if call(collection.count)!=len(rows):raise StorageError('chroma_integrity_failed')
        raw=call(collection.query,query_embeddings=[query_vector],n_results=limit,
            where={'document_id':{'$in':sorted(document_ids)}},include=['documents','metadatas','distances'])
        try:
            columns=[]
            for key in ('ids','distances','documents','metadatas'):
                value=raw[key]
                if type(value) is not list or len(value)!=1 or type(value[0]) is not list or len(value[0])!=limit:
                    raise ValueError()
                columns.append(value[0])
            ids,distances,texts,metas=columns
            if any(type(uid) is not str or uid not in eligible for uid in ids) or len(set(ids))!=len(ids):raise ValueError()
            result=[]
            for uid,distance,text,meta in zip(*columns,strict=True):
                if type(distance) not in (int,float) or not math.isfinite(distance) or text!=rows[uid]['text'] or \
                        _json_bytes(meta,store.settings.max_file_bytes)!=_json_bytes(rows[uid]['metadata'],store.settings.max_file_bytes):
                    raise ValueError()
                result.append(dict(chunk=copy.deepcopy(chunks[uid]),distance=float(distance),score=max(0.,1-float(distance)/2)))
        except Exception:raise StorageError('chroma_integrity_failed') from None
        store._check_rows(collection,ids,rows)
    return sorted(result,key=lambda hit:(hit['distance'],hit['chunk'].id))
