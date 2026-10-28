"""Unified settings consume existing contracts without loading models or storage."""
import copy
from pathlib import Path
import pytest
import yaml
from naiyue_rag.core.errors import SettingsError
from test_settings import offline

ROOT=Path(__file__).resolve().parents[1]


def configuration():
    def sample(name):return yaml.safe_load((ROOT/'examples/core-demo'/f'{name}.example.yaml').read_text())
    encoding=sample('encoding');encoding.pop('embedding');encoding['model']='embedding'
    rerank=sample('rerank');rerank.pop('enabled');rerank.update(backend='llm',model='reranker')
    storage=sample('storage');storage['storage_root']='indexes'
    sparse=sample('sparse');sparse['cache_dir']='cache/sparse'
    return dict(config_version=1,paths=dict(data_root='data',knowledge_base_root='knowledge'),models_file='models.json',
        service=dict(host='127.0.0.1',port=8000,access_token='SYNTHETIC_TOKEN_'+'a'*32,startup_timeout_seconds=30,
            shutdown_timeout_seconds=10,request_timeout_seconds=180,max_request_bytes=1048576),
        ingestion=dict(chunk_size=1000,chunk_overlap=300,chunking_policy='markdown-source-zh-v2'),encoding=encoding,
        sparse=sparse,storage=storage,rerank=rerank,**{k:sample(k) for k in ('chroma','bm25','hybrid','evidence')})


def write(path,raw=None):
    path.write_text(yaml.safe_dump(configuration() if raw is None else raw),encoding='utf-8');return path


def load(path):
    from naiyue_rag import load_application_settings
    return load_application_settings(path)


def test_paths_and_typed_contracts_are_loaded_without_side_effects(tmp_path,monkeypatch):
    source=write(tmp_path/'config.yaml');other=tmp_path/'other';other.mkdir();monkeypatch.chdir(other)
    value=load(source)
    assert value.config_path==str(source) and value.data_root==str(tmp_path/'data')
    assert value.models_file==str(tmp_path/'models.json') and value.knowledge_base_root==str(tmp_path/'knowledge')
    assert value.storage.storage_root==str(tmp_path/'data/indexes')
    assert value.sparse.cache_dir==str(tmp_path/'data/cache/sparse')
    assert value.ingestion.chunking_policy=='markdown-source-zh-v2'
    assert value.encoding.model=='embedding' and value.encoding.runtime.max_inputs==1000
    assert value.rerank.backend=='llm' and value.rerank.settings.enabled
    assert value.hybrid.rrf_k==60 and value.evidence.max_context_characters==8000
    assert value.service.port==8000 and value.service.access_token not in repr(value)
    assert not (tmp_path/'data').exists() and not (tmp_path/'knowledge').exists() and not (tmp_path/'models.json').exists()
    exposed=value.to_dict();exposed['encoding']['runtime']['max_inputs']=1
    assert value.encoding.runtime.max_inputs==1000
    assert load(write(source,value.to_dict())).to_dict()==value.to_dict()


def test_absolute_paths_and_home_expansion_override_each_base(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path));raw=configuration()
    raw['paths']['data_root']='~/shared data'
    raw['paths']['knowledge_base_root']=str(tmp_path/'中文 材料')
    raw['models_file']=str(tmp_path/'separate/models.json')
    raw['storage']['storage_root']=str(tmp_path/'索引')
    value=load(write(tmp_path/'config.yaml',raw))
    assert value.data_root==str(tmp_path/'shared data')
    assert value.storage.storage_root==str(tmp_path/'索引')
    assert value.sparse.cache_dir==str(tmp_path/'shared data/cache/sparse')
    assert value.knowledge_base_root==str(tmp_path/'中文 材料')
    assert value.models_file==str(tmp_path/'separate/models.json')
    assert not (tmp_path/'索引').exists()


@pytest.mark.parametrize('group,key,bad',[
    (None,'config_version',True),(None,'config_version',2),(None,'models_file',''),
    ('paths','data_root','../outside'),('paths','knowledge_base_root','bad\x00path'),
    ('service','host','0.0.0.0'),('service','port',True),('service','port',0),('service','port',65536),
    ('service','access_token',None),('service','access_token','short'),('service','startup_timeout_seconds',float('nan')),
    ('service','max_request_bytes',False),('ingestion','chunk_overlap',1000),
    ('storage','max_documents',True),('sparse','max_terms_per_input',0),('hybrid','parallel_retrieval','yes'),
    ('encoding','model','bad/model'),('rerank','backend','unknown'),('rerank','model',None),
])
def test_invalid_values_are_rejected_without_payloads(tmp_path,caplog,group,key,bad):
    raw=configuration();(raw if group is None else raw[group])[key]=bad
    with pytest.raises(SettingsError,match='invalid_application_settings'):load(write(tmp_path/'config.yaml',raw))
    assert raw['service']['access_token'] is None or raw['service']['access_token'] not in caplog.text


@pytest.mark.parametrize('fault',['missing','extra','group-extra','encoding-extra','runtime-type','representation-type','none-model'])
def test_exact_schema_and_encoding_limits(tmp_path,fault):
    raw=configuration()
    if fault=='missing':del raw['hybrid']
    elif fault=='extra':raw['agent']={}
    elif fault=='group-extra':raw['paths']['other']='unexpected'
    elif fault=='encoding-extra':raw['encoding']['base_url']='https://synthetic.invalid'
    elif fault=='runtime-type':raw['encoding']['runtime']['max_inputs']=True
    elif fault=='representation-type':raw['encoding']['representation']['query_prefix']=None
    else:raw['rerank']['backend']='none'
    with pytest.raises(SettingsError,match='invalid_application_settings'):load(write(tmp_path/'config.yaml',raw))


def test_disabled_reranker_requires_no_model(tmp_path):
    raw=configuration();raw['rerank'].update(backend='none',model=None)
    value=load(write(tmp_path/'config.yaml',raw))
    assert not value.rerank.settings.enabled and value.rerank.model is None


@pytest.mark.parametrize('payload,code',[
    ('config_version: 1\nconfig_version: 1','invalid_settings_yaml'),
    ('x: &x {}\ny: *x','invalid_settings_yaml'),(' '*65537,'settings_too_large'),
],ids=['duplicate','alias','oversize'])
def test_existing_strict_yaml_boundary_is_preserved(tmp_path,payload,code):
    path=tmp_path/'config.yaml';path.write_text(payload)
    with pytest.raises(SettingsError,match=code):load(path)


def test_explicit_missing_file_never_initializes_home(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path))
    with pytest.raises(SettingsError,match='settings_file_error'):load(tmp_path/'missing.yaml')
    assert not (tmp_path/'.naiyue-rag').exists()


def test_existing_file_cannot_be_a_data_directory(tmp_path):
    raw=configuration();file=tmp_path/'occupied';file.write_text('user data')
    raw['paths']['data_root']=str(file)
    with pytest.raises(SettingsError,match='invalid_application_settings'):load(write(tmp_path/'config.yaml',raw))
    assert file.read_text()=='user data'
