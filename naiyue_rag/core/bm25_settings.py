"""Small explicit parameter surface for the selected Lucene BM25S policy."""
from dataclasses import dataclass,asdict
import logging
import math
from .errors import SettingsError
from .yaml_config import read_yaml_mapping


def _invalid():
    logging.getLogger(__name__).error('bm25_settings_failed code=invalid_bm25_settings')
    raise SettingsError('invalid_bm25_settings') from None


@dataclass(frozen=True)
class BM25Settings:
    k1:float
    b:float

    def __post_init__(self):
        for value in [self.k1,self.b]:
            if type(value) not in (int,float):_invalid()
            try:
                if not math.isfinite(value):_invalid()
            except (OverflowError,ValueError):_invalid()
        if self.k1<=0 or not 0<=self.b<=1:_invalid()
        object.__setattr__(self,'k1',float(self.k1));object.__setattr__(self,'b',float(self.b))

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):_invalid()
        return cls(**data)


def load_bm25_settings(path):
    try:_,data=read_yaml_mapping(path)
    except SettingsError as error:
        logging.getLogger(__name__).error('bm25_settings_failed code=%s',error.code)
        raise
    return BM25Settings.from_dict(data)
