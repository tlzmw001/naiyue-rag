import importlib
from pathlib import Path
import socket

import pytest


@pytest.fixture
def mod(): return importlib.import_module('experiments.lightrag_runtime')


def test_tokenizer_missing_and_hash_mismatch_are_observable(mod, tmp_path):
    with pytest.raises(mod.ProbeError, match='missing_tokenizer_asset'):
        mod.check_tokenizer(tmp_path, 'o200k_base')
    (tmp_path/mod.TOKEN_CACHE_KEY).write_bytes(b'corrupt')
    with pytest.raises(mod.ProbeError, match='tokenizer_hash_mismatch'):
        mod.check_tokenizer(tmp_path, 'o200k_base')


def test_controlled_env_removes_credentials_and_hidden_defaults(mod):
    env = mod.worker_environment('/tmp/tokens', {'NAIYUE_RAG_ZHIPU_API_KEY': 'sentinel',
                                               'OPENAI_API_KEY': 'sentinel', 'CHUNK_SIZE': '1',
                                               'TOP_K': '1', 'PATH': '/bin'})
    assert 'NAIYUE_RAG_ZHIPU_API_KEY' not in env and 'OPENAI_API_KEY' not in env
    assert 'CHUNK_SIZE' not in env and 'TOP_K' not in env
    assert env['PYTHON_DOTENV_DISABLED'] == '1'
    assert env['TIKTOKEN_CACHE_DIR'] == '/tmp/tokens'


def test_network_is_counted_and_blocked(mod):
    counter = [0]
    with mod.offline_guard(counter):
        with pytest.raises(mod.ProbeError, match='network_forbidden'):
            socket.getaddrinfo('example.com', 443)
        assert counter == [1]


def test_timeout_reaps_child_and_keeps_fixed_error(mod, tmp_path):
    # An event-independent subprocess exit wait verifies the hard timeout path.
    import sys
    with pytest.raises(mod.ProbeError, match='worker_timeout'):
        mod.supervise([sys.executable, '-c', 'import time; time.sleep(30)'], {}, tmp_path, {}, .1)
    assert (tmp_path/'worker-stderr.txt').exists()


def test_nonzero_worker_is_not_success(mod, tmp_path):
    import sys
    with pytest.raises(mod.ProbeError, match='worker_failed'):
        mod.supervise([sys.executable, '-c', 'raise SystemExit(2)'], {}, tmp_path, {}, 10)


def test_payload_serialization_error_does_not_orphan_process(mod,tmp_path,monkeypatch):
    import subprocess,sys
    processes=[];old=subprocess.Popen
    def start(*a,**k):
        process=old(*a,**k);processes.append(process);return process
    monkeypatch.setattr(mod.subprocess,'Popen',start)
    try:
        with pytest.raises(mod.ProbeError,match='worker_failed'):
            mod.supervise([sys.executable,'-c','import time; time.sleep(30)'],{'invalid':float('nan')},tmp_path,{},10)
        assert all(p.poll() is not None for p in processes)
    finally:
        for process in processes:
            if process.poll() is None:process.kill();process.communicate()
