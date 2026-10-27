"""Chunking parameters with separate runtime defaults and saved-policy decoding."""
from dataclasses import dataclass,field
from .errors import SettingsError
from .chunking_policy import DEFAULT_CHUNKING_POLICY,LEGACY_CHUNKING_POLICY,chunking_parameters


@dataclass(frozen=True,repr=False)
class IngestionSettings:
    chunk_size:int
    chunk_overlap:int
    chunking_policy:str|None=field(default=None,kw_only=True)

    def __post_init__(self):
        if self.chunking_policy is None:
            object.__setattr__(self,'chunking_policy',DEFAULT_CHUNKING_POLICY)

    def to_dict(self):
        validate_ingestion_settings(self)
        data=dict(chunk_size=self.chunk_size,chunk_overlap=self.chunk_overlap)
        if self.chunking_policy!=LEGACY_CHUNKING_POLICY:data['chunking_policy']=self.chunking_policy
        return data

    @classmethod
    def from_dict(cls,data):
        fields={'chunk_size','chunk_overlap'}
        if type(data) is not dict or set(data) not in (fields,fields|{'chunking_policy'}):
            raise SettingsError('invalid_ingestion_settings')
        policy=data.get('chunking_policy',LEGACY_CHUNKING_POLICY)
        chunking_parameters(policy)
        result=cls(data['chunk_size'],data['chunk_overlap'],chunking_policy=policy)
        validate_ingestion_settings(result)
        return result


def validate_ingestion_settings(value):
    if type(value) is not IngestionSettings or type(value.chunk_size) is not int or value.chunk_size<=0 or \
            type(value.chunk_overlap) is not int or not 0<=value.chunk_overlap<value.chunk_size:
        raise SettingsError('invalid_ingestion_settings')
    chunking_parameters(value.chunking_policy)
