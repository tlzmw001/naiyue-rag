"""One runtime's validated version resources; active only inside query calls."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
from pathlib import Path
import stat
from threading import RLock

from ..core.errors import StorageError

_CURRENT = ContextVar('nyr_query_resources', default=None)
_PINNED = ContextVar('nyr_pinned_version', default=None)
LOGGER = logging.getLogger(__name__)


def current_query_cache():
    return _CURRENT.get()


def read_query_active(manager):
    pinned = _PINNED.get()
    if pinned is not None and pinned[0] == manager.settings.to_dict():
        return pinned[1]
    return manager.catalog.read()


@contextmanager
def bind_query_resources(cache, manager, active):
    token = _CURRENT.set(cache)
    pin = _PINNED.set((manager.settings.to_dict(), active))
    try:
        yield
    finally:
        _PINNED.reset(pin)
        _CURRENT.reset(token)


def business_stamp(stamp, vector_root):
    native = vector_root / 'chroma'
    return tuple(row for row in stamp if not Path(row[0]).is_relative_to(native))


def cached_query_resource(method):
    @wraps(method)
    def wrapped(owner, identity, *args, **kwargs):
        cache = _CURRENT.get()
        if cache is None or str(identity) not in cache.identities:
            return method(owner, identity, *args, **kwargs)
        config = getattr(owner, 'config', None)
        key = (method.__qualname__, str(identity),
               json.dumps(owner.settings.to_dict(), sort_keys=True),
               None if config is None else json.dumps(config.to_dict(), sort_keys=True),
               tuple(str(a) for a in args) if method.__name__ == '_audit' else ())
        with cache.lock:
            if key not in cache.values:
                cache.values[key] = method(owner, identity, *args, **kwargs)
            return cache.values[key]
    return wrapped


class QueryResourceCache:
    def __init__(self):
        self.lock = RLock()
        self.values = {}
        self.identities = set()
        self.version = None
        self.stamp = None
        self.clients = {}

    def clear(self):
        with self.lock:
            self.values.clear()
            self.identities.clear()
            self.version = None
            self.stamp = None
            clients = dict(self.clients)
            from .chroma_backend import _CLIENT_LOCK
            failed = False
            with _CLIENT_LOCK:
                for key, client in clients.items():
                    try:
                        client.close()
                        del self.clients[key]
                    except Exception:
                        LOGGER.error('query_resources_close_failed code=chroma_close_failed')
                        failed = True
            if failed:
                raise StorageError('chroma_close_failed')

    def native_client(self, path, project_root, factory):
        # Called with the Chroma backend lifecycle lock held.
        key = (str(path), str(project_root))
        if key not in self.clients:
            self.clients[key] = factory(path, project_root)
        return self.clients[key]

    def _stamp(self, roots):
        result = []
        try:
            for root in roots:
                # Include ancestors so replacing a namespace with a symlink fails closed.
                for parent in (root, *root.parents):
                    if parent.is_symlink():
                        raise StorageError('bundle_path_invalid')
                paths = [root, *sorted(root.rglob('*'))] if root.exists() else [root]
                for path in paths:
                    try:
                        info = path.lstat()
                    except FileNotFoundError:
                        result.append((str(path), None))
                        continue
                    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                        raise StorageError('bundle_path_invalid')
                    result.append((str(path), info.st_mode, info.st_dev, info.st_ino,
                                   info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            return tuple(result)
        except StorageError:
            raise
        except Exception:
            raise StorageError('bundle_read_failed') from None

    @contextmanager
    def use(self, manager):
        active = manager.catalog.read()
        if active is None:
            self.clear()
            yield
            return
        version = active.version
        roots = [manager.bundles._path(version.bundle_id),
                 manager.bundles._path(version.vector_index_id, namespace='vectors'),
                 manager.bundles._path(version.bm25_index_id, namespace='bm25')]
        token = None
        try:
            before = self._stamp(roots)
            cold = self.version != active or self.stamp != before
            if cold:
                self.clear()
                self.version = active
                self.stamp = before
                self.identities = {version.bundle_id, *(str(p) for p in roots)}
                LOGGER.info('query_resources_reload revision=%s', active.revision)
            token = _CURRENT.set(self)
            yield
            after = self._stamp(roots)
            if cold:
                # Native first-open maintenance precedes the full row audit. Retained
                # clients avoid their shutdown writes during subsequent queries.
                if business_stamp(before, roots[1]) != business_stamp(after, roots[1]):
                    raise StorageError('bundle_integrity_failed')
                self.stamp = after
            elif after != before:
                self.clear()
        except BaseException:
            try:
                self.clear()
            except StorageError:
                LOGGER.error('query_resources_cleanup_failed code=chroma_close_failed')
            raise
        finally:
            if token is not None:
                _CURRENT.reset(token)
