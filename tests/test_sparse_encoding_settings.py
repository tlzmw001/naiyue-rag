"""Independent sparse configuration; no snapshot, key or model IO."""
import json
from pathlib import Path
import pytest
import yaml
from naiyue_rag.core.sparse_encoding_settings import SparseEncodingSettings,load_sparse_encoding_settings
from naiyue_rag.core.errors import SettingsError
from test_document_chunker import offline

def sparse_config(tmp_path,**changes):
    data={'min_chinese_term_length':2,'lowercase':True,'cache_dir':str(tmp_path/'token-cache'),
          'max_terms_per_input':10000,'max_resource_bytes':32*1024*1024}
    data.update(changes)
    return SparseEncodingSettings.from_dict(data)

def test_independent_yaml_relative_path_and_roundtrip(tmp_path):
    raw=sparse_config(tmp_path).to_dict();raw['cache_dir']='./cache'
    path=tmp_path/'sparse.yaml';path.write_text(yaml.safe_dump(raw))
    settings=load_sparse_encoding_settings(path)
    assert settings.cache_dir==str(tmp_path/'cache') and not Path(settings.cache_dir).exists()
    assert SparseEncodingSettings.from_dict(json.loads(json.dumps(settings.to_dict())))==settings
    assert not hasattr(settings,'snapshot')

@pytest.mark.parametrize('key,value',[
    ('min_chinese_term_length',0),('min_chinese_term_length',True),('min_chinese_term_length',2.),
    ('lowercase',1),('cache_dir','relative'),('cache_dir',''),('cache_dir','/tmp/../private'),
    ('cache_dir','https://example.invalid'),('max_terms_per_input',False),
    ('max_resource_bytes',0),('api_key','SYNTHETIC_PRIVATE')])
def test_bad_sparse_settings_fail_safely(tmp_path,key,value,caplog):
    raw=sparse_config(tmp_path).to_dict();raw[key]=value
    with pytest.raises(SettingsError,match='^invalid_sparse_encoding_settings$'):SparseEncodingSettings.from_dict(raw)
    assert 'SYNTHETIC_PRIVATE' not in caplog.text

@pytest.mark.parametrize('text',['x: 1\nx: 2','x: &a []\ny: *a','true: value'])
def test_reuses_strict_yaml_errors(tmp_path,text):
    path=tmp_path/'bad.yaml';path.write_text(text)
    with pytest.raises(SettingsError,match='^invalid_settings_yaml$'):load_sparse_encoding_settings(path)

def test_missing_and_extra_fields_and_read_error(tmp_path):
    raw=sparse_config(tmp_path).to_dict();raw.pop('lowercase')
    with pytest.raises(SettingsError):SparseEncodingSettings.from_dict(raw)
    with pytest.raises(SettingsError,match='^settings_file_error$'):load_sparse_encoding_settings(tmp_path/'missing.yaml')
