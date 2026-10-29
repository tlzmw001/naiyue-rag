"""The user entry point owns only services it starts."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import pytest
import yaml
from test_model_registry import settings_at

ROOT=Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as handle:
        handle.bind(('127.0.0.1',0));return handle.getsockname()[1]


def service_config(tmp_path):
    cfg=settings_at(tmp_path);path=Path(cfg.config_path)
    raw=yaml.safe_load(path.read_text());raw['service']['port']=free_port()
    raw['service']['startup_timeout_seconds']=20;raw['service']['shutdown_timeout_seconds']=10
    path.write_text(yaml.safe_dump(raw),encoding='utf-8')
    from naiyue_rag import load_application_settings
    return load_application_settings(path)


def child_env(root):
    # Public package source only for repository tests; wheel smoke uses no PYTHONPATH.
    return {**os.environ,'HOME':str(root),'USERPROFILE':str(root),'PYTHONPATH':str(ROOT),'OMP_NUM_THREADS':'1'}


@pytest.mark.parametrize('args',[['--help'],['--version'],['chat','--help'],['models','--help']])
def test_help_and_version_do_not_create_user_configuration(tmp_path,args):
    proc=subprocess.run([sys.executable,'-m','naiyue_rag',*args],cwd=tmp_path,env=child_env(tmp_path),
                        capture_output=True,text=True,timeout=30)
    assert proc.returncode==0,proc.stderr
    assert not (tmp_path/'.naiyue-rag').exists()
    assert proc.stdout.strip()


def test_config_is_accepted_before_and_after_subcommand(tmp_path):
    from naiyue_rag.cli import parser
    for args in [['--config','x.yaml','chat'],['chat','--config','x.yaml']]:
        parsed=parser().parse_args(args);assert parsed.config=='x.yaml' and parsed.command=='chat'


def test_chat_eof_starts_and_cleans_own_real_service(tmp_path):
    cfg=service_config(tmp_path)
    proc=subprocess.run([sys.executable,'-m','naiyue_rag','chat','--config',cfg.config_path],input='',cwd=tmp_path,
        env=child_env(tmp_path),capture_output=True,text=True,timeout=45)
    assert proc.returncode==0,proc.stderr
    assert '检索' in proc.stdout and cfg.service.access_token not in proc.stdout+proc.stderr
    with socket.socket() as handle:assert handle.connect_ex(('127.0.0.1',cfg.service.port))!=0


def test_existing_service_is_reused_and_survives_chat_exit(tmp_path):
    from naiyue_rag.managed_service import ManagedConnection
    cfg=service_config(tmp_path)
    with ManagedConnection(cfg) as owner:
        health=owner.client.health();assert owner.process is not None
        proc=subprocess.run([sys.executable,'-m','naiyue_rag','chat','--config',cfg.config_path],input='/exit\n',cwd=tmp_path,
            env=child_env(tmp_path),capture_output=True,text=True,timeout=30)
        assert proc.returncode==0,proc.stderr
        assert owner.client.health()==health and owner.process.poll() is None
        result=owner.client.request('documents',{})
        assert result['documents']==[]
    assert owner.process.poll()==0


def test_wrong_token_does_not_start_or_stop_existing_service(tmp_path):
    from naiyue_rag.managed_service import ManagedConnection
    from naiyue_rag.core.application_settings import _assemble
    from naiyue_rag.local_client import LocalServiceError
    cfg=service_config(tmp_path)
    with ManagedConnection(cfg) as owner:
        raw=cfg.to_dict();raw['service']['access_token']='x'*32;wrong=_assemble(Path(cfg.config_path),raw)
        with pytest.raises(LocalServiceError,match='service_unauthorized'):
            with ManagedConnection(wrong):pass
        assert owner.process.poll() is None and owner.client.health()['protocol']==1


def test_child_parent_pipe_eof_stops_only_that_child(tmp_path):
    from naiyue_rag.local_client import LocalClient,LocalServiceError
    cfg=service_config(tmp_path)
    process=subprocess.Popen([sys.executable,'-m','naiyue_rag','--config',cfg.config_path,'--parent-watch'],
        cwd=tmp_path,env=child_env(tmp_path),stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        with LocalClient(cfg) as client:
            deadline=time.monotonic()+20
            while True:
                try:assert client.health()['protocol']==1;break
                except LocalServiceError:
                    assert process.poll() is None and time.monotonic()<deadline
                    time.sleep(.05)
            process.stdin.close();process.wait(timeout=15)
            assert process.returncode==0
    finally:
        if process.poll() is None:process.kill();process.wait()
        process.stderr.close()


def test_nonproject_listener_is_never_killed(tmp_path):
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from threading import Thread
    from naiyue_rag.managed_service import ManagedConnection
    from naiyue_rag.local_client import LocalServiceError
    cfg=service_config(tmp_path)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'{"other":true}')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',cfg.service.port),Handler);thread=Thread(target=server.serve_forever);thread.start()
    try:
        with pytest.raises(LocalServiceError,match='service_identity_mismatch'):
            with ManagedConnection(cfg):pass
        assert thread.is_alive()
    finally:server.shutdown();thread.join();server.server_close()


def test_chat_handles_errors_and_removes_terminal_escape_sequences(tmp_path,monkeypatch,capsys):
    from naiyue_rag.cli import chat
    from naiyue_rag.local_client import LocalServiceError
    inputs=iter(['first','second','/exit']);monkeypatch.setattr('builtins.input',lambda prompt:next(inputs))
    class Client:
        def request(self,op,data):
            if data['query']=='first':raise LocalServiceError('application_busy')
            return {'status':'retrieved','context_text':'正文\x1b[31m危险\x1b[0m\x00结束'}
    assert chat(Client())==0
    captured=capsys.readouterr()
    assert 'application_busy' in captured.out and '正文' in captured.out and '\x1b' not in captured.out and '\x00' not in captured.out


def test_cli_explicit_missing_config_is_nonzero_and_private(tmp_path):
    proc=subprocess.run([sys.executable,'-m','naiyue_rag','documents','--config',str(tmp_path/'missing.yaml')],
        cwd=tmp_path,env=child_env(tmp_path),capture_output=True,text=True,timeout=30)
    assert proc.returncode==2 and json.loads(proc.stdout)['error']['code']=='invalid_application_settings'
    assert not (tmp_path/'.naiyue-rag').exists()


def test_chat_keyboard_interrupt_is_a_normal_exit(monkeypatch,capsys):
    from naiyue_rag.cli import chat
    def interrupt(prompt):raise KeyboardInterrupt()
    monkeypatch.setattr('builtins.input',interrupt)
    assert chat(object())==0


def test_missing_model_key_explains_the_configuration_field(monkeypatch,capsys):
    from naiyue_rag.cli import chat
    from naiyue_rag.local_client import LocalServiceError
    inputs=iter(['question','/exit']);monkeypatch.setattr('builtins.input',lambda prompt:next(inputs))
    class Client:
        def request(self,*args):raise LocalServiceError('model_credential_invalid')
    assert chat(Client())==0
    output=capsys.readouterr().out
    assert 'models.json' in output and 'api_key' in output


@pytest.mark.parametrize('primary',[False,True])
def test_client_cleanup_failure_is_safe_and_preserves_primary(tmp_path,caplog,primary):
    from types import SimpleNamespace
    from naiyue_rag.managed_service import ManagedConnection
    from naiyue_rag.local_client import LocalServiceError
    connection=ManagedConnection(service_config(tmp_path));connection.client.close()
    def fail():raise OSError('SYNTHETIC_PRIVATE_CLIENT_CLOSE')
    connection.client=SimpleNamespace(close=fail)
    if primary:
        assert connection.__exit__(ValueError,ValueError('PRIMARY'),None) is False
    else:
        with pytest.raises(LocalServiceError,match='service_shutdown_failed'):connection.__exit__(None,None,None)
    assert 'SYNTHETIC_PRIVATE_CLIENT_CLOSE' not in caplog.text


def test_real_local_client_receives_retrieval_timeout_before_http_timeout(tmp_path,monkeypatch):
    from dataclasses import replace
    from threading import Thread,Event
    import uvicorn
    from naiyue_rag.serving.engine import RetrievalEngine
    from naiyue_rag.service import create_service
    from naiyue_rag.local_client import LocalClient,LocalServiceError
    cfg=service_config(tmp_path)
    cfg=replace(cfg,service=replace(cfg.service,request_timeout_seconds=.5),
        retrieval=replace(cfg.retrieval,request_timeout_seconds=.5))
    release=Event()
    def blocked(*args,**kwargs):
        assert release.wait(10)
        return {'status':'synthetic'}
    monkeypatch.setattr(RetrievalEngine,'execute',blocked)
    server=uvicorn.Server(uvicorn.Config(create_service(cfg),host=cfg.service.host,port=cfg.service.port,
        loop='asyncio',http='h11',log_level='critical',access_log=False))
    thread=Thread(target=server.run,daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started:
            assert thread.is_alive() and time.monotonic()<deadline
            time.sleep(.01)
        with LocalClient(cfg) as client:
            with pytest.raises(LocalServiceError,match='^retrieval_timeout$'):
                client.request('query',{'query':'synthetic'})
            assert client.status()['draining']==1
    finally:
        release.set();server.should_exit=True;thread.join(10)
        assert not thread.is_alive()
