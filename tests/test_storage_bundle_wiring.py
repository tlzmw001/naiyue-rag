"""Actual source/encoding boundary, private disk artifacts and reload failure paths."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import pytest
import httpx
from naiyue_rag.storage import BundleStore,prepare_index_bundle
from naiyue_rag.core.errors import StorageError
from test_storage_bundle import ingredients,make_bundle,storage_settings,KB,PRIVATE
from test_openai_embedding import safe_ambient,payload
from test_document_chunker import offline


def folder(cfg,receipt):
    return Path(cfg.storage_root)/hashlib.sha256(KB.encode()).hexdigest()/'artifacts'/receipt.bundle_id


def test_actual_sdk_sparse_and_new_process_reload(tmp_path,monkeypatch):
    from naiyue_rag import (OpenAICompatibleEmbedding,DenseEncoder,SparseEncoder,BatchProcessor,
                           prepare_document_encoding_inputs)
    from test_sparse_encoding_settings import sparse_config
    seen=[]
    def handle(request):
        wire=json.loads(request.content);seen.append(wire);raw=payload(len(wire['input']))
        raw['usage']={'prompt_tokens':7,'total_tokens':7}
        return httpx.Response(200,json=raw)
    monkeypatch.setattr(httpx,'HTTPTransport',lambda **kwargs:httpx.MockTransport(handle))
    data=ingredients(tmp_path);cfg=data['encoding_settings']
    with OpenAICompatibleEmbedding(cfg,api_key=PRIVATE) as provider:
        dense=DenseEncoder(cfg,provider);sparse=SparseEncoder(cfg,sparse_config(tmp_path))
        result=BatchProcessor(cfg,dense,sparse).process(prepare_document_encoding_inputs(data['documents'],data['chunks'],cfg))
    data['encoding_result']=result;bundle=prepare_index_bundle(**data)
    settings=storage_settings(tmp_path);store=BundleStore(settings);receipt=store.save(bundle)
    assert receipt.status=='ready' and receipt.document_count==3 and receipt.chunk_count==len(bundle.chunks)
    assert len(seen)==result.report.planned_batch_count and provider.closed
    assert all(r.sparse.tokens for r in bundle.encoding_result.records)
    assert store.load(receipt.bundle_id).to_dict()==bundle.to_dict()
    # Child gets only explicit config/ID, no model key, original source root or .env loader.
    script='''
import hashlib,json,sys,socket
sys.path.insert(0,sys.argv[1])
def forbidden(*a,**k):raise AssertionError('network forbidden')
socket.socket.connect=socket.socket.connect_ex=forbidden
from naiyue_rag.storage import StorageSettings,BundleStore
raw=json.load(sys.stdin)
bundle=BundleStore(StorageSettings.from_dict(raw['settings'])).load(raw['id'])
print(hashlib.sha256(json.dumps(bundle.to_dict(),ensure_ascii=False,sort_keys=True).encode()).hexdigest())
assert 'chromadb' not in sys.modules and 'openai' not in sys.modules
'''
    # Change the source: a reload must still return the saved version.
    (tmp_path/'source/L1_Module.md').write_text('changed after save')
    child=subprocess.run([sys.executable,'-c',script,str(Path.cwd())],
        input=json.dumps(dict(settings=settings.to_dict(),id=receipt.bundle_id)),text=True,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,cwd=tmp_path,env={},timeout=30)
    assert child.returncode==0
    expected=hashlib.sha256(json.dumps(bundle.to_dict(),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    assert child.stdout.strip()==expected
    root=folder(settings,receipt)
    assert stat.S_IMODE(root.stat().st_mode)==0o700
    assert all(stat.S_IMODE(p.stat().st_mode)==0o600 for p in root.iterdir())
    assert len(list(root.iterdir()))==5


def test_repeat_does_not_write_or_add_pending(tmp_path,monkeypatch):
    cfg=storage_settings(tmp_path);store=BundleStore(cfg);bundle=make_bundle(tmp_path)
    receipt=store.save(bundle);root=folder(cfg,receipt)
    before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
    monkeypatch.setattr(store,'_write_file',lambda *a:pytest.fail('repeat must not write'))
    again=store.save(bundle)
    assert again.status=='unchanged' and again.bundle_id==receipt.bundle_id
    assert before=={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
    assert len(list(root.parent.iterdir()))==1

@pytest.mark.parametrize('mode',['empty','blank'])
def test_empty_storage(tmp_path,mode):
    cfg=storage_settings(tmp_path);store=BundleStore(cfg);bundle=make_bundle(tmp_path,mode)
    receipt=store.save(bundle)
    assert receipt.chunk_count==0 and store.load(receipt.bundle_id).to_dict()==bundle.to_dict()

@pytest.mark.parametrize('key,value',[
    ('max_documents',1),('max_chunks',1),('max_file_bytes',20),('max_manifest_bytes',20),
    ('max_file_bytes',5000),('max_bundle_bytes',11000)])
def test_limits_before_filesystem_mutation(tmp_path,key,value):
    changes={key:value}
    if key=='max_bundle_bytes':changes.update(max_file_bytes=value,max_manifest_bytes=value)
    cfg=storage_settings(tmp_path,**changes);store=BundleStore(cfg);bundle=make_bundle(tmp_path)
    with pytest.raises(StorageError,match='bundle_limit_exceeded'):store.save(bundle)
    assert not Path(cfg.storage_root).exists()

@pytest.mark.parametrize('fault',['missing','extra','hash','size','utf8','truncated','duplicate','nan','manifest-extra','manifest-count-bool','manifest-id','manifest-limit','source-unbound'])
def test_corruption_is_not_repaired(tmp_path,fault):
    cfg=storage_settings(tmp_path);store=BundleStore(cfg);bundle=make_bundle(tmp_path);receipt=store.save(bundle);root=folder(cfg,receipt)
    manifest=json.loads((root/'manifest.json').read_text())
    if fault=='missing':(root/'chunks.json').unlink()
    elif fault=='extra':(root/'extra.json').write_text('{}')
    elif fault=='hash':(root/'chunks.json').write_bytes(b'[]\n')
    elif fault=='size':manifest['files']['chunks.json']['bytes']+=1
    elif fault=='utf8':(root/'relations.json').write_bytes(b'\xff')
    elif fault=='truncated':(root/'manifest.json').write_bytes(b'{')
    elif fault=='duplicate':(root/'manifest.json').write_bytes(b'{"status":"ready","status":"ready"}')
    elif fault=='nan':(root/'manifest.json').write_bytes(b'{"status":NaN}')
    elif fault=='manifest-extra':manifest['secret']=PRIVATE
    elif fault=='manifest-count-bool':manifest['document_count']=True
    elif fault=='manifest-id':manifest['bundle_id']='0'*64
    elif fault=='manifest-limit':(root/'manifest.json').write_bytes(b'x'*(cfg.max_manifest_bytes+1))
    else:
        raw=json.loads((root/'documents.json').read_text());raw[0]['text']=PRIVATE
        (root/'documents.json').write_text(json.dumps(raw))
    if fault in ('size','manifest-extra','manifest-count-bool','manifest-id'):(root/'manifest.json').write_text(json.dumps(manifest))
    before={p.name:p.read_bytes() for p in root.iterdir()}
    with pytest.raises(StorageError):store.load(receipt.bundle_id)
    with pytest.raises(StorageError):store.save(bundle)
    assert before=={p.name:p.read_bytes() for p in root.iterdir()}

@pytest.mark.parametrize('fault',['root','kb','artifacts','bundle','file','fifo'])
def test_symlinks_and_non_regular_files_are_refused(tmp_path,fault):
    cfg=storage_settings(tmp_path);store=BundleStore(cfg);receipt=store.save(make_bundle(tmp_path));root=folder(cfg,receipt)
    if fault=='fifo':
        (root/'chunks.json').unlink();os.mkfifo(root/'chunks.json')
    elif fault=='file':
        (root/'chunks.json').rename(root/'held.json');(root/'chunks.json').symlink_to(root/'held.json')
    else:
        path={'root':Path(cfg.storage_root),'kb':root.parent.parent,'artifacts':root.parent,'bundle':root}[fault]
        target=path.with_name(path.name+'-held');path.rename(target);path.symlink_to(target,target_is_directory=True)
    with pytest.raises(StorageError):store.load(receipt.bundle_id)

@pytest.mark.parametrize('uid',['../bad','x','a'*63,'A'*64,True,None])
def test_invalid_ids_have_no_write_side_effects(tmp_path,uid):
    cfg=storage_settings(tmp_path);store=BundleStore(cfg)
    with pytest.raises(StorageError,match='invalid_bundle_id'):store.load(uid)
    assert not Path(cfg.storage_root).exists()


def test_missing_bundle_is_read_only(tmp_path):
    cfg=storage_settings(tmp_path)
    with pytest.raises(StorageError,match='bundle_not_found'):BundleStore(cfg).load('0'*64)
    assert not Path(cfg.storage_root).exists()

@pytest.mark.parametrize('fault',['mkdir','write','flush','fsync-file','fsync-directory','rename','fsync-after-rename','read'])
def test_critical_io_fails_safely(tmp_path,monkeypatch,fault,caplog):
    import naiyue_rag.storage.bundle_store as module
    cfg=storage_settings(tmp_path);store=BundleStore(cfg);bundle=make_bundle(tmp_path)
    def fail(*a,**k):raise OSError(PRIVATE)
    if fault=='read':
        receipt=store.save(bundle);monkeypatch.setattr(store,'_read_file',fail)
        with pytest.raises(StorageError):store.load(receipt.bundle_id)
    else:
        if fault=='mkdir':monkeypatch.setattr(module.os,'mkdir',fail)
        elif fault=='write':monkeypatch.setattr(store,'_write_file',fail)
        elif fault=='flush':
            original=module.os.fdopen
            class Stream:
                def __init__(self,*args,**kwargs):self.stream=original(*args,**kwargs)
                def __enter__(self):return self
                def __exit__(self,*args):self.stream.close()
                def write(self,data):return self.stream.write(data)
                def flush(self):fail()
                def fileno(self):return self.stream.fileno()
            monkeypatch.setattr(module.os,'fdopen',Stream)
        elif fault=='fsync-file':monkeypatch.setattr(module.os,'fsync',fail)
        elif fault=='fsync-directory':monkeypatch.setattr(store,'_sync_directory',fail)
        elif fault=='rename':monkeypatch.setattr(module.os,'rename',fail)
        else:
            normal=store._sync_directory;calls=[]
            def after(path):
                calls.append(path)
                if len(calls)==2:fail()
                return normal(path)
            monkeypatch.setattr(store,'_sync_directory',after)
        expected='bundle_publish_uncertain' if fault=='fsync-after-rename' else None
        with pytest.raises(StorageError) as caught:store.save(bundle)
        if expected:assert caught.value.code==expected
        if Path(cfg.storage_root).exists():
            published=list(Path(cfg.storage_root).glob('*/artifacts/[0-9a-f]*'))
            assert bool(published)==(fault=='fsync-after-rename')
    assert PRIVATE not in caplog.text


def test_revision_and_historical_l2_are_separate_saved_artifacts(tmp_path):
    data=ingredients(tmp_path);cfg=storage_settings(tmp_path);store=BundleStore(cfg)
    old=store.save(prepare_index_bundle(**data));root=tmp_path/'source'
    (root/'L1_Module.md').write_text('# 模块\n\nfeature_x开启时支持新策略。\n')
    (root/'L2_B.md').write_text('# 新需求B\n\n新策略仅改部分原功能。\n')
    from naiyue_rag import MarkdownLoader,DocumentChunker,prepare_knowledge_base,prepare_document_encoding_inputs,BatchProcessor
    from test_storage_bundle import Dense,Sparse
    docs=MarkdownLoader(root,KB,4096).load_all();chunks,relations,_=prepare_knowledge_base(docs,DocumentChunker(data['ingestion_settings']),text_mode='raw')
    model=data['encoding_settings'];result=BatchProcessor(model,Dense(model),Sparse(model)).process(prepare_document_encoding_inputs(docs,chunks,model))
    new=store.save(prepare_index_bundle(docs,chunks,relations,result,knowledge_base_id=KB,encoding_settings=model,ingestion_settings=data['ingestion_settings']))
    assert new.bundle_id!=old.bundle_id
    before={d.metadata['source_path']:d.text for d in store.load(old.bundle_id).documents}
    after={d.metadata['source_path']:d.text for d in store.load(new.bundle_id).documents}
    assert before['L2_A.md']==after['L2_A.md'] and 'L2_B.md' in after and 'L2_B.md' not in before
    assert before['L1_Module.md']!=after['L1_Module.md']


def test_all_new_artifact_directories_are_private(tmp_path):
    cfg=storage_settings(tmp_path);receipt=BundleStore(cfg).save(make_bundle(tmp_path));root=Path(cfg.storage_root)
    created=[root,*[p for p in root.rglob('*') if p.is_dir()]]
    assert all(stat.S_IMODE(path.stat().st_mode)==0o700 for path in created)


def test_short_write_cannot_publish_an_incomplete_bundle(tmp_path,monkeypatch):
    import naiyue_rag.storage.bundle_store as module
    cfg=storage_settings(tmp_path);bundle=make_bundle(tmp_path);normal=module.os.fdopen
    class Partial:
        def __init__(self,*args,**kwargs):self.stream=normal(*args,**kwargs)
        def __enter__(self):return self
        def __exit__(self,*args):self.stream.close()
        def write(self,data):return self.stream.write(data[:1])
        def flush(self):return self.stream.flush()
        def fileno(self):return self.stream.fileno()
    monkeypatch.setattr(module.os,'fdopen',Partial)
    with pytest.raises(StorageError,match='bundle_write_failed'):BundleStore(cfg).save(bundle)
    assert not list(Path(cfg.storage_root).glob('*/artifacts/[0-9a-f]*'))


def test_valid_file_hashes_cannot_replace_source_binding(tmp_path):
    cfg=storage_settings(tmp_path);store=BundleStore(cfg);receipt=store.save(make_bundle(tmp_path));root=folder(cfg,receipt)
    def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    documents=json.loads((root/'documents.json').read_text());documents[0]['text']+=PRIVATE
    raw=canonical(documents)+b'\n';(root/'documents.json').write_bytes(raw)
    manifest=json.loads((root/'manifest.json').read_text())
    manifest['files']['documents.json']=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    unsigned={k:v for k,v in manifest.items() if k!='bundle_id'}
    uid=hashlib.sha256(canonical(unsigned)).hexdigest();manifest['bundle_id']=uid
    (root/'manifest.json').write_bytes(canonical(manifest)+b'\n');root.rename(root.with_name(uid))
    # All disk hashes are consistent; M1/M2/M3 binding must still refuse the changed source.
    with pytest.raises(StorageError,match='invalid_index_bundle|bundle_source_mismatch'):store.load(uid)

@pytest.mark.parametrize('limit',['max_documents','max_chunks','max_file_bytes','max_bundle_bytes'])
def test_reload_respects_current_resource_limits(tmp_path,limit):
    cfg=storage_settings(tmp_path);receipt=BundleStore(cfg).save(make_bundle(tmp_path))
    changes={limit:1}
    if limit=='max_bundle_bytes':changes.update(max_file_bytes=1,max_manifest_bytes=1)
    restricted=storage_settings(tmp_path,**changes)
    with pytest.raises(StorageError,match='bundle_limit_exceeded'):BundleStore(restricted).load(receipt.bundle_id)

@pytest.mark.parametrize('action',['write','read'])
def test_stream_creation_failure_closes_raw_descriptor(tmp_path,monkeypatch,action):
    import naiyue_rag.storage.bundle_store as module
    cfg=storage_settings(tmp_path);store=BundleStore(cfg);bundle=make_bundle(tmp_path)
    receipt=store.save(bundle) if action=='read' else None
    closed=[];original_close=module.os.close
    def broken(*args,**kwargs):raise OSError(PRIVATE)
    def close(fd):closed.append(fd);return original_close(fd)
    monkeypatch.setattr(module.os,'fdopen',broken);monkeypatch.setattr(module.os,'close',close)
    with pytest.raises(StorageError):store.load(receipt.bundle_id) if action=='read' else store.save(bundle)
    assert len(closed)==1
