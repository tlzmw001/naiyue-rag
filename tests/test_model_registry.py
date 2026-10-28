"""Model settings and credentials are strict and never implicitly fall back."""
import copy
from importlib.resources import files
import json
from pathlib import Path
import pytest
from naiyue_rag import load_application_settings
from naiyue_rag.core.errors import SettingsError
from test_application_settings import configuration,write
from test_encoding_settings import config_data
from test_settings import offline

KEY='SYNTHETIC_PRIVATE_KEY'


def model_data():
    raw=json.loads(files('naiyue_rag.resources').joinpath('models.json').read_text())
    raw['models']['embedding']={'kind':'embedding',**config_data()['embedding'],'api_key':KEY}
    raw['models']['reranker'].update(model='synthetic-model',base_url='https://synthetic.invalid/v1/',api_key_env='SYNTHETIC_RERANK_KEY')
    return raw


def settings_at(root,raw=None):
    cfg=configuration();encoded=config_data();encoded.pop('embedding');encoded['model']='embedding';cfg['encoding']=encoded
    cfg['paths']['knowledge_base_root']='source'
    write(root/'config.yaml',cfg)
    (root/'models.json').write_text(json.dumps(model_data() if raw is None else raw),encoding='utf-8')
    return load_application_settings(root/'config.yaml')


def registry_at(root,raw=None):
    from naiyue_rag.core.model_registry import load_model_registry
    return load_model_registry(settings_at(root,raw))


def test_model_identity_reuses_actual_core_fields_and_key_is_private(tmp_path):
    registry=registry_at(tmp_path)
    assert registry.encoding_settings().to_dict()==config_data()
    assert registry.resolve_key('embedding',environ={})==KEY
    assert registry.resolve_key('reranker',environ={'SYNTHETIC_RERANK_KEY':'SECOND_SYNTHETIC_KEY'})=='SECOND_SYNTHETIC_KEY'
    assert registry.llm_settings('reranker').model=='synthetic-model'
    assert registry.local_settings('local-reranker').model_path==str(tmp_path/'data/models/mmarco-mMiniLMv2-L12-H384-v1')
    assert KEY not in repr(registry) and not (tmp_path/'data').exists()


@pytest.mark.parametrize('environment',[{}, {'SYNTHETIC_RERANK_KEY':''},{'SYNTHETIC_RERANK_KEY':'bad\nkey'}])
def test_selected_environment_is_required_without_dotenv_fallback(tmp_path,environment,caplog):
    registry=registry_at(tmp_path)
    (tmp_path/'.env').write_text('SYNTHETIC_RERANK_KEY=SHOULD_NOT_BE_READ')
    with pytest.raises(SettingsError,match='model_credential_invalid'):registry.resolve_key('reranker',environ=environment)
    assert 'SHOULD_NOT_BE_READ' not in caplog.text and KEY not in caplog.text


@pytest.mark.parametrize('fault',['extra','version','duplicate-role','kind','provider','key-both','key-none','empty-key','bad-env','dimensions','url','local-path','model-id'])
def test_bad_registry_fails_without_secrets(tmp_path,caplog,fault):
    raw=model_data();model=raw['models']['embedding']
    if fault=='extra':raw['extra']=1
    elif fault=='version':raw['config_version']=True
    elif fault=='duplicate-role':model['unexpected']=1
    elif fault=='kind':model['kind']='unknown'
    elif fault=='provider':model['provider']='unsupported'
    elif fault=='key-both':model['api_key_env']='OTHER_KEY'
    elif fault=='key-none':model.pop('api_key')
    elif fault=='empty-key':model['api_key']=''
    elif fault=='bad-env':model.pop('api_key');model['api_key_env']='bad-name'
    elif fault=='dimensions':model['expected_dimensions']=True
    elif fault=='url':model['base_url']='https://user:secret@synthetic.invalid/'
    elif fault=='local-path':raw['models']['local-reranker']['model_path']='../outside'
    else:raw['models']['bad/id']=raw['models'].pop('embedding')
    with pytest.raises(SettingsError,match='invalid_models_settings'):registry_at(tmp_path,raw)
    assert KEY not in caplog.text and 'user:secret' not in caplog.text


@pytest.mark.parametrize('payload',['{"config_version":1,"config_version":1,"models":{}}','{"config_version":NaN,"models":{}}',' '*65537],ids=['duplicate','NaN','oversize'])
def test_duplicate_or_unbounded_json_is_rejected(tmp_path,payload):
    from naiyue_rag.core.model_registry import load_model_registry
    cfg=settings_at(tmp_path);Path(cfg.models_file).write_text(payload)
    with pytest.raises(SettingsError):load_model_registry(cfg)


def test_unknown_models_and_role_mismatch_are_explicit(tmp_path):
    registry=registry_at(tmp_path)
    for call in [lambda:registry.encoding_settings('reranker'),lambda:registry.llm_settings('embedding'),
                 lambda:registry.local_settings('reranker'),lambda:registry.resolve_key('unknown')]:
        with pytest.raises(SettingsError,match='model_selection_invalid'):call()


@pytest.mark.parametrize('mode',['missing','directory','symlink'])
def test_registry_requires_an_explicit_regular_file(tmp_path,mode):
    from naiyue_rag.core.model_registry import load_model_registry
    cfg=settings_at(tmp_path);p=Path(cfg.models_file);p.unlink()
    if mode=='directory':p.mkdir()
    elif mode=='symlink':
        target=tmp_path/'private.json';target.write_text(json.dumps(model_data()));p.symlink_to(target)
    with pytest.raises(SettingsError,match='models_file_error'):load_model_registry(cfg)
