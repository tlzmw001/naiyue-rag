"""Lazy native SDK boundary; shared dotenv allowed, explicit policy wins."""
from contextlib import contextmanager
from importlib import metadata
import logging
import os
from ..core.errors import StorageError

SDK_VERSION='1.5.9'


def new_client(path,project_root):
    try:version=metadata.version('chromadb')
    except Exception:raise StorageError('chroma_runtime_mismatch') from None
    if version!=SDK_VERSION:raise StorageError('chroma_runtime_mismatch')
    try:
        # SDK import itself can read cwd/.env; malformed known fields fail safely here.
        import chromadb
        from chromadb.config import Settings
        settings=Settings(_env_file=str(project_root/'.env'),allow_reset=False,
            anonymized_telemetry=False,chroma_api_impl='chromadb.api.rust.RustBindingsAPI')
    except Exception:raise StorageError('chroma_environment_invalid') from None
    try:return chromadb.PersistentClient(path=str(path),settings=settings)
    except Exception as error:
        if os.environ.get('NYR_NATIVE_DIAGNOSTICS')=='1':
            logging.getLogger(__name__).error('chroma_diagnostic phase=client type=%s detail=%s',
                type(error).__name__,str(error)[:1000])
        raise StorageError('chroma_open_failed') from None


def call(method,*,code='chroma_read_failed',**kwargs):
    try:return method(**kwargs)
    except StorageError:raise
    except Exception as error:
        if code=='chroma_open_failed' and os.environ.get('NYR_NATIVE_DIAGNOSTICS')=='1':
            logging.getLogger(__name__).error('chroma_diagnostic phase=collection type=%s detail=%s',
                type(error).__name__,str(error)[:1000])
        raise StorageError(code) from None


@contextmanager
def open_collection(path,project_root,name,identity,batch_size,*,create=False):
    client=new_client(path,project_root);failed=False
    try:
        if create:
            maximum=call(client.get_max_batch_size)
            if type(maximum) is not int or maximum<batch_size:raise StorageError('chroma_batch_limit')
            collection=call(client.create_collection,code='chroma_open_failed',name=name,
                metadata=identity,embedding_function=None,configuration={'hnsw':{'space':'cosine'}})
        else:
            collection=call(client.get_collection,code='chroma_open_failed',name=name,embedding_function=None)
        try:
            configuration=collection.configuration
            if collection.metadata!=identity or configuration['hnsw']['space']!='cosine' or \
                    configuration.get('embedding_function') is not None:
                raise StorageError('chroma_identity_mismatch')
        except StorageError:raise
        except Exception:raise StorageError('chroma_identity_mismatch') from None
        yield collection
    except BaseException:
        failed=True
        raise
    finally:
        try:client.close()
        except Exception:
            if failed:logging.getLogger(__name__).error('chroma_close_failed code=chroma_close_failed')
            else:raise StorageError('chroma_close_failed') from None
