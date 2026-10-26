"""Explicit rerank budgets, independent of embedding and retrieval settings."""
from dataclasses import dataclass,asdict
import copy
import logging
import math
from urllib.parse import urlsplit
from .errors import SettingsError
from .yaml_config import read_yaml_mapping


def _invalid():
    logging.getLogger(__name__).error('rerank_settings_failed code=invalid_rerank_settings')
    raise SettingsError('invalid_rerank_settings') from None


def _positive(value):return type(value) is int and value>0


def _seconds(value):
    try:return type(value) in (int,float) and math.isfinite(value) and value>0
    except OverflowError:return False


@dataclass(frozen=True)
class RerankSettings:
    enabled:bool
    top_k:int
    max_candidates:int
    max_input_characters:int

    def __post_init__(self):
        if type(self.enabled) is not bool or not all(_positive(getattr(self,k)) for k in
                ('top_k','max_candidates','max_input_characters')):_invalid()

    def to_dict(self):
        self.__post_init__();return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):_invalid()
        return cls(**data)


@dataclass(frozen=True,repr=False)
class LLMRerankSettings:
    model:str
    base_url:str
    timeout_seconds:float
    deadline_seconds:float
    max_response_bytes:int
    max_output_tokens:int
    temperature:float
    extra_body:dict

    def __post_init__(self):
        try:
            if type(self.model) is not str or not self.model.strip() or any(ord(c)<32 for c in self.model):raise ValueError()
            if type(self.base_url) is not str:raise ValueError()
            url=urlsplit(self.base_url);url.port
            if url.scheme not in ('https','http') or not url.hostname or url.username is not None or url.password is not None or \
                    '?' in self.base_url or '#' in self.base_url or any(ord(c)<=32 for c in self.base_url):raise ValueError()
            if not all(_seconds(getattr(self,k)) for k in ('timeout_seconds','deadline_seconds')) or \
                    not all(_positive(getattr(self,k)) for k in ('max_response_bytes','max_output_tokens')):raise ValueError()
            if type(self.temperature) not in (int,float) or not math.isfinite(self.temperature) or not 0<=self.temperature<=2:raise ValueError()
            if type(self.extra_body) is not dict or set(self.extra_body)-{'thinking'}:raise ValueError()
            if 'thinking' in self.extra_body:
                v=self.extra_body['thinking']
                if type(v) is not dict or set(v)!={'type'} or type(v['type']) is not str or v['type'] not in ('enabled','disabled'):raise ValueError()
            self.model.encode('utf-8');self.base_url.encode('utf-8')
            object.__setattr__(self,'extra_body',copy.deepcopy(self.extra_body))
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__();return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):_invalid()
        return cls(**data)


def load_rerank_settings(path):
    _,data=read_yaml_mapping(path)
    return RerankSettings.from_dict(data)


def load_llm_rerank_settings(path):
    _,data=read_yaml_mapping(path)
    return LLMRerankSettings.from_dict(data)
