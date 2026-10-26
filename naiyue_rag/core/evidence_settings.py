"""Separate limits for readable context and the entire structured response."""
from dataclasses import dataclass,asdict
from .errors import SettingsError
from .yaml_config import read_yaml_mapping


@dataclass(frozen=True)
class EvidenceSettings:
    max_context_characters:int
    max_response_bytes:int

    def __post_init__(self):
        if any(type(v) is not int or v<=0 for v in (self.max_context_characters,self.max_response_bytes)):
            raise SettingsError('invalid_evidence_settings')

    def to_dict(self):
        self.__post_init__();return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise SettingsError('invalid_evidence_settings')
        return cls(**data)


def load_evidence_settings(path):
    _,data=read_yaml_mapping(path)
    return EvidenceSettings.from_dict(data)
