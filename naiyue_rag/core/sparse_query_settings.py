"""Explicit keyword query parameters, independent of index construction settings."""
from dataclasses import dataclass,asdict
import logging
from .errors import SettingsError
from .yaml_config import read_yaml_mapping


def _invalid():
    logging.getLogger(__name__).error('sparse_query_settings_failed code=invalid_sparse_query_settings')
    raise SettingsError('invalid_sparse_query_settings') from None


@dataclass(frozen=True)
class SparseQuerySettings:
    top_k:int
    statistics_scope:str

    def __post_init__(self):
        if type(self.top_k) is not int or self.top_k<=0 or type(self.statistics_scope) is not str or \
                self.statistics_scope not in ('global','scope'):_invalid()

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):_invalid()
        return cls(**data)


def load_sparse_query_settings(path):
    try:_,data=read_yaml_mapping(path)
    except SettingsError as error:
        logging.getLogger(__name__).error('sparse_query_settings_failed code=%s',error.code)
        raise
    return SparseQuerySettings.from_dict(data)
