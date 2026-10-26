"""Standalone sparse policy and explicit resource boundaries."""
from dataclasses import dataclass,asdict
import logging
from pathlib import Path
from .errors import SettingsError
from .yaml_config import read_yaml_mapping

LOGGER=logging.getLogger(__name__)

def _invalid():
    LOGGER.error('sparse_settings_failed code=invalid_sparse_encoding_settings')
    raise SettingsError('invalid_sparse_encoding_settings') from None


@dataclass(frozen=True,repr=False)
class SparseEncodingSettings:
    min_chinese_term_length:int
    lowercase:bool
    cache_dir:str
    max_terms_per_input:int
    max_resource_bytes:int

    def __post_init__(self):validate_sparse_settings(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):_invalid()
        return cls(**dict(data))

    def to_dict(self):
        validate_sparse_settings(self)
        return asdict(self)


def validate_sparse_settings(settings):
    if type(settings) is not SparseEncodingSettings:_invalid()
    for value in [settings.min_chinese_term_length,settings.max_terms_per_input,settings.max_resource_bytes]:
        if type(value) is not int or value<=0:_invalid()
    if type(settings.lowercase) is not bool:_invalid()
    try:
        value=settings.cache_dir
        if type(value) is not str or not value or any(ord(c)<32 for c in value):_invalid()
        value.encode('utf-8');path=Path(value)
        if not path.is_absolute() or '..' in path.parts or path==Path(path.anchor):_invalid()
    except (ValueError,TypeError,UnicodeError):_invalid()


def load_sparse_encoding_settings(path):
    try:
        source,data=read_yaml_mapping(path)
        if type(data) is not dict or type(data.get('cache_dir')) is not str:_invalid()
        raw=dict(data);value=Path(raw['cache_dir'])
        if not value.is_absolute():value=source.parent/value
        raw['cache_dir']=str(value)
        return SparseEncodingSettings.from_dict(raw)
    except SettingsError as error:
        LOGGER.error('sparse_settings_failed code=%s',error.code)
        raise
