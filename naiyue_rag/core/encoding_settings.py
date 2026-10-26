"""Standalone encoding settings; no snapshot paths, implicit secrets or network."""
from dataclasses import dataclass,asdict
import hashlib
import json
import logging
import math
from urllib.parse import urlsplit
from .errors import SettingsError
from .yaml_config import read_yaml_mapping

LOGGER=logging.getLogger(__name__)


def _invalid():
    LOGGER.error('encoding_settings_failed stage=encoding_config code=invalid_encoding_settings')
    raise SettingsError('invalid_encoding_settings') from None


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),
                                   allow_nan=False).encode()).hexdigest()


def _text(value,empty=False):
    if type(value) is not str or '\x00' in value or (not empty and not value.strip()):_invalid()
    try:value.encode('utf-8')
    except UnicodeError:_invalid()


@dataclass(frozen=True,repr=False)
class EmbeddingSettings:
    provider:str
    base_url:str
    model:str
    expected_dimensions:int
    request_dimensions:int|None
    model_revision:str|None
    allowed_response_models:tuple


@dataclass(frozen=True,repr=False)
class RepresentationSettings:
    document_text_mode:str
    text_layout:str
    document_prefix:str
    query_prefix:str


@dataclass(frozen=True,repr=False)
class EncodingRuntimeSettings:
    batch_size:int
    max_inputs:int
    max_input_utf8_bytes:int
    max_batch_input_utf8_bytes:int
    max_requests:int
    timeout_seconds:float
    deadline_seconds:float
    max_response_bytes:int


@dataclass(frozen=True,repr=False)
class EncodingSettings:
    embedding:EmbeddingSettings
    representation:RepresentationSettings
    runtime:EncodingRuntimeSettings

    def __post_init__(self):validate_encoding_settings(self)

    @classmethod
    def from_dict(cls,data):
        try:
            groups={'embedding':EmbeddingSettings,'representation':RepresentationSettings,'runtime':EncodingRuntimeSettings}
            if type(data) is not dict or set(data)!=set(groups):_invalid()
            values={}
            for name,kind in groups.items():
                raw=data[name]
                if type(raw) is not dict or set(raw)!=set(kind.__dataclass_fields__):_invalid()
                raw=dict(raw)
                if name=='embedding':
                    aliases=raw['allowed_response_models']
                    if type(aliases) is not list:_invalid()
                    raw['allowed_response_models']=tuple(aliases)
                values[name]=kind(**raw)
            return cls(**values)
        except SettingsError:raise
        except (KeyError,ValueError,TypeError,UnicodeError):_invalid()

    def to_dict(self):
        validate_encoding_settings(self)
        result=asdict(self);result['embedding']['allowed_response_models']=list(self.embedding.allowed_response_models)
        return result

    @property
    def model_space_id(self):
        validate_encoding_settings(self)
        return digest({'policy':'embedding-space-v1','embedding':self.to_dict()['embedding']})

    @property
    def representation_id(self):
        validate_encoding_settings(self)
        return digest({'policy':'encoding-representation-v1','representation':asdict(self.representation)})


def validate_encoding_settings(settings):
    if type(settings) is not EncodingSettings:_invalid()
    e,r,t=settings.embedding,settings.representation,settings.runtime
    if type(e) is not EmbeddingSettings or type(r) is not RepresentationSettings or type(t) is not EncodingRuntimeSettings:_invalid()
    for value in [e.provider,e.base_url,e.model]:_text(value)
    if e.provider!='openai_compatible':_invalid()
    try:
        u=urlsplit(e.base_url);u.port
        if u.scheme not in ('http','https') or not u.hostname or u.username is not None or \
                u.password is not None or '?' in e.base_url or '#' in e.base_url or any(ord(c)<=32 for c in e.base_url):_invalid()
    except ValueError:_invalid()
    if type(e.expected_dimensions) is not int or e.expected_dimensions<=0:_invalid()
    if e.request_dimensions is not None and (type(e.request_dimensions) is not int or e.request_dimensions!=e.expected_dimensions):_invalid()
    if e.model_revision is not None:_text(e.model_revision)
    if type(e.allowed_response_models) is not tuple or not e.allowed_response_models:_invalid()
    for value in e.allowed_response_models:_text(value)
    if len(set(e.allowed_response_models))!=len(e.allowed_response_models):_invalid()
    if r.document_text_mode not in ('raw','labeled_case') or r.text_layout not in ('view_only','contexts_then_view'):_invalid()
    _text(r.document_prefix,True);_text(r.query_prefix,True)
    for name in ['batch_size','max_inputs','max_input_utf8_bytes','max_batch_input_utf8_bytes','max_requests','max_response_bytes']:
        value=getattr(t,name)
        if type(value) is not int or value<=0:_invalid()
    for value in [t.timeout_seconds,t.deadline_seconds]:
        try:
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:_invalid()
        except OverflowError:_invalid()


def load_encoding_settings(path):
    try:
        _,data=read_yaml_mapping(path)
        return EncodingSettings.from_dict(data)
    except SettingsError as error:
        LOGGER.error('encoding_settings_failed stage=encoding_config code=%s',error.code)
        raise
