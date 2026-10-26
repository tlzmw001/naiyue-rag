"""Strict local configuration contracts; only temporary synthetic YAML files."""
import copy
from dataclasses import FrozenInstanceError, replace
import logging
from pathlib import Path
import socket
import traceback

import pytest
import yaml

from naiyue_rag.core.settings import Settings, load_settings, validate_settings
from naiyue_rag.core.errors import SettingsError
from test_a2_snapshot import settings as legacy_settings


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)


def configuration(tmp_path):
    old = legacy_settings(tmp_path)
    return {
        'snapshot': {k: old[k] for k in ['dataset', 'corpus_run', 'vector_run']},
        'embedding': {k: old[k] for k in ['endpoint', 'model', 'dimensions']},
        'retrieval': {'rrf_k': old['rrf_k']},
        'sparse': {k: old[k] for k in
                   ['bm25_k1', 'bm25_b', 'bm25_method', 'backend', 'tokenizer_policy']},
        'runtime': {'tokenizer_cache_dir': str(tmp_path / 'tokenizer')},
    }


def write_settings(tmp_path, data=None):
    path = tmp_path / 'settings.yaml'
    path.write_text(yaml.safe_dump(configuration(tmp_path) if data is None else data), encoding='utf-8')
    return path


def test_groups_bridge_and_frozen_values(tmp_path):
    raw = configuration(tmp_path)
    value = Settings.from_dict(raw)
    assert value.to_snapshot_config() == legacy_settings(tmp_path)
    assert value.runtime.tokenizer_cache_dir == str(tmp_path / 'tokenizer')
    raw['embedding']['model'] = 'changed'
    exposed = value.to_snapshot_config()
    exposed['model'] = 'changed'
    assert value.embedding.model == 'embedding-3'
    with pytest.raises(FrozenInstanceError):
        value.embedding.model = 'changed'
    validate_settings(value)


def test_relative_resource_paths_follow_config_directory_not_cwd(tmp_path, monkeypatch):
    raw = configuration(tmp_path)
    raw['snapshot'] = {'dataset': '../materials', 'corpus_run': 'corpus', 'vector_run': 'vectors'}
    raw['runtime']['tokenizer_cache_dir'] = 'cache'
    folder = tmp_path / 'config'; folder.mkdir()
    path = folder / 'local.yaml'
    path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    other = tmp_path / 'other'; other.mkdir()
    monkeypatch.chdir(other)
    value = load_settings(path)
    assert value.snapshot.dataset == str(tmp_path / 'materials')
    assert value.snapshot.corpus_run == str(folder / 'corpus')
    assert value.snapshot.vector_run == str(folder / 'vectors')
    assert value.runtime.tokenizer_cache_dir == str(folder / 'cache')
    assert load_settings('../config/local.yaml') == value
    assert not (folder / 'cache').exists()


@pytest.mark.parametrize('group,key,value', [
    ('embedding','dimensions',True), ('embedding','dimensions',0),
    ('embedding','dimensions','2048'), ('embedding','model',''),
    ('embedding','model','\ud800'), ('embedding','model','a\x00b'),
    ('snapshot','dataset',None), ('runtime','tokenizer_cache_dir',[]),
    ('retrieval','rrf_k',True), ('retrieval','rrf_k',61),
    ('sparse','bm25_k1',True), ('sparse','bm25_k1',float('nan')),
    ('sparse','bm25_b',float('inf')), ('sparse','bm25_b',.5),
    ('sparse','bm25_method','robertson'), ('sparse','backend','other'),
    ('sparse','tokenizer_policy','other'),
])
def test_invalid_field_values_fail_explicitly(tmp_path, group, key, value):
    raw = configuration(tmp_path); raw[group][key] = value
    with pytest.raises(SettingsError, match='^invalid_settings$'):
        Settings.from_dict(raw)


@pytest.mark.parametrize('mutation', ['missing_group','extra_group','missing_field','extra_field','bad_group'])
def test_exact_field_sets_required(tmp_path, mutation):
    raw = configuration(tmp_path)
    if mutation == 'missing_group': del raw['runtime']
    elif mutation == 'extra_group': raw['auth'] = {}
    elif mutation == 'missing_field': del raw['embedding']['model']
    elif mutation == 'extra_field': raw['embedding']['api_key'] = 'synthetic-secret'
    else: raw['embedding'] = []
    with pytest.raises(SettingsError, match='^invalid_settings$'):
        Settings.from_dict(raw)


@pytest.mark.parametrize('root', [None, [], 'text', 1])
def test_invalid_root(root):
    with pytest.raises(SettingsError, match='^invalid_settings$'):
        Settings.from_dict(root)


def test_validation_checks_directly_constructed_or_replaced_objects(tmp_path):
    value = Settings.from_dict(configuration(tmp_path))
    invalid = replace(value, embedding=replace(value.embedding, dimensions=True))
    with pytest.raises(SettingsError, match='^invalid_settings$'): validate_settings(invalid)
    with pytest.raises(SettingsError, match='^invalid_settings$'): invalid.to_snapshot_config()
    with pytest.raises(SettingsError, match='^invalid_settings$'): validate_settings({})
    with pytest.raises(SettingsError, match='^invalid_settings$'):
        validate_settings(replace(value, snapshot={}))


@pytest.mark.parametrize('payload,code', [
    ('', 'invalid_settings'), ('[]', 'invalid_settings'),
    ('snapshot: [', 'invalid_settings_yaml'),
    ('snapshot: {}\nsnapshot: {}', 'invalid_settings_yaml'),
    ('embedding:\n  model: a\n  model: b', 'invalid_settings_yaml'),
    ('x: &x [*x]', 'invalid_settings_yaml'),
    ('x: &x {}\ny: *x', 'invalid_settings_yaml'),
    ('x: {<<: {model: a}}', 'invalid_settings_yaml'),
    ('!!python/object/apply:os.system ["echo unsafe"]', 'invalid_settings_yaml'),
    ('true: value', 'invalid_settings_yaml'),
])
def test_yaml_structural_failures(tmp_path, payload, code):
    path = tmp_path / 'invalid.yaml'; path.write_text(payload)
    with pytest.raises(SettingsError, match=f'^{code}$'):
        load_settings(path)


@pytest.mark.parametrize('mode,code', [
    ('missing','settings_file_error'), ('directory','settings_file_error'),
    ('encoding','invalid_settings_yaml'), ('oversize','settings_too_large'),
])
def test_file_failures(tmp_path, mode, code):
    path = tmp_path / 'config.yaml'
    if mode == 'directory': path.mkdir()
    elif mode == 'encoding': path.write_bytes(b'\xff')
    elif mode == 'oversize': path.write_bytes(b' ' * 65537)
    with pytest.raises(SettingsError, match=f'^{code}$'): load_settings(path)


def test_read_permission_failure_is_observable(tmp_path, monkeypatch, caplog):
    path = write_settings(tmp_path)
    def deny(*args, **kwargs): raise PermissionError('synthetic-sensitive-path')
    monkeypatch.setattr(Path, 'open', deny)
    with caplog.at_level(logging.ERROR), pytest.raises(SettingsError, match='^settings_file_error$'):
        load_settings(path)
    assert 'stage=settings code=settings_file_error' in caplog.text
    assert 'synthetic-sensitive-path' not in caplog.text


def test_errors_logs_and_representations_do_not_expose_values(tmp_path, caplog):
    sentinel = 'SYNTHETIC_SETTINGS_SECRET'
    raw = configuration(tmp_path); raw['embedding']['model'] = sentinel
    value = Settings.from_dict(raw)
    assert sentinel not in repr(value) + repr(value.embedding)
    for payload in [yaml.safe_dump(raw | {'extra': sentinel}), f'snapshot: ["{sentinel}"']:
        path = tmp_path / f'{sentinel}.yaml'; path.write_text(payload)
        with caplog.at_level(logging.ERROR):
            try: load_settings(path)
            except SettingsError as error:
                assert sentinel not in ''.join(traceback.format_exception(error))
                assert error.__suppress_context__
            else: pytest.fail('invalid configuration accepted')
        assert sentinel not in caplog.text
        assert 'stage=settings code=' in caplog.text


def test_loading_is_read_only_without_dotenv_or_network(tmp_path, monkeypatch):
    path = write_settings(tmp_path)
    (tmp_path / '.env').write_text('SYNTHETIC_SENTINEL=unused')
    original = Path.open; opened = []
    def observe(self, *args, **kwargs):
        opened.append(self.resolve()); return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', observe)
    load_settings(path)
    assert opened == [path.resolve()]
    assert not (tmp_path / 'tokenizer').exists()


def test_ingestion_optional_group_loaded_without_changing_snapshot_config(tmp_path):
    raw=configuration(tmp_path);raw['ingestion']={'chunk_size':777,'chunk_overlap':123}
    value=load_settings(write_settings(tmp_path,raw))
    assert value.ingestion.chunk_size==777 and value.ingestion.chunk_overlap==123
    assert value.to_snapshot_config()==legacy_settings(tmp_path)
    assert Settings.from_dict(configuration(tmp_path)).ingestion is None


@pytest.mark.parametrize('group', [None,{}, {'chunk_size':100},
    {'chunk_size':True,'chunk_overlap':0},{'chunk_size':0,'chunk_overlap':0},
    {'chunk_size':100,'chunk_overlap':-1},{'chunk_size':100,'chunk_overlap':True},
    {'chunk_size':100,'chunk_overlap':100}, {'chunk_size':'100','chunk_overlap':0},
    {'chunk_size':100,'chunk_overlap':0,'extra':1}])
def test_invalid_ingestion_group_rejected(tmp_path,group):
    raw=configuration(tmp_path);raw['ingestion']=group
    with pytest.raises(SettingsError,match='^invalid_settings$'):Settings.from_dict(raw)
