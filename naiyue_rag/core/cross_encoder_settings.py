"""Pinned local model identity and pair/token/resource budgets."""
from dataclasses import dataclass,asdict
from pathlib import Path
import re
from .errors import SettingsError
from .yaml_config import read_yaml_mapping


@dataclass(frozen=True,repr=False)
class CrossEncoderSettings:
    model_id:str
    model_revision:str
    model_path:str
    device:str
    batch_size:int
    max_pair_tokens:int
    max_model_bytes:int

    def __post_init__(self):
        try:
            if type(self.model_id) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',self.model_id):raise ValueError()
            if type(self.model_revision) is not str or not re.fullmatch('[0-9a-f]{40}',self.model_revision):raise ValueError()
            if type(self.model_path) is not str or not Path(self.model_path).is_absolute() or '..' in Path(self.model_path).parts or \
                    any(ord(c)<32 for c in self.model_path):raise ValueError()
            if type(self.device) is not str or self.device not in ('cpu','cuda','mps'):raise ValueError()
            for v in (self.batch_size,self.max_pair_tokens,self.max_model_bytes):
                if type(v) is not int or v<=0:raise ValueError()
        except Exception:raise SettingsError('invalid_cross_encoder_settings') from None

    def to_dict(self):
        self.__post_init__();return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise SettingsError('invalid_cross_encoder_settings')
        return cls(**data)


def load_cross_encoder_settings(path):
    source,data=read_yaml_mapping(path)
    if type(data) is not dict or type(data.get('model_path')) is not str:raise SettingsError('invalid_cross_encoder_settings')
    raw=dict(data);value=Path(raw['model_path'])
    raw['model_path']=str(value if value.is_absolute() else source.parent/value)
    return CrossEncoderSettings.from_dict(raw)
