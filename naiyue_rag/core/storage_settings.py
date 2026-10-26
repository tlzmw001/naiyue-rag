"""Explicit local artifact boundaries; loading settings never creates directories."""
from dataclasses import dataclass,asdict
import logging
from pathlib import Path
from .errors import SettingsError
from .yaml_config import read_yaml_mapping

LOGGER=logging.getLogger(__name__)


def _invalid():
    LOGGER.error('storage_settings_failed code=invalid_storage_settings')
    raise SettingsError('invalid_storage_settings') from None


@dataclass(frozen=True,repr=False)
class StorageSettings:
    storage_root:str
    knowledge_base_id:str
    max_documents:int
    max_chunks:int
    max_file_bytes:int
    max_bundle_bytes:int
    max_manifest_bytes:int

    def __post_init__(self):validate_storage_settings(self)

    def to_dict(self):
        validate_storage_settings(self)
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):_invalid()
        return cls(**dict(data))


def validate_storage_settings(settings):
    if type(settings) is not StorageSettings:_invalid()
    try:
        for value in [settings.storage_root,settings.knowledge_base_id]:
            if type(value) is not str or not value.strip() or any(ord(c)<32 for c in value):_invalid()
            value.encode('utf-8')
        path=Path(settings.storage_root)
        if not path.is_absolute() or '..' in path.parts or path==Path(path.anchor):_invalid()
        for part in [path,*path.parents]:
            if part.is_symlink() or part.exists() and not part.is_dir():_invalid()
        for value in [settings.max_documents,settings.max_chunks,settings.max_file_bytes,
                      settings.max_bundle_bytes,settings.max_manifest_bytes]:
            if type(value) is not int or value<=0:_invalid()
        if max(settings.max_file_bytes,settings.max_manifest_bytes)>settings.max_bundle_bytes:_invalid()
    except SettingsError:raise
    except Exception:_invalid()


def load_storage_settings(path):
    try:source,data=read_yaml_mapping(path)
    except SettingsError as error:
        LOGGER.error('storage_settings_failed code=%s',error.code)
        raise
    if type(data) is not dict or type(data.get('storage_root')) is not str:_invalid()
    raw=dict(data);value=Path(raw['storage_root'])
    if not value.is_absolute():value=source.parent/value
    raw['storage_root']=str(value)
    return StorageSettings.from_dict(raw)
