"""Default configuration creation is private, complete, and never overwrites."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import pytest
import yaml
from naiyue_rag.core.errors import SettingsError
from test_settings import offline


@pytest.fixture
def home(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path));monkeypatch.setenv('USERPROFILE',str(tmp_path));return tmp_path


def load():
    from naiyue_rag import load_application_settings
    return load_application_settings()


def test_first_run_creates_only_templates_and_reuses_them(home):
    value=load();folder=home/'.naiyue-rag';config=folder/'config.yaml';models=folder/'models.json'
    assert value.config_path==str(config) and value.models_file==str(models)
    assert len(value.service.access_token)>=32
    registry=json.loads(models.read_text());assert registry['config_version']==1
    assert registry['models']['embedding']['api_key_env']=='NAIYUE_RAG_ZHIPU_API_KEY'
    assert all('api_key' not in m for m in registry['models'].values())
    before={p.name:p.read_bytes() for p in folder.iterdir()}
    assert load().to_dict()==value.to_dict()
    assert {p.name:p.read_bytes() for p in folder.iterdir()}==before
    assert set(before)=={'config.yaml','models.json'} and not Path(value.data_root).exists()
    if __import__('os').name!='nt':
        assert folder.stat().st_mode&0o777==0o700
        assert config.stat().st_mode&0o777==models.stat().st_mode&0o777==0o600


def test_existing_user_model_file_is_preserved(home):
    folder=home/'.naiyue-rag';folder.mkdir();file=folder/'models.json'
    private=b'{"user_owned": "SYNTHETIC_NOT_A_KEY"}\n';file.write_bytes(private)
    assert load().models_file==str(file)
    assert file.read_bytes()==private


def test_user_edits_and_missing_registry_are_not_repaired(home):
    value=load();config=Path(value.config_path);registry=Path(value.models_file)
    raw=yaml.safe_load(config.read_text());raw['service']['port']=8181
    config.write_text(yaml.safe_dump(raw));registry.unlink()
    before=config.read_bytes();again=load()
    assert again.service.port==8181 and config.read_bytes()==before and not registry.exists()


def test_invalid_existing_configuration_is_preserved(home):
    folder=home/'.naiyue-rag';folder.mkdir();file=folder/'config.yaml';file.write_text('user: invalid')
    with pytest.raises(SettingsError,match='invalid_application_settings'):load()
    assert file.read_text()=='user: invalid' and not (folder/'models.json').exists()


def test_parallel_initialization_publishes_one_complete_winner(home):
    barrier=threading.Barrier(4)
    def run(_):barrier.wait();return load()
    with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(run,range(4)))
    assert len({v.service.access_token for v in values})==1
    assert all(v.to_dict()==values[0].to_dict() for v in values)
    assert {p.name for p in (home/'.naiyue-rag').iterdir()}=={'config.yaml','models.json'}


@pytest.mark.parametrize('mode',['file','symlink','config-directory'])
def test_invalid_default_locations_never_overwrite_user_assets(home,mode):
    folder=home/'.naiyue-rag'
    if mode=='file':folder.write_text('user data')
    elif mode=='symlink':
        target=home/'target';target.mkdir();folder.symlink_to(target,target_is_directory=True)
    else:folder.mkdir();(folder/'config.yaml').mkdir()
    with pytest.raises(SettingsError):load()
    if mode=='file':assert folder.read_text()=='user data'
    elif mode=='symlink':assert list((home/'target').iterdir())==[]
    else:assert list((folder/'config.yaml').iterdir())==[]


@pytest.mark.parametrize('operation',['fsync','link'])
def test_publish_failures_are_observable_and_leave_no_partial_config(home,monkeypatch,caplog,operation):
    import naiyue_rag.core.configuration_bootstrap as module
    def fail(*args,**kwargs):raise OSError('SYNTHETIC_PRIVATE_IO')
    monkeypatch.setattr(module.os,operation,fail)
    with pytest.raises(SettingsError,match='configuration_initialization_failed'):load()
    assert not (home/'.naiyue-rag/config.yaml').exists()
    assert not list((home/'.naiyue-rag').glob('.*.tmp-*'))
    assert 'configuration_initialization_failed' in caplog.text and 'SYNTHETIC_PRIVATE_IO' not in caplog.text


def test_stream_construction_failure_closes_owned_descriptor(tmp_path,monkeypatch):
    import errno
    import os
    import tempfile
    from naiyue_rag.core.configuration_bootstrap import _publish
    from naiyue_rag.core.errors import SettingsError
    original=tempfile.mkstemp;owned=[]
    def tracked(*args,**kwargs):
        fd,name=original(*args,**kwargs);owned.append(fd);return fd,name
    def fail(*args,**kwargs):raise OSError('SYNTHETIC_PRIVATE_STREAM_FAILURE')
    monkeypatch.setattr(tempfile,'mkstemp',tracked);monkeypatch.setattr(os,'fdopen',fail)
    try:
        with pytest.raises(SettingsError,match='configuration_initialization_failed'):_publish(tmp_path/'config.yaml',b'complete')
        with pytest.raises(OSError) as caught:os.fstat(owned[0])
        assert caught.value.errno==errno.EBADF
        assert list(tmp_path.iterdir())==[]
    finally:
        for fd in owned:
            try:os.close(fd)
            except OSError as error:
                if error.errno!=errno.EBADF:raise
