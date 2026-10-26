"""Formal BM25 storage contracts over already-paired synthetic records."""
from collections import Counter
import copy
import json
from pathlib import Path
import pytest
from naiyue_rag.storage import (BM25Settings,load_bm25_settings,BM25Indexer,BM25Store,BundleStore)
from naiyue_rag.core.errors import SettingsError,StorageError
from test_storage_bundle import make_bundle,storage_settings,PRIVATE


@pytest.mark.parametrize('k1,b',[(0,.75),(-1,.75),(True,.75),(float('nan'),.75),
    (float('inf'),.75),(1.5,-.1),(1.5,1.1),(1.5,True),(1.5,float('nan'))])
def test_invalid_bm25_settings(k1,b):
    with pytest.raises(SettingsError,match='invalid_bm25_settings'):BM25Settings(k1,b)


def test_config_is_strict_and_normalized(tmp_path):
    assert BM25Settings(1,0).to_dict()==dict(k1=1.,b=0.)
    p=tmp_path/'bm25.yaml';p.write_text('k1: 1.5\nb: 0.75\n')
    assert load_bm25_settings(p)==BM25Settings(1.5,.75)
    for raw in ['k1: 1\nk1: 2\nb: 0','k1: 1\nb: 0\nextra: true','k1: &a 1\nb: *a']:
        p.write_text(raw)
        with pytest.raises(SettingsError):load_bm25_settings(p)


def save_bundle(tmp_path,mode='normal'):
    cfg=storage_settings(tmp_path);bundle=make_bundle(tmp_path,'empty' if mode=='zero' else 'normal')
    # The older M4.1 helper intentionally produces only empty sparse rows.
    # Supply explicit nonempty synthetic inputs for BM25's normal/storage branches.
    for i,record in enumerate(bundle.encoding_result.records):
        tokens=[] if mode=='all-empty' or mode=='mixed' and i==0 else (
            ['开关','开关','0','0.5','tc-01','cvr_ltv'] if i%2==0 else ['关闭','1'])
        record.sparse.tokens=tokens;record.sparse.term_frequencies=dict(Counter(tokens))
        record.sparse.doc_length=len(tokens);record.sparse.unique_terms=len(set(tokens))
    return cfg,BundleStore(cfg).save(bundle).bundle_id,bundle


@pytest.fixture
def saved(tmp_path):return save_bundle(tmp_path)


def index_folder(cfg):return next(Path(cfg.storage_root).glob('*/bm25/[!.]*'))


def test_build_reload_repeat_and_identity(saved,monkeypatch):
    import naiyue_rag.storage.bm25_backend as backend
    cfg,uid,bundle=saved;settings=BM25Settings(1.5,.75)
    writer=BM25Indexer(cfg,settings);reader=BM25Store(cfg,settings)
    ready=writer.build(uid);assert ready.status=='ready' and ready.chunk_count==len(bundle.chunks)
    root=index_folder(cfg);before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
    def forbidden(*args,**kwargs):pytest.fail('repeat must not rebuild or save')
    monkeypatch.setattr(backend,'build_native',forbidden)
    assert writer.build(uid).status=='unchanged' and reader.audit(uid).status=='verified'
    assert before=={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
    rows=json.loads((root/'rows.json').read_bytes())
    assert [r['item_id'] for r in rows]==[r.input.item_id for r in bundle.encoding_result.records]
    assert ready.verified_count==len(rows) and ready.tokenized_chunk_count==len(rows)
    assert not hasattr(reader,'search')


@pytest.mark.parametrize('mode',['zero','all-empty','mixed'])
def test_empty_rows_preserve_mapping(tmp_path,mode,monkeypatch):
    import naiyue_rag.storage.bm25_backend as backend
    cfg,uid,bundle=save_bundle(tmp_path,mode)
    if mode!='mixed':
        def forbidden(*args,**kwargs):pytest.fail('empty vocab must not invoke native index')
        monkeypatch.setattr(backend,'build_native',forbidden)
    writer=BM25Indexer(cfg,BM25Settings(1.5,.75));receipt=writer.build(uid)
    assert receipt.chunk_count==len(bundle.chunks) and writer.audit(uid).verified_count==len(bundle.chunks)
    expected=sum(bool(r.sparse.tokens) for r in bundle.encoding_result.records)
    assert receipt.tokenized_chunk_count==expected
    assert receipt.empty_chunk_count==receipt.chunk_count-expected
    marker=json.loads((index_folder(cfg)/'ready.json').read_bytes())
    assert marker['native_state']==('indexed' if expected else 'empty')
    if not expected:assert {p.name for p in index_folder(cfg).iterdir()}=={'rows.json','ready.json'}
    assert receipt.avgdl==pytest.approx(sum(r.sparse.doc_length for r in bundle.encoding_result.records)/len(bundle.chunks) if bundle.chunks else 0.)


def test_parameter_change_creates_new_candidate(saved):
    cfg,uid,_=saved
    first=BM25Indexer(cfg,BM25Settings(1.5,.75)).build(uid)
    second=BM25Indexer(cfg,BM25Settings(1.2,0)).build(uid)
    assert first.index_id!=second.index_id and second.status=='ready'
    assert BM25Store(cfg,BM25Settings(1.5,.75)).audit(uid).index_id==first.index_id


def test_read_missing_and_bad_id_do_not_create(saved):
    cfg,uid,_=saved;reader=BM25Store(cfg,BM25Settings(1.5,.75))
    with pytest.raises(StorageError,match='bm25_index_not_found'):reader.audit(uid)
    with pytest.raises(StorageError,match='invalid_bundle_id'):reader.audit('../outside')
    assert not list(Path(cfg.storage_root).glob('*/bm25'))


@pytest.mark.parametrize('fault',['native-save','marker-write','rename','parent-sync'])
def test_failed_build_not_reported_ready(saved,monkeypatch,fault,caplog):
    import naiyue_rag.storage.bm25_backend as backend
    import naiyue_rag.storage.bm25_store as module
    cfg,uid,_=saved;writer=BM25Indexer(cfg,BM25Settings(1.5,.75))
    def fail(*args,**kwargs):raise OSError(PRIVATE)
    if fault=='native-save':monkeypatch.setattr(backend,'build_native',fail)
    elif fault=='marker-write':monkeypatch.setattr(writer.bundles,'_write_file',fail)
    elif fault=='rename':monkeypatch.setattr(module.os,'rename',fail)
    else:
        original=writer.bundles._sync_directory
        def sync(path):
            if path.name=='bm25':fail()
            original(path)
        monkeypatch.setattr(writer.bundles,'_sync_directory',sync)
    expected='bm25_publish_uncertain' if fault=='parent-sync' else 'bm25_publish_failed' if fault=='rename' else 'bm25_write_failed'
    with pytest.raises(StorageError,match=expected):writer.build(uid)
    assert PRIVATE not in caplog.text
    if fault=='parent-sync':assert writer.audit(uid).status=='verified'
    else:assert not list(Path(cfg.storage_root).glob('*/bm25/[!.]*/ready.json'))


def test_short_write_cannot_publish_keyword_index(saved,monkeypatch):
    import naiyue_rag.storage.bundle_store as shared
    cfg,uid,_=saved;original=shared.os.fdopen
    class ShortWriter:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def __getattr__(self,name):return getattr(self.stream,name)
        def write(self,payload):return self.stream.write(payload[:-1])
    def stream(fd,mode):
        value=original(fd,mode)
        return ShortWriter(value) if mode=='wb' else value
    monkeypatch.setattr(shared.os,'fdopen',stream)
    with pytest.raises(StorageError,match='bm25_write_failed'):
        BM25Indexer(cfg,BM25Settings(1.5,.75)).build(uid)
    assert not list(Path(cfg.storage_root).glob('*/bm25/[!.]*/ready.json'))


def test_keyword_namespace_symlink_cannot_redirect_storage(saved,tmp_path):
    cfg,uid,_=saved;external=tmp_path/'external';external.mkdir()
    kb=next(Path(cfg.storage_root).iterdir());(kb/'bm25').symlink_to(external,target_is_directory=True)
    with pytest.raises(StorageError,match='bm25_path_invalid'):
        BM25Indexer(cfg,BM25Settings(1.5,.75)).build(uid)
    assert list(external.iterdir())==[]


def test_native_save_partial_files_remain_unpublished(saved,monkeypatch,caplog):
    import bm25s
    import numpy as np
    cfg,uid,_=saved;source=next(Path(cfg.storage_root).glob('*/artifacts/*'))
    before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in source.iterdir()}
    def partial_save(model,path,**kwargs):
        np.save(Path(path)/'data.csc.index.npy',model.scores['data'],allow_pickle=False)
        raise OSError(PRIVATE)
    monkeypatch.setattr(bm25s.BM25,'save',partial_save)
    with pytest.raises(StorageError,match='bm25_write_failed'):
        BM25Indexer(cfg,BM25Settings(1.5,.75)).build(uid)
    pending=list(Path(cfg.storage_root).glob('*/bm25/.pending-*'))
    assert len(pending)==1 and {p.name for p in pending[0].iterdir()}=={'data.csc.index.npy'}
    assert not list(Path(cfg.storage_root).glob('*/bm25/[!.]*/ready.json'))
    assert before=={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in source.iterdir()}
    assert PRIVATE not in caplog.text
