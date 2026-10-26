"""Explicit application settings; native SDK dotenv fields remain SDK-owned."""
from dataclasses import dataclass,asdict
import ipaddress
import logging
import re
from .errors import SettingsError
from .yaml_config import read_yaml_mapping


def _invalid():
    logging.getLogger(__name__).error('chroma_settings_failed code=invalid_chroma_settings')
    raise SettingsError('invalid_chroma_settings') from None


@dataclass(frozen=True)
class ChromaSettings:
    collection_name:str
    batch_size:int

    def __post_init__(self):
        name=self.collection_name
        if type(name) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{1,61}[A-Za-z0-9]',name) is None:_invalid()
        try:ipaddress.ip_address(name)
        except ValueError:pass
        else:_invalid()
        if type(self.batch_size) is not int or self.batch_size<=0:_invalid()

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):_invalid()
        return cls(**data)


def load_chroma_settings(path):
    try:_,data=read_yaml_mapping(path)
    except SettingsError as error:
        logging.getLogger(__name__).error('chroma_settings_failed code=%s',error.code)
        raise
    return ChromaSettings.from_dict(data)
