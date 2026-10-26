"""Metadata reads pin one catalog binding, with no native index execution or repairs."""
from dataclasses import replace
import copy
import json
from pathlib import Path
import pytest
from naiyue_rag.storage import (DocumentManager,DocumentList,DocumentDetail,BundleStore,ChromaSettings,
    BM25Settings,VectorUpserter,BM25Indexer,ChromaStore,BM25Store,IndexVersion,prepare_index_bundle)
from naiyue_rag.storage.bundle_store import _json_bytes,_digest
from naiyue_rag.core.errors import StorageError
from test_document_manager import prepared
from test_storage_bundle import storage_settings,make_bundle,PRIVATE,KB,Dense
from test_document_views import document_id


def publish(manager,bundle,revision=0):
    uid=BundleStore(manager.settings).save(bundle).bundle_id
    VectorUpserter(manager.settings,manager.chroma_settings,project_root=manager.project_root).build(uid)
    BM25Indexer(manager.settings,manager.bm25_settings).build(uid)
    return manager.activate(uid,expected_revision=revision).active


def rebuild(root,bundle):
    from naiyue_rag import MarkdownLoader,DocumentChunker,prepare_knowledge_base,prepare_document_encoding_inputs,BatchProcessor
    from test_batch_processor import Sparse
    cfg=bundle.encoding_settings;ingestion=bundle.ingestion_settings
    docs=MarkdownLoader(root/'source',KB,4096).load_all()
    chunks,relations,_=prepare_knowledge_base(docs,DocumentChunker(ingestion),text_mode='raw')
    result=BatchProcessor(cfg,Dense(cfg),Sparse(cfg)).process(prepare_document_encoding_inputs(docs,chunks,cfg))
    return prepare_index_bundle(docs,chunks,relations,result,knowledge_base_id=KB,encoding_settings=cfg,ingestion_settings=ingestion)


def test_list_and_detail_consume_only_saved_bundle(prepared,monkeypatch):
    manager,uid,bundle,_,_=prepared;selected=manager.activate(uid,expected_revision=0).active
    def forbidden(*args,**kwargs):pytest.fail('management must not execute retrieval backends')
    monkeypatch.setattr(manager,'open_active',forbidden)
    for cls,names in [(ChromaStore,['audit','get_by_ids']),(BM25Store,['audit']),
                      (VectorUpserter,['build']),(BM25Indexer,['build'])]:
        for name in names:monkeypatch.setattr(cls,name,forbidden)
    calls=[];read=manager.catalog.read;load=manager.bundles.load
    def read_once():calls.append('catalog');return read()
    def load_once(uid):calls.append('bundle');return load(uid)
    monkeypatch.setattr(manager.catalog,'read',read_once);monkeypatch.setattr(manager.bundles,'load',load_once)
    listing=manager.list_documents()
    assert calls==['catalog','bundle'] and listing.active==selected
    assert isinstance(listing,DocumentList) and len(listing.documents)==3
    assert sum(i.chunk_count for i in listing.documents)==len(bundle.chunks)
    case=next(i for i in listing.documents if i.source_path.endswith('_测试用例.md'))
    calls.clear();detail=manager.get_document_detail(case.document_id,expected_revision=1)
    assert calls==['catalog','bundle'] and isinstance(detail,DocumentDetail)
    assert detail.active==selected and detail.document==case and len(detail.chunk_ids)==case.chunk_count
    assert all(i.startswith('unit-') for i in detail.chunk_ids)
    assert set(detail.to_dict())=={'active','document','chunk_ids'}


@pytest.mark.parametrize('operation',['list','detail'])
def test_unactivated_and_conflict_have_no_write_side_effects(tmp_path,monkeypatch,operation):
    cfg=storage_settings(tmp_path);manager=DocumentManager(cfg,ChromaSettings('knowledge_hub',2),BM25Settings(1.5,.75),project_root=tmp_path)
    def call(revision):
        return manager.list_documents(expected_revision=revision) if operation=='list' else manager.get_document_detail('doc-'+'0'*64,expected_revision=revision)
    result=call(0);assert result.active is None
    assert call(None).active is None
    with pytest.raises(StorageError,match='catalog_revision_conflict'):call(1)
    assert not Path(cfg.storage_root).exists()


@pytest.mark.parametrize('revision',[True,-1,1.0,'1',2**63])
@pytest.mark.parametrize('operation',['list','detail'])
def test_invalid_read_revision_rejected_before_io(prepared,monkeypatch,revision,operation):
    manager,_,_,_,_=prepared
    def forbidden():pytest.fail('invalid request must not read catalog')
    monkeypatch.setattr(manager.catalog,'read',forbidden)
    with pytest.raises(StorageError,match='document_invalid_request'):
        if operation=='list':manager.list_documents(expected_revision=revision)
        else:manager.get_document_detail('doc-'+'0'*64,expected_revision=revision)


@pytest.mark.parametrize('uid',[None,'../a.md','a'*64,'doc-'+'A'*64,'unit-'+'0'*64])
def test_invalid_document_id_rejected_before_io(prepared,monkeypatch,uid):
    manager,*_=prepared
    def forbidden():pytest.fail('invalid ID must not read catalog')
    monkeypatch.setattr(manager.catalog,'read',forbidden)
    with pytest.raises(StorageError,match='document_invalid_request'):manager.get_document_detail(uid)


@pytest.mark.parametrize('mode',['empty','blank'])
def test_active_empty_and_blank_document(prepared,tmp_path,mode):
    manager,*_=prepared;child=tmp_path/'empty-source';child.mkdir();bundle=make_bundle(child,mode)
    selected=publish(manager,bundle)
    result=manager.list_documents();assert result.active==selected
    assert len(result.documents)==(mode=='blank') and sum(d.chunk_count for d in result.documents)==0
    missing=manager.get_document_detail('doc-'+'0'*64)
    assert missing.active==selected and missing.document is None and missing.chunk_ids==[]
    if mode=='blank':
        detail=manager.get_document_detail(result.documents[0].document_id)
        assert detail.document.size_bytes==0 and detail.chunk_ids==[]


@pytest.mark.parametrize('operation',['list','detail'])
def test_activation_during_read_does_not_mix_versions(prepared,tmp_path,monkeypatch,operation):
    manager,uid,bundle,_,_=prepared;old=manager.activate(uid,expected_revision=0).active
    path=tmp_path/'source'/'L1_Module.md';path.write_text('# 模块v2\n\n新增规则。\n')
    (tmp_path/'source'/'L2_B.md').write_text('# 新需求B\n\n保留历史A用于回归。\n')
    candidate=rebuild(tmp_path,bundle)
    newer=DocumentManager(manager.settings,manager.chroma_settings,manager.bm25_settings,project_root=tmp_path)
    new_uid=BundleStore(manager.settings).save(candidate).bundle_id
    VectorUpserter(manager.settings,manager.chroma_settings,project_root=tmp_path).build(new_uid)
    BM25Indexer(manager.settings,manager.bm25_settings).build(new_uid)
    read=manager.catalog.read;load=manager.bundles.load;calls=[]
    def select_then_activate():
        calls.append('catalog');saved=read();newer.activate(new_uid,expected_revision=1);return saved
    def loaded(uid):calls.append('bundle');return load(uid)
    monkeypatch.setattr(manager.catalog,'read',select_then_activate);monkeypatch.setattr(manager.bundles,'load',loaded)
    old_doc=next(d for d in bundle.documents if d.metadata['source_path']=='L1_Module.md')
    result=manager.list_documents() if operation=='list' else manager.get_document_detail(old_doc.id)
    assert calls==['catalog','bundle'] and result.active==old
    item=next(i for i in result.documents if i.document_id==old_doc.id) if operation=='list' else result.document
    assert item.source_sha256==old_doc.metadata['source_sha256']
    monkeypatch.setattr(manager.catalog,'read',read)
    fresh=manager.list_documents();assert fresh.active.revision==2 and len(fresh.documents)==4
    assert {'L2_A.md','L2_A_测试用例.md','L2_B.md'}<=set(i.source_path for i in fresh.documents)
    assert next(i for i in fresh.documents if i.document_id==old_doc.id).source_sha256!=item.source_sha256
    def forbidden(*args):pytest.fail('revision conflict must not load a bundle')
    monkeypatch.setattr(manager.bundles,'load',forbidden)
    with pytest.raises(StorageError,match='catalog_revision_conflict'):
        manager.get_document_detail(old_doc.id,expected_revision=1)


@pytest.mark.parametrize('field',['document_count','chunk_count','source_fingerprint','model_space_id',
    'representation_id','tokenizer_id','dimensions'])
def test_active_bundle_identity_mismatch_fails(prepared,field):
    manager,uid,_,_,_=prepared;selected=manager.activate(uid,expected_revision=0).active
    raw=selected.version.to_dict();raw.pop('version_id')
    raw[field]=raw[field]+1 if type(raw[field]) is int else 'f'*64
    raw['version_id']=_digest(_json_bytes(raw,65536,newline=False))
    with manager.catalog.write() as conn:manager.catalog.publish(conn,IndexVersion.from_dict(raw),2)
    with pytest.raises(StorageError,match='catalog_identity_mismatch'):manager.list_documents()


@pytest.mark.parametrize('backend',['chroma','bm25'])
def test_broken_index_does_not_hide_document_snapshot(prepared,backend):
    manager,uid,_,_,_=prepared;selected=manager.activate(uid,expected_revision=0).active
    namespace,index_id=('vectors',selected.version.vector_index_id) if backend=='chroma' else ('bm25',selected.version.bm25_index_id)
    marker=manager.catalog.path.parent/namespace/index_id/'ready.json';marker.write_text('{}')
    result=manager.list_documents();assert result.active==selected and len(result.documents)==3
    assert manager.get_document_detail(result.documents[0].document_id).document is not None
    with pytest.raises(StorageError):manager.open_active()


@pytest.mark.parametrize('fault',['catalog','bundle','close'])
def test_critical_read_failures_are_not_empty(prepared,monkeypatch,fault,caplog):
    manager,uid,_,_,_=prepared;manager.activate(uid,expected_revision=0)
    if fault=='catalog':manager.catalog.path.write_bytes(b'bad sqlite')
    elif fault=='bundle':(manager.catalog.path.parent/'artifacts'/uid/'chunks.json').write_text('[]')
    else:
        original=manager.catalog._close
        def fail(conn):original(conn);raise OSError(PRIVATE)
        monkeypatch.setattr(manager.catalog,'_close',fail)
    with pytest.raises(StorageError):manager.list_documents()
    with pytest.raises(StorageError):manager.get_document_detail('doc-'+'0'*64)
    assert PRIVATE not in caplog.text


def test_output_and_input_limits_do_not_truncate(prepared,monkeypatch):
    manager,uid,_,_,_=prepared;manager.activate(uid,expected_revision=0)
    # Keep the validated readers' original limits to isolate the final response-size boundary.
    old_settings=manager.settings;manager.settings=replace(old_settings,max_bundle_bytes=1,max_file_bytes=1,max_manifest_bytes=1)
    with pytest.raises(StorageError,match='document_limit_exceeded'):manager.list_documents()
    with pytest.raises(StorageError,match='document_limit_exceeded'):manager.get_document_detail('doc-'+'0'*64)
    manager.settings=replace(old_settings,max_documents=1)
    manager.bundles=BundleStore(manager.settings)
    with pytest.raises(StorageError,match='bundle_limit_exceeded'):manager.list_documents()


def test_same_bytes_different_paths_are_distinct_saved_documents(prepared,tmp_path):
    manager,_,bundle,_,_=prepared;source=tmp_path/'source'
    (source/'L2_Copy.md').write_bytes((source/'L2_A.md').read_bytes())
    candidate=rebuild(tmp_path,bundle);selected=publish(manager,candidate)
    listing=manager.list_documents()
    items=[i for i in listing.documents if i.source_path in ('L2_A.md','L2_Copy.md')]
    assert len(items)==2 and len({i.document_id for i in items})==2
    assert len({i.source_sha256 for i in items})==1
    details=[manager.get_document_detail(i.document_id,expected_revision=selected.revision) for i in items]
    assert all(d.document==i and d.chunk_ids for d,i in zip(details,items))
    assert not set(details[0].chunk_ids)&set(details[1].chunk_ids)
