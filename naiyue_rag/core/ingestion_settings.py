"""The two real chunking parameters, independent of any snapshot."""
from dataclasses import dataclass
from .errors import SettingsError


@dataclass(frozen=True,repr=False)
class IngestionSettings:
    chunk_size:int
    chunk_overlap:int


def validate_ingestion_settings(value):
    if type(value) is not IngestionSettings or type(value.chunk_size) is not int or value.chunk_size<=0 or \
            type(value.chunk_overlap) is not int or not 0<=value.chunk_overlap<value.chunk_size:
        raise SettingsError('invalid_ingestion_settings')
