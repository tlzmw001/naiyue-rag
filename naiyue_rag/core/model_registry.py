"""Explicit model definitions; credentials are resolved only for selected use."""
from collections.abc import Mapping
import copy
import json
import hashlib
import logging
import os
from pathlib import Path
import re
import stat
from .application_settings import ApplicationSettings,_model
from .application_paths import resolve_application_path
from .encoding_settings import EncodingSettings,EmbeddingSettings
from .rerank_settings import LLMRerankSettings
from .cross_encoder_settings import CrossEncoderSettings
from .credentials import _valid_key
from .errors import SettingsError
from .yaml_config import MAX_SETTINGS_BYTES

LOGGER=logging.getLogger(__name__)


def _fail(code):
    LOGGER.error('model_configuration_failed code=%s',code)
    raise SettingsError(code) from None


def _unique(pairs):
    raw={}
    for key,value in pairs:
        if key in raw:raise ValueError()
        raw[key]=value
    return raw


def _constant(value):raise ValueError()


def _read(path):
    fd=None
    try:
        path=Path(path)
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError()
        before=path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_SETTINGS_BYTES:raise ValueError()
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        after=os.fstat(fd)
        if not stat.S_ISREG(after.st_mode) or (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):raise ValueError()
        with os.fdopen(fd,'rb') as stream:
            fd=None;payload=stream.read(MAX_SETTINGS_BYTES+1)
        if len(payload)>MAX_SETTINGS_BYTES:raise ValueError()
        return payload
    except Exception:_fail('models_file_error')
    finally:
        if fd is not None:
            try:os.close(fd)
            except OSError:LOGGER.error('model_configuration_failed code=models_file_close_failed')


class ModelRegistry:
    def __init__(self,settings,raw):
        try:
            if type(settings) is not ApplicationSettings or type(raw) is not dict or set(raw)!={'config_version','models'}:raise ValueError()
            if type(raw['config_version']) is not int or raw['config_version']!=1 or type(raw['models']) is not dict:raise ValueError()
            self.settings=settings;self._models=copy.deepcopy(raw['models']);self._typed={}
            self.identity=hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()
            for uid,entry in self._models.items():
                _model(uid)
                if type(entry) is not dict:raise ValueError()
                kind=entry.get('kind');body=dict(entry);body.pop('kind',None)
                if kind in ('embedding','chat'):
                    credentials=set(body)&{'api_key','api_key_env'}
                    if len(credentials)!=1:raise ValueError()
                    key=credentials.pop();value=body.pop(key)
                    if key=='api_key':_valid_key(value)
                    elif type(value) is not str or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value) is None:raise ValueError()
                if kind=='embedding':
                    if set(body)!=set(EmbeddingSettings.__dataclass_fields__):raise ValueError()
                    typed=EncodingSettings.from_dict(dict(embedding=body,
                        representation=settings.encoding.to_dict()['representation'],runtime=settings.encoding.to_dict()['runtime']))
                elif kind=='chat':
                    if body.pop('provider',None)!='openai_compatible':raise ValueError()
                    typed=LLMRerankSettings.from_dict(body)
                elif kind=='cross_encoder':
                    body['model_path']=resolve_application_path(body.get('model_path'),settings.data_root)
                    typed=CrossEncoderSettings.from_dict(body)
                else:raise ValueError()
                self._typed[uid]=typed
        except Exception:_fail('invalid_models_settings')

    def _pick(self,model_id,kind):
        if type(model_id) is not str or model_id not in self._models or self._models[model_id]['kind']!=kind:
            _fail('model_selection_invalid')
        return self._typed[model_id]

    def encoding_settings(self,model_id=None):
        value=self._pick(self.settings.encoding.model if model_id is None else model_id,'embedding')
        return EncodingSettings.from_dict(value.to_dict())

    def llm_settings(self,model_id):
        return LLMRerankSettings.from_dict(self._pick(model_id,'chat').to_dict())

    def local_settings(self,model_id):
        return CrossEncoderSettings.from_dict(self._pick(model_id,'cross_encoder').to_dict())

    def resolve_key(self,model_id,*,environ=None):
        if type(model_id) is not str or model_id not in self._models:_fail('model_selection_invalid')
        entry=self._models[model_id]
        if entry['kind'] not in ('embedding','chat'):_fail('model_selection_invalid')
        try:
            if 'api_key' in entry:return _valid_key(entry['api_key'])
            environment=os.environ if environ is None else environ
            if not isinstance(environment,Mapping) or entry['api_key_env'] not in environment:raise ValueError()
            return _valid_key(environment[entry['api_key_env']])
        except Exception:_fail('model_credential_invalid')


def load_model_registry(settings):
    if type(settings) is not ApplicationSettings:_fail('invalid_models_settings')
    payload=_read(settings.models_file)
    try:raw=json.loads(payload.decode('utf-8'),object_pairs_hook=_unique,parse_constant=_constant)
    except Exception:_fail('invalid_models_settings')
    return ModelRegistry(settings,raw)
