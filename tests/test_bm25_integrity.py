"""Bounded native format and source-level audits; rehashed corruption is still wrong."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import numpy as np
import pytest
from naiyue_rag.storage import BM25Indexer,BM25Store,BM25Settings
from naiyue_rag.core.errors import StorageError
from naiyue_rag.storage.bundle_store import _json_bytes,_parse
from test_bm25_store import saved,index_folder


def rewrite(root,name,payload):
    (root/name).write_bytes(payload)
    header=json.loads((root/'ready.json').read_bytes())
    header['files'][name]=dict(bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
    (root/'ready.json').write_bytes(_json_bytes(header,65536))


def npy(value):
    stream=BytesIO();np.save(stream,value,allow_pickle=True);return stream.getvalue()


@pytest.mark.parametrize('fault',['missing','extra','bad-marker','identity','mapping','params','version',
    'duplicate-json','vocab','vocab-swap','nan','wrong-weight','zero-weight','wrong-row','valid-wrong-row','duplicate-row','offsets',
    'symlink','fifo','descriptor-limit'])
def test_rehashed_corruption_rejected(saved,tmp_path,fault):
    cfg,uid,_=saved;writer=BM25Indexer(cfg,BM25Settings(1.5,.75));writer.build(uid);root=index_folder(cfg)
    if fault=='missing':(root/'data.csc.index.npy').unlink()
    elif fault=='extra':(root/'unexpected').write_text('extra')
    elif fault=='bad-marker':(root/'ready.json').write_text('{}\n')
    elif fault in ('identity','descriptor-limit'):
        h=json.loads((root/'ready.json').read_bytes())
        if fault=='identity':h['tokenizer_id']='0'*64
        else:h['files']['rows.json']['bytes']=cfg.max_file_bytes+1
        (root/'ready.json').write_bytes(_json_bytes(h,65536))
    elif fault=='mapping':
        rows=json.loads((root/'rows.json').read_bytes());rows.reverse()
        rewrite(root,'rows.json',_json_bytes(rows,65536))
    elif fault in ('params','version','duplicate-json'):
        p=json.loads((root/'params.index.json').read_bytes())
        if fault=='params':p['backend']='numba'
        elif fault=='version':p['version']='0.0.0'
        raw=json.dumps(p).encode()
        if fault=='duplicate-json':raw=raw[:-1]+b',"k1":1.5}'
        rewrite(root,'params.index.json',raw)
    elif fault in ('vocab','vocab-swap'):
        v=json.loads((root/'vocab.index.json').read_bytes());keys=list(v)
        if fault=='vocab':v[keys[1]]=v[keys[0]]
        else:v['开关'],v['关闭']=v['关闭'],v['开关']
        rewrite(root,'vocab.index.json',json.dumps(v).encode())
    elif fault in ('nan','wrong-weight','zero-weight'):
        a=np.load(root/'data.csc.index.npy',allow_pickle=False)
        a[0]=float('nan') if fault=='nan' else a[0]+.1 if fault=='wrong-weight' else 0
        rewrite(root,'data.csc.index.npy',npy(a))
    elif fault in ('wrong-row','valid-wrong-row','duplicate-row'):
        a=np.load(root/'indices.csc.index.npy',allow_pickle=False)
        if fault=='wrong-row':a[0]=len(a)+100
        elif fault=='valid-wrong-row':a[0]=(a[0]+1)%len(saved[2].chunks)
        else:a[1]=a[0]
        rewrite(root,'indices.csc.index.npy',npy(a))
    elif fault=='offsets':
        a=np.load(root/'indptr.csc.index.npy',allow_pickle=False);a[1]=-1
        rewrite(root,'indptr.csc.index.npy',npy(a))
    else:
        p=root/'data.csc.index.npy';raw=p.read_bytes();p.unlink()
        if fault=='symlink':
            target=tmp_path/'external';target.write_bytes(raw);p.symlink_to(target)
        else:
            import os
            os.mkfifo(p)
    with pytest.raises(StorageError):writer.audit(uid)


@pytest.mark.parametrize('fault',['object','oversize-shape','truncated','wrong-dtype'])
def test_invalid_npy_rejected_before_native_allocation(saved,monkeypatch,fault):
    cfg,uid,_=saved;writer=BM25Indexer(cfg,BM25Settings(1.5,.75));writer.build(uid);root=index_folder(cfg)
    if fault=='object':payload=npy(np.array([{'synthetic':1}],dtype=object))
    elif fault=='oversize-shape':
        stream=BytesIO();np.lib.format.write_array_header_1_0(stream,
            dict(descr='<f8',fortran_order=False,shape=(10**12,)))
        payload=stream.getvalue()
    elif fault=='truncated':payload=(root/'data.csc.index.npy').read_bytes()[:-1]
    else:payload=npy(np.load(root/'data.csc.index.npy',allow_pickle=False).astype(np.float32))
    rewrite(root,'data.csc.index.npy',payload);calls=[]
    def forbidden(*args,**kwargs):calls.append(1);raise AssertionError('unsafe array allocation')
    monkeypatch.setattr(np,'load',forbidden)
    with pytest.raises(StorageError,match='bm25_integrity_failed'):writer.audit(uid)
    assert calls==[]


def test_native_runtime_failure_has_fixed_code(saved,monkeypatch):
    import naiyue_rag.storage.bm25_backend as backend
    cfg,uid,_=saved
    def missing(*args):raise backend.metadata.PackageNotFoundError('SYNTHETIC_PRIVATE')
    monkeypatch.setattr(backend.metadata,'version',missing)
    with pytest.raises(StorageError,match='bm25_runtime_mismatch'):
        BM25Indexer(cfg,BM25Settings(1.5,.75)).build(uid)


def test_native_json_does_not_weaken_existing_canonical_contract():
    raw=b'{"a": 1}\n'
    with pytest.raises(StorageError,match='bundle_integrity_failed'):_parse(raw)
    assert _parse(raw,canonical=False)=={'a':1}
    for raw in [b'{"a":1,"a":1}',b'{"a":NaN}']:
        with pytest.raises(StorageError):_parse(raw,canonical=False)


def test_hand_scoring_matches_persisted_model(tmp_path):
    from collections import Counter
    import math
    from naiyue_rag.core.sparse_types import SparseRecord
    from naiyue_rag.storage import bm25_backend as backend
    docs=[['alpha','alpha','beta'],['beta','gamma']]
    records=[SparseRecord(str(i),'document','f'*64,tokens,dict(Counter(tokens)),len(tokens),len(set(tokens)),'a'*64)
             for i,tokens in enumerate(docs)]
    cfg=BM25Settings(1.5,.75);backend.build_native(tmp_path,records,cfg)
    payloads={name:(tmp_path/name).read_bytes() for name in backend.NATIVE_FILES}
    model=backend.load_native(tmp_path,payloads,records,cfg)
    expected=math.log(1+(2-1+.5)/(1+.5))*2/(2+1.5*(1-.75+.75*3/2.5))
    assert model.get_scores(['alpha']).tolist()==pytest.approx([expected,0.],rel=1e-12)
    assert model.get_scores(['unseen']).tolist()==[0.,0.]
