"""Explicit project credential resolution with no global environment mutation or network."""
import os
from pathlib import Path
import subprocess
import pytest
from naiyue_rag.core.credentials import resolve_api_key,MAX_ENV_BYTES
from naiyue_rag.core.errors import SettingsError
from test_document_chunker import offline

NAME='NAIYUE_RAG_ZHIPU_API_KEY'
PRIVATE='SYNTHETIC_PRIVATE'


def test_named_environment_wins_without_reading_file(tmp_path,monkeypatch):
    (tmp_path/'.env').write_text('malformed='+PRIVATE+'\nBROKEN="unterminated')
    import naiyue_rag.core.credentials as module
    monkeypatch.setattr(module,'_read_project_env',lambda root:pytest.fail('env should not be read'))
    assert resolve_api_key(tmp_path,NAME,environ={NAME:'environment-key'})=='environment-key'

@pytest.mark.parametrize('value',['',' ',PRIVATE+' ',PRIVATE+'\n',True,None,'密钥'])
def test_present_but_invalid_environment_never_falls_back(tmp_path,value,caplog):
    (tmp_path/'.env').write_text(f'{NAME}=file-key\n')
    with pytest.raises(SettingsError,match='^credential_invalid$'):resolve_api_key(tmp_path,NAME,environ={NAME:value})
    assert PRIVATE not in caplog.text

@pytest.mark.parametrize('text,expected',[
    (f'{NAME}=file-key\n','file-key'),
    (f'export {NAME} = "key=with=equals" # note\n','key=with=equals'),
    (f"# comment\n{NAME}='key#literal'\n",'key#literal'),
    ('\ufeff'+f'{NAME}=bom-key\n','bom-key'),
    (f'{NAME}=${{OTHER_KEY}}\n','${OTHER_KEY}'),
])
def test_dotenv_syntax_and_literal_value_without_interpolation(tmp_path,text,expected):
    (tmp_path/'.env').write_text(text)
    assert resolve_api_key(tmp_path,NAME,environ={'OTHER_KEY':'do-not-expand'})==expected


def test_project_root_is_explicit_and_only_selected_value_is_used(tmp_path,monkeypatch):
    root=tmp_path/'project';root.mkdir();nested=root/'nested';nested.mkdir()
    (tmp_path/'.env').write_text(f'{NAME}=wrong-parent\n')
    (root/'.env').write_text(f'{NAME}=right-key\nOPENAI_LOG=debug\nOTHER=ignored\n')
    monkeypatch.chdir(nested);monkeypatch.delenv(NAME,raising=False)
    before=dict(os.environ)
    assert resolve_api_key(root,NAME)=='right-key'
    assert dict(os.environ)==before
    with pytest.raises(SettingsError,match='credential_not_found'):resolve_api_key(nested,NAME,environ={})

@pytest.mark.parametrize('text,code',[
    ('OTHER=unused\n','credential_not_found'),
    (f'{NAME}=\n','credential_invalid'),
    (f'{NAME}\n','credential_invalid'),
    (f'{NAME}="bad key"\n','credential_invalid'),
    (f'{NAME}=first\n{NAME}=second\n','credential_env_invalid'),
    ('OTHER=a\nOTHER=b\n','credential_env_invalid'),
    (f'{NAME}="unterminated\n','credential_env_invalid'),
    (f'{NAME}="line\\nsecret"\n','credential_invalid'),
])
def test_bad_or_missing_selected_key_is_explicit(tmp_path,text,code,caplog):
    (tmp_path/'.env').write_text(text.replace('secret',PRIVATE))
    with pytest.raises(SettingsError,match='^'+code+'$') as caught:resolve_api_key(tmp_path,NAME,environ={})
    assert PRIVATE not in str(caught.value)+caplog.text

@pytest.mark.parametrize('fault',['missing','directory','symlink','fifo','bad-utf8','too-large','read-permission','identity-race'])
def test_file_failure_is_bounded_and_observable(tmp_path,monkeypatch,fault,caplog):
    import naiyue_rag.core.credentials as module
    path=tmp_path/'.env';code='credential_file_error'
    if fault=='missing':code='credential_not_found'
    elif fault=='directory':path.mkdir()
    elif fault=='symlink':
        target=tmp_path/'key';target.write_text(f'{NAME}={PRIVATE}');path.symlink_to(target)
    elif fault=='fifo':os.mkfifo(path)
    elif fault=='bad-utf8':path.write_bytes(b'\xff');code='credential_env_invalid'
    elif fault=='too-large':path.write_bytes(b'a'*(MAX_ENV_BYTES+1));code='credential_file_too_large'
    else:
        path.write_text(f'{NAME}={PRIVATE}')
        if fault=='read-permission':
            def denied(*args,**kwargs):raise PermissionError(PRIVATE)
            monkeypatch.setattr(module.os,'open',denied)
        else:
            original=module.os.fstat
            def different(fd):
                from types import SimpleNamespace
                observed=original(fd)
                return SimpleNamespace(st_mode=observed.st_mode,st_ino=observed.st_ino+1,st_dev=observed.st_dev,st_size=observed.st_size)
            monkeypatch.setattr(module.os,'fstat',different)
    with pytest.raises(SettingsError,match='^'+code+'$') as caught:resolve_api_key(tmp_path,NAME,environ={})
    assert PRIVATE not in str(caught.value)+caplog.text
    assert 'credential_' in caplog.text

@pytest.mark.parametrize('name',['','A-B','1KEY','../.env',None,True])
def test_invalid_key_name_is_not_an_arbitrary_source(tmp_path,name):
    with pytest.raises(SettingsError,match='credential_invalid_name'):resolve_api_key(tmp_path,name,environ={})


def test_other_provider_can_use_an_explicit_credential_name(tmp_path):
    (tmp_path/'.env').write_text('CUSTOM_EMBEDDING_KEY=another-key\n'+NAME+'=wrong-key\n')
    assert resolve_api_key(tmp_path,'CUSTOM_EMBEDDING_KEY',environ={})=='another-key'
    with pytest.raises(SettingsError,match='credential_not_found'):
        resolve_api_key(tmp_path,'UNCONFIGURED_KEY',environ={'OPENAI_API_KEY':'do-not-guess'})


def test_only_root_example_is_unignored():
    result=subprocess.run(['git','check-ignore','--no-index','--stdin'],input='.env\n.env.local\n.env.example\nchild/.env.example\n',
                          text=True,capture_output=True,check=False)
    assert result.returncode==0
    assert result.stdout.splitlines()==['.env','.env.local','child/.env.example']
    assert 'NAIYUE_RAG_ZHIPU_API_KEY=' in Path('.env.example').read_text()


def test_file_descriptor_is_closed_when_stream_creation_fails(tmp_path,monkeypatch):
    import naiyue_rag.core.credentials as module
    (tmp_path/'.env').write_text(f'{NAME}={PRIVATE}')
    original_close=module.os.close;closed=[]
    def close(fd):closed.append(fd);return original_close(fd)
    def broken(*args,**kwargs):raise OSError(PRIVATE)
    monkeypatch.setattr(module.os,'fdopen',broken);monkeypatch.setattr(module.os,'close',close)
    with pytest.raises(SettingsError,match='credential_file_error'):resolve_api_key(tmp_path,NAME,environ={})
    assert len(closed)==1
