"""Pinned native arrays and source-level numeric auditing; no user query API."""
from importlib import metadata
from io import BytesIO
import math
import numpy as np
from ..core.errors import StorageError
from .bundle_store import _parse,_json_bytes

SDK_VERSION='0.3.13'
NATIVE_FILES=('data.csc.index.npy','indices.csc.index.npy','indptr.csc.index.npy',
              'vocab.index.json','params.index.json')


def check_runtime():
    try:version=metadata.version('bm25s')
    except Exception:raise StorageError('bm25_runtime_mismatch') from None
    if version!=SDK_VERSION:raise StorageError('bm25_runtime_mismatch')


def _sdk():
    check_runtime()
    try:import bm25s
    except Exception:raise StorageError('bm25_runtime_mismatch') from None
    return bm25s


def parameters(settings):
    return dict(k1=settings.k1,b=settings.b,delta=.5,method='lucene',idf_method='lucene',
                backend='numpy',csc_backend='numpy',dtype='float64',int_dtype='int32',auto_compile=False)


def statistics(records):
    postings={}
    for row,record in enumerate(records):
        for term,tf in record.term_frequencies.items():postings.setdefault(term,{})[row]=tf
    return postings,sum(r.doc_length for r in records)/len(records) if records else 0.,sum(r.unique_terms for r in records)


def build_native(path,records,settings):
    sdk=_sdk()
    try:
        model=sdk.BM25(**parameters(settings))
        model.index([list(r.tokens) for r in records],create_empty_token=False,show_progress=False)
        model.save(path,allow_pickle=False,show_progress=False)
        return model
    except Exception:raise StorageError('bm25_write_failed') from None


def _native_json(raw):
    try:return _parse(raw,canonical=False)
    except Exception:raise StorageError('bm25_integrity_failed') from None


def _npy_header(raw,dtype,length):
    """Validate allocation size before SDK np.load; pickle/object arrays never reach it."""
    try:
        stream=BytesIO(raw);version=np.lib.format.read_magic(stream)
        if version==(1,0):shape,fortran,actual=np.lib.format.read_array_header_1_0(stream,max_header_size=10000)
        elif version==(2,0):shape,fortran,actual=np.lib.format.read_array_header_2_0(stream,max_header_size=10000)
        else:raise ValueError()
        if type(shape) is not tuple or len(shape)!=1 or type(shape[0]) is not int or shape[0]!=length:
            raise ValueError()
        if fortran or actual!=np.dtype(dtype) or actual.hasobject:raise ValueError()
        if stream.tell()+length*actual.itemsize!=len(raw):raise ValueError()
    except Exception:raise StorageError('bm25_integrity_failed') from None


def audit_model(model,records,settings):
    try:
        postings,avgdl,nnz=statistics(records);N=len(records);vocab=model.vocab_dict
        if type(vocab) is not dict or set(vocab)!=set(postings) or \
                any(type(v) is not int for v in vocab.values()) or set(vocab.values())!=set(range(len(vocab))):raise ValueError()
        scores=model.scores
        if set(scores)!={'data','indices','indptr','num_docs'} or type(scores['num_docs']) is not int or scores['num_docs']!=N:raise ValueError()
        data,indices,offsets=[scores[k] for k in ['data','indices','indptr']]
        for array,dtype,size in [(data,'float64',nnz),(indices,'int32',nnz),(offsets,'int64',len(vocab)+1)]:
            if array.ndim!=1 or array.dtype!=np.dtype(dtype) or array.shape!=(size,):raise ValueError()
        if offsets[0]!=0 or offsets[-1]!=nnz or np.any(offsets<0) or np.any(offsets>nnz) or \
                np.any(np.diff(offsets)<0) or np.any(indices<0) or np.any(indices>=N) or \
                not np.isfinite(data).all() or np.any(data<=0):raise ValueError()
        for term,col in vocab.items():
            start,end=int(offsets[col]),int(offsets[col+1]);actual=indices[start:end]
            expected=postings[term]
            if len(actual)!=len(expected) or len(set(actual))!=len(actual) or set(actual)!=set(expected):raise ValueError()
            idf=math.log(1+(N-len(expected)+.5)/(len(expected)+.5))
            for row,weight in zip(actual,data[start:end],strict=True):
                tf=expected[int(row)];dl=records[int(row)].doc_length
                expected_weight=idf*tf/(tf+settings.k1*(1-settings.b+settings.b*dl/avgdl))
                if not math.isclose(float(weight),expected_weight,rel_tol=1e-12,abs_tol=1e-15):raise ValueError()
    except StorageError:raise
    except Exception:raise StorageError('bm25_integrity_failed') from None


def load_native(path,payloads,records,settings):
    """Prevalidate bounded bytes before the native loader reads its fixed file set."""
    sdk=_sdk();postings,_,nnz=statistics(records)
    params=_native_json(payloads['params.index.json']);vocab=_native_json(payloads['vocab.index.json'])
    expected={k:v for k,v in parameters(settings).items() if k not in ('auto_compile','csc_backend')}
    expected.update(num_docs=len(records),version=SDK_VERSION)
    if _json_bytes(params,len(payloads['params.index.json'])+1024)!=_json_bytes(expected,len(payloads['params.index.json'])+1024):
        raise StorageError('bm25_identity_mismatch')
    if type(vocab) is not dict or set(vocab)!=set(postings) or any(type(v) is not int for v in vocab.values()) or \
            set(vocab.values())!=set(range(len(vocab))):raise StorageError('bm25_integrity_failed')
    for name,dtype,length in [('data.csc.index.npy','float64',nnz),('indices.csc.index.npy','int32',nnz),
                               ('indptr.csc.index.npy','int64',len(vocab)+1)]:
        _npy_header(payloads[name],dtype,length)
    try:
        model=sdk.BM25.load(path,allow_pickle=False,mmap=False,load_corpus=False,show_progress=False,
                           override_params={'auto_compile':False,'csc_backend':'numpy'})
    except Exception:raise StorageError('bm25_read_failed') from None
    audit_model(model,records,settings)
    return model
