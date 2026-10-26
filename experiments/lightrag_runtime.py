"""Pinned runtime, explicit tokenizer preparation, offline subprocess boundary."""
import argparse
import base64
from contextlib import contextmanager
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from urllib.request import build_opener

from experiments.embedding_probe import NoRedirect, ProbeError
from experiments.vector_index import digest

TOKEN_URL = 'https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken'
TOKEN_SHA256 = '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'
TOKEN_CACHE_KEY = hashlib.sha1(TOKEN_URL.encode()).hexdigest()


def check_tokenizer(cache_dir, encoding):
    if encoding != 'o200k_base': raise ProbeError('runtime', 'invalid_tokenizer_encoding')
    path = Path(cache_dir)/TOKEN_CACHE_KEY
    try: data = path.read_bytes()
    except OSError: raise ProbeError('runtime', 'missing_tokenizer_asset') from None
    if digest(data) != TOKEN_SHA256: raise ProbeError('runtime', 'tokenizer_hash_mismatch')
    return {'encoding': encoding, 'sha256': TOKEN_SHA256, 'bytes': len(data)}


def prepare_tokenizer(cache_dir, encoding):
    if encoding != 'o200k_base': raise ProbeError('runtime', 'invalid_tokenizer_encoding')
    path = Path(cache_dir)/TOKEN_CACHE_KEY
    if path.exists(): return check_tokenizer(cache_dir, encoding)
    try:
        with build_opener(NoRedirect()).open(TOKEN_URL, timeout=30) as response:
            data = response.read(10*1024*1024+1)
        if len(data) > 10*1024*1024 or digest(data) != TOKEN_SHA256:
            raise ProbeError('runtime', 'tokenizer_hash_mismatch')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as handle: handle.write(data)
    except ProbeError: raise
    except Exception: raise ProbeError('runtime', 'tokenizer_prepare_failed') from None
    return check_tokenizer(cache_dir, encoding)


def worker_environment(cache_dir, inherited=None):
    # Whitelist prevents SDK import-time environment defaults and provider credentials leaking into the worker.
    inherited = os.environ if inherited is None else inherited
    env = {k: inherited[k] for k in ['PATH', 'HOME', 'TMPDIR', 'LANG', 'SYSTEMROOT'] if k in inherited}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHON_DOTENV_DISABLED='1',
               TIKTOKEN_CACHE_DIR=os.path.abspath(cache_dir), PYTHONHASHSEED='0',
               B0_OFFLINE='1')
    return env


@contextmanager
def offline_guard(counter):
    original = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo, socket.socket.sendto)
    def forbid(*args, **kwargs):
        counter[0] += 1
        raise ProbeError('network', 'network_forbidden')
    socket.socket.connect = socket.socket.connect_ex = socket.getaddrinfo = socket.socket.sendto = forbid
    try: yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo, socket.socket.sendto = original


def verify_runtime(lock_path, sdk_version):
    try:
        if sdk_version != '1.5.7': raise ValueError('sdk')
        lock = Path(lock_path).read_bytes()
        pinned = re.findall(rb'^([\w.-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})$', lock, re.M)
        if len(pinned) != 62: raise ValueError('lock')
        versions = {name.decode(): version.decode() for name,version,_ in pinned}
        if versions.get('lightrag-hku') != sdk_version: raise ValueError('sdk')
        for name, expected in versions.items():
            if metadata.version(name) != expected: raise ValueError('version')
        sdk = metadata.distribution('lightrag-hku')
        files = {}
        for path in sdk.files:
            if str(path).startswith('lightrag/') and str(path).endswith('.py'):
                data = path.locate().read_bytes(); value = digest(data)
                if not path.hash or path.hash.mode != 'sha256' or \
                        base64.urlsafe_b64encode(bytes.fromhex(value)).decode().rstrip('=') != path.hash.value:
                    raise ValueError('record')
                files[str(path)] = value
        if not files: raise ValueError('sources')
        return {'sdk_version': sdk_version, 'lock_sha256': digest(lock), 'versions': versions,
                'sdk_source_sha256': digest(json.dumps(files, sort_keys=True).encode()), 'sdk_source_count': len(files)}
    except (OSError, ValueError, metadata.PackageNotFoundError):
        raise ProbeError('runtime', 'runtime_mismatch') from None


def supervise(command, payload, cwd, env, timeout):
    if timeout <= 0: raise ProbeError('deadline', 'worker_timeout')
    cwd = Path(cwd); cwd.mkdir(parents=True, exist_ok=True)
    process = None
    try:
        with (cwd/'worker-stderr.txt').open('x') as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                       text=True, cwd=cwd, env=env)
            try: output, _ = process.communicate(json.dumps(payload, ensure_ascii=False, allow_nan=False), timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()
                raise ProbeError('deadline', 'worker_timeout') from None
        try: result = json.loads(output)
        except ValueError: raise ProbeError('worker', 'worker_failed') from None
        with (cwd/'worker-result.json').open('x') as handle:
            json.dump(result, handle, ensure_ascii=False, allow_nan=False)
        if process.returncode != 0 or result.get('status') != 'complete':
            error = result.get('sanitized_error', {})
            category = error.get('category', 'worker_failed')
            raise ProbeError('worker', category)
        return result
    except ProbeError: raise
    except (OSError, ValueError, TypeError): raise ProbeError('worker', 'worker_failed') from None
    finally:
        # Serialization/pipe errors after Popen must not leave a running child behind.
        if process is not None and process.poll() is None:
            process.kill(); process.communicate()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-tokenizer', action='store_true', required=True)
    parser.add_argument('--encoding', required=True); parser.add_argument('--cache-dir', required=True)
    args = parser.parse_args(argv)
    try: print(json.dumps(prepare_tokenizer(args.cache_dir, args.encoding)))
    except ProbeError as error: print(str(error), file=sys.stderr); return 2
    return 0


if __name__ == '__main__': raise SystemExit(main())
