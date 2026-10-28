"""Publish complete default templates without replacing user-owned files."""
from importlib.resources import files
import logging
import os
from pathlib import Path
import secrets
import tempfile
import yaml
from .errors import SettingsError

LOGGER=logging.getLogger(__name__)


def _fail():
    LOGGER.error('configuration_initialization_failed code=configuration_initialization_failed')
    raise SettingsError('configuration_initialization_failed') from None


def _regular(path):
    if path.is_symlink() or not path.is_file():_fail()


def _publish(path,payload):
    temporary=None;fd=None
    try:
        fd,name=tempfile.mkstemp(prefix=f'.{path.name}.tmp-',dir=path.parent)
        temporary=Path(name)
        stream=os.fdopen(fd,'wb');fd=None
        with stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,path)
        except FileExistsError:_regular(path)
    except SettingsError:raise
    except Exception:_fail()
    finally:
        failed=False
        if fd is not None:
            try:os.close(fd)
            except OSError:
                LOGGER.error('configuration_cleanup_failed code=configuration_initialization_failed');failed=True
        if temporary is not None:
            try:temporary.unlink()
            except OSError:
                LOGGER.error('configuration_cleanup_failed code=configuration_initialization_failed')
                failed=True
        if failed:raise SettingsError('configuration_initialization_failed') from None


def initialize_default_configuration():
    """Only the absent default config grants permission to publish templates."""
    try:
        folder=Path.home().resolve()/'.naiyue-rag'
        if folder.is_symlink():_fail()
        folder.mkdir(mode=0o700,exist_ok=True)
        if not folder.is_dir():_fail()
        config=folder/'config.yaml'
        if config.exists() or config.is_symlink():
            _regular(config);return config
        registry=folder/'models.json'
        if registry.exists() or registry.is_symlink():_regular(registry)
        resource=files('naiyue_rag.resources')
        _publish(registry,resource.joinpath('models.json').read_bytes())
        raw=yaml.safe_load(resource.joinpath('config.yaml').read_text(encoding='utf-8'))
        raw['service']['access_token']=secrets.token_urlsafe(32)
        _publish(config,yaml.safe_dump(raw,allow_unicode=True,sort_keys=False).encode('utf-8'))
        return config
    except SettingsError:raise
    except Exception:_fail()
