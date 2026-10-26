"""Parameters actually consumed by both retrievers and the RRF join."""
from dataclasses import dataclass,asdict
import logging
from .errors import SettingsError
from .yaml_config import read_yaml_mapping


def _invalid():
    logging.getLogger(__name__).error('hybrid_settings_failed code=invalid_hybrid_settings')
    raise SettingsError('invalid_hybrid_settings') from None


@dataclass(frozen=True)
class HybridSettings:
    dense_top_k:int
    sparse_top_k:int
    fusion_top_k:int
    rrf_k:int
    bm25_statistics_scope:str
    parallel_retrieval:bool

    def __post_init__(self):
        if any(type(v) is not int or v<=0 for v in (self.dense_top_k,self.sparse_top_k,self.fusion_top_k,self.rrf_k)) or \
                type(self.bm25_statistics_scope) is not str or self.bm25_statistics_scope not in ('global','scope') or \
                type(self.parallel_retrieval) is not bool:_invalid()

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):_invalid()
        return cls(**data)


def load_hybrid_settings(path):
    try:_,data=read_yaml_mapping(path)
    except SettingsError as error:
        logging.getLogger(__name__).error('hybrid_settings_failed code=%s',error.code);raise
    return HybridSettings.from_dict(data)
