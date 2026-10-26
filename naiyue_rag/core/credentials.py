"""Resolve one explicitly named credential; never search upwards or mutate os.environ."""
from collections.abc import Mapping
from io import StringIO
import logging
import os
from pathlib import Path
import re
import stat
from dotenv.parser import parse_stream
from .errors import SettingsError

LOGGER=logging.getLogger(__name__)
MAX_ENV_BYTES=65536


def _fail(code):
    LOGGER.error('credential_resolution_failed code=%s',code)
    raise SettingsError(code) from None


def _valid_key(value):
    if type(value) is not str or not value or any(ord(c)<33 or ord(c)>126 for c in value):
        _fail('credential_invalid')
    return value


def _read_project_env(root):
    path=root/'.env'
    try:
        before=path.lstat()
        if not stat.S_ISREG(before.st_mode):_fail('credential_file_error')
        flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)
        fd=os.open(path,flags)
        try:handle=os.fdopen(fd,'rb')
        except Exception:
            try:os.close(fd)
            except OSError:LOGGER.error('credential_resolution_failed code=credential_file_close_error')
            _fail('credential_file_error')
        with handle:
            after=os.fstat(handle.fileno())
            if not stat.S_ISREG(after.st_mode) or (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):
                _fail('credential_file_error')
            if after.st_size>MAX_ENV_BYTES:_fail('credential_file_too_large')
            payload=handle.read(MAX_ENV_BYTES+1)
        if len(payload)>MAX_ENV_BYTES:_fail('credential_file_too_large')
    except SettingsError:raise
    except FileNotFoundError:_fail('credential_not_found')
    except Exception:_fail('credential_file_error')
    try:
        values={}
        # parse_stream does no interpolation or logging. Binding.error must be checked explicitly.
        for binding in parse_stream(StringIO(payload.decode('utf-8-sig'))):
            if binding.error:_fail('credential_env_invalid')
            if binding.key is None:continue
            if binding.key in values:_fail('credential_env_invalid')
            values[binding.key]=binding.value
        return values
    except SettingsError:raise
    except Exception:_fail('credential_env_invalid')


def resolve_api_key(project_root,key_env,*,environ=None):
    """Environment presence wins even if invalid; absent values may use exactly root/.env."""
    if type(key_env) is not str or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key_env) is None:
        _fail('credential_invalid_name')
    try:
        root=Path(project_root).resolve(strict=True)
        if not root.is_dir():_fail('credential_file_error')
    except SettingsError:raise
    except Exception:_fail('credential_file_error')
    environment=os.environ if environ is None else environ
    if not isinstance(environment,Mapping):_fail('credential_invalid')
    if key_env in environment:return _valid_key(environment[key_env])
    values=_read_project_env(root)
    if key_env not in values:_fail('credential_not_found')
    return _valid_key(values[key_env])
