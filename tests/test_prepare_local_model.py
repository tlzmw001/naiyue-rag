"""Explicit pinned model preparation; transport is fake, integrity is real."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_cross_encoder_reranker import config


@pytest.fixture
def source(tmp_path,monkeypatch):
    import huggingface_hub
    cfg=config(tmp_path);files={'config.json':b'{}','tokenizer.json':b'{}','tokenizer_config.json':b'{"model_max_length":512}',
        'model.safetensors':b'SYNTHETIC_WEIGHT','README.md':b'Apache-2.0'}
    calls=[]
    siblings=[SimpleNamespace(rfilename=n,size=len(v),blob_id=hashlib.sha1(b'blob '+str(len(v)).encode()+b'\0'+v).hexdigest(),
        lfs=SimpleNamespace(sha256=hashlib.sha256(v).hexdigest()) if n=='model.safetensors' else None) for n,v in files.items()]
    info=SimpleNamespace(sha=cfg.model_revision,siblings=siblings)
    class API:
        def model_info(self,repo_id,**kwargs):calls.append(('info',repo_id,kwargs));return info
    monkeypatch.setattr(huggingface_hub,'HfApi',API)
    def download(repo_id,filename,**kwargs):
        calls.append(('download',filename,kwargs));path=Path(kwargs['local_dir'])/filename;path.write_bytes(files[filename]);return str(path)
    monkeypatch.setattr(huggingface_hub,'hf_hub_download',download)
    return cfg,files,info,calls


def test_prepare_verifies_source_and_reuses_without_download(source):
    from naiyue_rag.validation.prepare_local_model import prepare_local_model
    from naiyue_rag.reranking.cross_encoder import audit_model
    cfg,files,info,calls=source
    result=prepare_local_model(cfg)
    assert result['status']=='prepared' and result['files']==len(files) and result['bytes']==sum(map(len,files.values()))
    assert audit_model(cfg)==Path(cfg.model_path)
    assert all(c[2]['token'] is False and c[2]['revision']==cfg.model_revision for c in calls)
    assert {c[1] for c in calls if c[0]=='download'}==set(files)
    calls.clear();assert prepare_local_model(cfg)['status']=='unchanged' and calls==[]


@pytest.mark.parametrize('fault',['revision','hash','limit','occupied','network'])
def test_prepare_failure_is_explicit_and_keeps_existing_files(source,monkeypatch,fault):
    from dataclasses import replace
    from naiyue_rag.validation.prepare_local_model import prepare_local_model,ModelPreparationError
    cfg,files,info,calls=source
    if fault=='revision':info.sha='b'*40
    elif fault=='hash':info.siblings[0].blob_id='0'*40
    elif fault=='limit':cfg=replace(cfg,max_model_bytes=1)
    elif fault=='occupied':
        Path(cfg.model_path).mkdir();(Path(cfg.model_path)/'keep.txt').write_text('keep')
    else:
        import huggingface_hub
        def fail(*args,**kwargs):raise OSError('SYNTHETIC_PRIVATE')
        monkeypatch.setattr(huggingface_hub,'hf_hub_download',fail)
    with pytest.raises(ModelPreparationError) as caught:prepare_local_model(cfg)
    assert 'SYNTHETIC_PRIVATE' not in str(caught.value)
    assert not (Path(cfg.model_path)/'naiyue-model.json').exists()
    if fault=='occupied':assert (Path(cfg.model_path)/'keep.txt').read_text()=='keep'
