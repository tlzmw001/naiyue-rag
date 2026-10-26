"""Local SQLite version registration and one active pointer; no artifact rebuilding."""
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import sqlite3
import stat
from ..core.errors import StorageError
from .bundle_store import BundleStore,_json_bytes,_parse
from .version_types import IndexVersion,ActiveVersion,MAX_REVISION

LOGGER=logging.getLogger(__name__)
SCHEMA=(
    'CREATE TABLE versions (version_id TEXT PRIMARY KEY NOT NULL, descriptor_json TEXT NOT NULL)',
    "CREATE TABLE active (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    'version_id TEXT NOT NULL REFERENCES versions(version_id), '
    "revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>0))")


def _busy(error):
    code=getattr(error,'sqlite_errorcode',0)
    return type(code) is int and code & 255 in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED)


class IndexCatalog:
    def __init__(self,settings):
        self.bundles=BundleStore(settings);self.settings=settings

    @property
    def path(self):
        try:
            target=self.bundles._path(error_code='catalog_path_invalid').parent/'catalog.sqlite3'
            for p in [target,*(Path(str(target)+suffix) for suffix in ('-journal','-wal','-shm'))]:
                if p.is_symlink():raise StorageError('catalog_path_invalid')
                if p.exists():
                    info=p.stat()
                    if not stat.S_ISREG(info.st_mode):raise StorageError('catalog_path_invalid')
                    if info.st_size>self.settings.max_bundle_bytes:raise StorageError('catalog_limit_exceeded')
            return target
        except StorageError:raise
        except Exception:raise StorageError('catalog_path_invalid') from None

    def _commit(self,conn):conn.execute('COMMIT')
    def _rollback(self,conn):conn.execute('ROLLBACK')
    def _close(self,conn):conn.close()

    def _close_after(self,conn,*,failed,committed=False):
        try:self._close(conn)
        except Exception:
            if failed:LOGGER.error('catalog_cleanup_failed code=catalog_cleanup_failed')
            else:raise StorageError('catalog_commit_uncertain' if committed else 'catalog_cleanup_failed') from None

    def _abort(self,conn):
        try:
            # Absence of a transaction may mean COMMIT already succeeded, not a confirmed rollback.
            if not conn.in_transaction:return False
            self._rollback(conn)
            return not conn.in_transaction
        except Exception:
            LOGGER.error('catalog_cleanup_failed code=catalog_cleanup_failed')
            return False

    def _size(self,conn):
        pages=conn.execute('PRAGMA page_count').fetchone()[0]
        size=conn.execute('PRAGMA page_size').fetchone()[0]
        if pages*size>self.settings.max_bundle_bytes:raise StorageError('catalog_limit_exceeded')

    def _validate(self,conn):
        try:
            if conn.execute('PRAGMA user_version').fetchone()[0]!=1:
                raise StorageError('catalog_schema_unsupported')
            rows=conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema "
                "WHERE name NOT GLOB 'sqlite_*' ORDER BY name").fetchmany(3)
            if rows!=[('table','active','active',SCHEMA[1]),('table','versions','versions',SCHEMA[0])]:
                raise StorageError('catalog_schema_unsupported')
            if conn.execute('PRAGMA journal_mode').fetchone()[0]!='delete':
                raise StorageError('catalog_schema_unsupported')
            if conn.execute('PRAGMA quick_check(1)').fetchone()!=('ok',) or \
                    conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise StorageError('catalog_integrity_failed')
            self._size(conn)
        except StorageError:raise
        except sqlite3.Error as error:
            code=getattr(error,'sqlite_errorcode',0) & 255
            raise StorageError('catalog_busy' if _busy(error) else 'catalog_integrity_failed'
                if code in (sqlite3.SQLITE_CORRUPT,sqlite3.SQLITE_NOTADB) else 'catalog_read_failed') from None

    def _connect(self,*,write):
        path=self.path;created=False;conn=None;failed=True;committing=False
        if not write and not path.exists():return None
        try:
            if write and not path.exists():
                if not path.parent.is_dir():raise StorageError('catalog_path_invalid')
                try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
                except FileExistsError:raise StorageError('catalog_busy') from None
                os.close(fd);created=True
            # URI escaping is supplied by Path.as_uri, never by string-interpolating a raw path.
            conn=sqlite3.connect(path.as_uri()+('?mode=rw' if write else '?mode=ro'),
                                 uri=True,timeout=0,isolation_level=None)
            conn.execute('PRAGMA foreign_keys=ON');conn.execute('PRAGMA read_uncommitted=OFF')
            conn.execute('PRAGMA trusted_schema=OFF')
            if not write:conn.execute('PRAGMA query_only=ON')
            if created:
                conn.execute('PRAGMA journal_mode=DELETE');conn.execute('PRAGMA synchronous=FULL')
                conn.execute('BEGIN IMMEDIATE')
                for sql in SCHEMA:conn.execute(sql)
                conn.execute('PRAGMA user_version=1');self._size(conn)
                committing=True;self._commit(conn)
                self.bundles._sync_directory(path.parent)
                committing=False
            self._validate(conn)
            if write:conn.execute('PRAGMA synchronous=FULL')
            failed=False
            return conn
        except BaseException as error:
            rolled_back=self._abort(conn) if conn is not None else True
            if not isinstance(error,Exception):raise
            if committing:
                code='catalog_busy' if _busy(error) and rolled_back else 'catalog_commit_uncertain'
                raise StorageError(code) from None
            if isinstance(error,StorageError):raise
            raise StorageError('catalog_busy' if _busy(error) else
                'catalog_write_failed' if write else 'catalog_read_failed') from None
        finally:
            if failed and conn is not None:self._close_after(conn,failed=True)

    def _decode(self,uid,raw,length):
        if type(length) is not int:raise StorageError('catalog_integrity_failed')
        if length>self.settings.max_manifest_bytes:raise StorageError('catalog_limit_exceeded')
        try:
            if type(raw) is not str:raise StorageError('catalog_integrity_failed')
            obj=IndexVersion.from_dict(_parse(raw.encode('utf-8'),canonical=False))
            if obj.version_id!=uid or _json_bytes(obj.to_dict(),self.settings.max_manifest_bytes,newline=False).decode()!=raw:
                raise StorageError('catalog_integrity_failed')
            if obj.knowledge_base_id!=self.settings.knowledge_base_id:raise StorageError('catalog_identity_mismatch')
            if obj.document_count>self.settings.max_documents or obj.chunk_count>self.settings.max_chunks:
                raise StorageError('catalog_limit_exceeded')
            return obj
        except StorageError as error:
            if error.code in ('catalog_schema_unsupported','catalog_identity_mismatch','catalog_limit_exceeded'):raise
            raise StorageError('catalog_integrity_failed') from None
        except Exception:raise StorageError('catalog_integrity_failed') from None

    def current(self,conn):
        # CASE bounds the text fetched into Python, including deliberately oversized rows.
        rows=conn.execute('SELECT a.revision,a.version_id,length(CAST(v.descriptor_json AS BLOB)), '
            'CASE WHEN length(CAST(v.descriptor_json AS BLOB))<=? THEN v.descriptor_json END '
            'FROM active a LEFT JOIN versions v ON v.version_id=a.version_id',
            (self.settings.max_manifest_bytes,)).fetchmany(2)
        if not rows:return None
        if len(rows)!=1:raise StorageError('catalog_integrity_failed')
        revision,uid,length,raw=rows[0]
        try:return ActiveVersion(revision,self._decode(uid,raw,length))
        except StorageError as error:
            if error.code=='catalog_invalid_request':raise StorageError('catalog_integrity_failed') from None
            raise

    def lookup(self,conn,uid):
        row=conn.execute('SELECT length(CAST(descriptor_json AS BLOB)), '
            'CASE WHEN length(CAST(descriptor_json AS BLOB))<=? THEN descriptor_json END '
            'FROM versions WHERE version_id=?',(self.settings.max_manifest_bytes,uid)).fetchone()
        return None if row is None else self._decode(uid,row[1],row[0])

    def publish(self,conn,version,revision):
        if revision>MAX_REVISION:raise StorageError('catalog_limit_exceeded')
        if type(version) is not IndexVersion or type(revision) is not int or revision<=0:
            raise StorageError('catalog_invalid_request')
        if version.knowledge_base_id!=self.settings.knowledge_base_id:raise StorageError('catalog_identity_mismatch')
        try:raw=_json_bytes(version.to_dict(),self.settings.max_manifest_bytes,newline=False).decode()
        except StorageError as error:
            raise StorageError('catalog_limit_exceeded' if error.code=='bundle_limit_exceeded' else error.code) from None
        existing=self.lookup(conn,version.version_id)
        if existing is None:conn.execute('INSERT INTO versions VALUES (?,?)',(version.version_id,raw))
        elif existing!=version:raise StorageError('catalog_integrity_failed')
        conn.execute('INSERT INTO active VALUES (1,?,?) ON CONFLICT(singleton) DO UPDATE '
            'SET version_id=excluded.version_id,revision=excluded.revision',(version.version_id,revision))

    @contextmanager
    def write(self):
        conn=self._connect(write=True);failed=False;committing=False;committed=False;cleanup=False
        before=conn.total_changes
        try:
            conn.execute('BEGIN IMMEDIATE');self._validate(conn)
            yield conn
            if conn.total_changes!=before:
                self._size(conn);committing=True
                self._commit(conn);committed=True
            else:
                cleanup=True;self._rollback(conn)
        except BaseException as error:
            failed=True;confirmed=self._abort(conn)
            if not isinstance(error,Exception):raise
            if committing:
                raise StorageError('catalog_busy' if _busy(error) and confirmed else 'catalog_commit_uncertain') from None
            if isinstance(error,StorageError):raise
            raise StorageError('catalog_busy' if _busy(error) else
                'catalog_cleanup_failed' if cleanup else 'catalog_write_failed') from None
        finally:self._close_after(conn,failed=failed,committed=committed)

    def read(self):
        conn=self._connect(write=False)
        if conn is None:return None
        failed=False
        try:
            conn.execute('BEGIN');self._validate(conn)
            return self.current(conn)
        except BaseException as error:
            failed=True
            if not isinstance(error,Exception) or isinstance(error,StorageError):raise
            raise StorageError('catalog_busy' if _busy(error) else 'catalog_read_failed') from None
        finally:self._close_after(conn,failed=failed)
