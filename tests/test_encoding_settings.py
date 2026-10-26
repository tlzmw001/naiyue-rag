"""Formal encoding configuration without snapshot paths or real credentials."""
import copy
import json
from dataclasses import replace

import pytest
import yaml

from naiyue_rag.core.encoding_settings import EncodingSettings,load_encoding_settings
from naiyue_rag.core.errors import SettingsError
from test_document_chunker import offline


def config_data():
    return {'embedding':{'provider':'openai_compatible','base_url':'https://embedding.example.invalid/v1',
        'model':'synthetic-model','expected_dimensions':3,'request_dimensions':None,
        'model_revision':None,'allowed_response_models':['synthetic-model']},
        'representation':{'document_text_mode':'raw','text_layout':'contexts_then_view',
                          'document_prefix':'passage: ','query_prefix':'query: '},
        'runtime':{'batch_size':2,'max_inputs':100,'max_input_utf8_bytes':4096,
                   'max_batch_input_utf8_bytes':8192,'max_requests':100,
                   'timeout_seconds':10,'deadline_seconds':60,'max_response_bytes':65536}}


def config(**changes):
    raw=config_data()
    for group,values in changes.items():raw[group].update(values)
    return EncodingSettings.from_dict(raw)


def test_standalone_yaml_hashes_and_output_isolation(tmp_path):
    raw=config_data();path=tmp_path/'encoding.yaml';path.write_text(yaml.safe_dump(raw))
    settings=load_encoding_settings(path)
    assert settings.to_dict()==raw and json.loads(json.dumps(settings.to_dict()))==raw
    assert len(settings.model_space_id)==64 and len(settings.representation_id)==64
    assert not hasattr(settings,'snapshot')
    returned=settings.to_dict();returned['embedding']['allowed_response_models'].append('changed')
    raw['embedding']['allowed_response_models'].clear()
    assert settings.embedding.allowed_response_models==('synthetic-model',)
    assert settings.model_space_id==config(runtime={'batch_size':3}).model_space_id
    assert settings.model_space_id!=config(embedding={'model_revision':'revision-2'}).model_space_id
    assert settings.representation_id!=config(representation={'document_text_mode':'labeled_case'}).representation_id


@pytest.mark.parametrize('group,key,value',[
    ('embedding','provider','ollama'),('embedding','expected_dimensions',True),
    ('embedding','request_dimensions',2),('embedding','allowed_response_models',[]),
    ('embedding','base_url','https://secret@example.invalid/v1'),
    ('embedding','base_url','https://example.invalid/v1?key=secret'),
    ('embedding','base_url','https://example.invalid/v1?'),
    ('embedding','base_url','https://example.invalid/v1#'),
    ('embedding','base_url','file:///private'),('embedding','model',''),
    ('representation','document_text_mode','guess'),('representation','text_layout','guess'),
    ('representation','query_prefix','x\x00y'),('runtime','batch_size',0),
    ('runtime','max_inputs',False),('runtime','timeout_seconds',float('nan')),
    ('runtime','deadline_seconds',-1),('runtime','max_response_bytes',0),
    ('runtime','timeout_seconds',10**1000),
])
def test_bad_config_rejected_without_payload(group,key,value,caplog):
    raw=config_data();raw[group][key]=value
    with pytest.raises(SettingsError,match='^invalid_encoding_settings$'):
        EncodingSettings.from_dict(raw)
    assert 'secret' not in caplog.text


@pytest.mark.parametrize('text',[
    'embedding: {}\nembedding: {}', 'x: &a [1]\ny: *a',
    'x: &a {k: 1}\ny: {<<: *a}', '!!python/object:secret {}',
    'true: value',
])
def test_unsafe_yaml_rejected(tmp_path,text):
    path=tmp_path/'encoding.yaml';path.write_text(text)
    with pytest.raises(SettingsError,match='^invalid_settings_yaml$'):load_encoding_settings(path)


def test_missing_extra_key_and_read_failure(tmp_path,caplog):
    for mutate in [lambda d:d.pop('runtime'),lambda d:d.update(snapshot={}),
                   lambda d:d['embedding'].update(api_key='SYNTHETIC_PRIVATE')]:
        raw=config_data();mutate(raw)
        with pytest.raises(SettingsError,match='^invalid_encoding_settings$'):EncodingSettings.from_dict(raw)
    with pytest.raises(SettingsError,match='^settings_file_error$'):load_encoding_settings(tmp_path/'SYNTHETIC_PRIVATE')
    assert 'SYNTHETIC_PRIVATE' not in caplog.text
