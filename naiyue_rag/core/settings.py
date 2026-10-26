"""Explicit, read-only YAML settings for current snapshot consumers."""
from dataclasses import dataclass, replace
import logging
import math
from pathlib import Path


from .errors import SettingsError

LOGGER = logging.getLogger(__name__)
from .yaml_config import read_yaml_mapping
from .ingestion_settings import IngestionSettings
GROUPS = {
    'snapshot': {'dataset', 'corpus_run', 'vector_run'},
    'embedding': {'endpoint', 'model', 'dimensions'},
    'retrieval': {'rrf_k'},
    'sparse': {'bm25_k1', 'bm25_b', 'bm25_method', 'backend', 'tokenizer_policy'},
    'runtime': {'tokenizer_cache_dir'},
}


def _invalid():
    raise SettingsError('invalid_settings') from None


def _string(value):
    if type(value) is not str or not value.strip() or '\x00' in value:
        _invalid()
    try:
        value.encode('utf-8')
    except UnicodeError:
        _invalid()


@dataclass(frozen=True, repr=False)
class SnapshotSettings:
    dataset: str
    corpus_run: str
    vector_run: str


@dataclass(frozen=True, repr=False)
class EmbeddingSettings:
    endpoint: str
    model: str
    dimensions: int


@dataclass(frozen=True, repr=False)
class RetrievalSettings:
    rrf_k: int


@dataclass(frozen=True, repr=False)
class SparseSettings:
    bm25_k1: float
    bm25_b: float
    bm25_method: str
    backend: str
    tokenizer_policy: str


@dataclass(frozen=True, repr=False)
class RuntimeSettings:
    tokenizer_cache_dir: str


@dataclass(frozen=True, repr=False)
class Settings:
    snapshot: SnapshotSettings
    embedding: EmbeddingSettings
    retrieval: RetrievalSettings
    sparse: SparseSettings
    runtime: RuntimeSettings
    ingestion: IngestionSettings | None = None

    @classmethod
    def from_dict(cls, data):
        if type(data) is not dict or not set(GROUPS) <= set(data) or set(data) - set(GROUPS) - {'ingestion'}:
            _invalid()
        for group, fields in GROUPS.items():
            if type(data[group]) is not dict or set(data[group]) != fields:
                _invalid()
        ingestion = None
        if 'ingestion' in data:
            group = data['ingestion']
            if type(group) is not dict or set(group) != {'chunk_size','chunk_overlap'}: _invalid()
            ingestion = IngestionSettings(**group)
        value = cls(SnapshotSettings(**data['snapshot']), EmbeddingSettings(**data['embedding']),
                    RetrievalSettings(**data['retrieval']), SparseSettings(**data['sparse']),
                    RuntimeSettings(**data['runtime']), ingestion)
        validate_settings(value)
        return value

    def to_snapshot_config(self):
        validate_settings(self)
        result = {}
        for name in ['snapshot', 'embedding', 'retrieval', 'sparse']:
            group = getattr(self, name)
            result.update({key: getattr(group, key) for key in GROUPS[name]})
        return result


def validate_settings(settings):
    if type(settings) is not Settings:
        _invalid()
    if settings.ingestion is not None:
        group=settings.ingestion
        if type(group) is not IngestionSettings or type(group.chunk_size) is not int or group.chunk_size <= 0 or \
                type(group.chunk_overlap) is not int or not 0 <= group.chunk_overlap < group.chunk_size:
            _invalid()
    for name, cls in [('snapshot', SnapshotSettings), ('embedding', EmbeddingSettings),
                      ('retrieval', RetrievalSettings), ('sparse', SparseSettings),
                      ('runtime', RuntimeSettings)]:
        if type(getattr(settings, name)) is not cls:
            _invalid()
    for group, keys in [('snapshot', ['dataset', 'corpus_run', 'vector_run']),
                        ('embedding', ['endpoint', 'model']),
                        ('runtime', ['tokenizer_cache_dir'])]:
        for key in keys:
            _string(getattr(getattr(settings, group), key))
    if type(settings.embedding.dimensions) is not int or settings.embedding.dimensions <= 0:
        _invalid()
    if type(settings.retrieval.rrf_k) is not int or settings.retrieval.rrf_k != 60:
        _invalid()
    for key, expected in [('bm25_k1', 1.5), ('bm25_b', .75)]:
        value = getattr(settings.sparse, key)
        if type(value) not in (int, float) or value != expected or not math.isfinite(value):
            _invalid()
    for key, expected in [('bm25_method', 'lucene'), ('backend', 'numpy'),
                          ('tokenizer_policy', 'zh-search-ascii-ident-v1')]:
        value = getattr(settings.sparse, key)
        if type(value) is not str or value != expected:
            _invalid()


def _resolve(base, value):
    path = Path(value)
    return str((path if path.is_absolute() else base / path).resolve())


def load_settings(path):
    """Read explicit local configuration; resource paths follow its directory."""
    try:
        source, data = read_yaml_mapping(path)
        value = Settings.from_dict(data)
        try:
            snapshot = replace(value.snapshot, **{key: _resolve(source.parent, getattr(value.snapshot, key))
                                                  for key in GROUPS['snapshot']})
            runtime = replace(value.runtime,
                              tokenizer_cache_dir=_resolve(source.parent, value.runtime.tokenizer_cache_dir))
        except (OSError, ValueError, UnicodeError, RuntimeError):
            raise SettingsError('invalid_settings') from None
        return replace(value, snapshot=snapshot, runtime=runtime)
    except SettingsError as error:
        LOGGER.error('settings_failed stage=settings code=%s', error.code)
        raise
