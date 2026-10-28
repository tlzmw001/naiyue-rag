"""Run with the candidate's clean venv Python, outside the repository cwd."""
import hashlib
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib import metadata
from importlib.resources import files
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def smoke(root,expected_version=None):
    import naiyue_rag
    import yaml
    assert Path(naiyue_rag.__file__).is_relative_to(Path(sys.prefix)), 'source import instead of installed package'
    installed_version=metadata.version('naiyue-rag')
    from naiyue_rag._version import __version__
    assert installed_version==__version__
    if expected_version is not None:assert installed_version==expected_version
    supported={'darwin':{'arm64'},'linux':{'x86_64'},'win32':{'AMD64','x86_64'}}
    assert platform.machine() in supported.get(sys.platform,set()), 'unsupported target architecture'
    # Imports verify full runtime dependencies, without fetching any model weights.
    import torch,sentence_transformers,transformers,chromadb,bm25s
    root=root.resolve();environment={**os.environ,'HOME':str(root),'USERPROFILE':str(root),'PYTHONUTF8':'1','OMP_NUM_THREADS':'1'}
    environment.pop('PYTHONPATH',None)
    environment.pop('OPENAI_LOG',None);environment.pop('OPENAI_CUSTOM_HEADERS',None)
    command=Path(sys.executable).parent/('nyr.exe' if os.name=='nt' else 'nyr')
    def run(*args,input=None):
        result=subprocess.run([str(command),*args],cwd=root,env=environment,input=input,encoding='utf-8',
            capture_output=True,timeout=90)
        assert result.returncode==0, result.stdout+result.stderr
        assert 'SYNTHETIC_MODEL_KEY' not in result.stdout+result.stderr
        return result.stdout
    assert 'chat' in run('--help') and run('--version').strip()=='nyr '+installed_version
    assert not (root/'.naiyue-rag').exists()
    init=subprocess.run([sys.executable,'-I','-c',
        'from naiyue_rag import load_application_settings; load_application_settings()'],cwd=root,env=environment,capture_output=True,timeout=30)
    assert init.returncode==0,init.stderr.decode()
    config=root/'.naiyue-rag/config.yaml';models=config.with_name('models.json')
    raw=yaml.safe_load(config.read_text(encoding='utf-8'));raw['service']['port']=free_port()
    raw['service']['startup_timeout_seconds']=45
    config.write_text(yaml.safe_dump(raw,allow_unicode=True),encoding='utf-8')
    assert json.loads(run('documents'))['documents']==[]
    assert '终端检索' in run('chat',input='')
    calls=[]
    class ModelHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.headers.get('Authorization')=='Bearer SYNTHETIC_MODEL_KEY'
            wire=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(self.path)
            if self.path.endswith('/embeddings'):
                result={'model':'synthetic-model','data':[{'index':i,'embedding':[1.,2.,3.]} for i in reversed(range(len(wire['input'])))],
                    'usage':{'prompt_tokens':7*len(wire['input']),'total_tokens':7*len(wire['input'])}}
            else:
                passages=json.loads(wire['messages'][1]['content'])['passages']
                result={'model':'synthetic-model','choices':[{'finish_reason':'stop','message':{'role':'assistant',
                    'content':json.dumps({'scores':[{'passage_id':p['passage_id'],'score':i} for i,p in enumerate(passages)]})}}],
                    'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}
            payload=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def log_message(self,*args):pass
    model_server=ThreadingHTTPServer(('127.0.0.1',0),ModelHandler)
    worker=Thread(target=model_server.serve_forever);worker.start()
    try:
        # This is a synthetic test provider, with actual SDK HTTP and native indexes.
        registry=json.loads(models.read_text(encoding='utf-8'))
        for uid in ('embedding','reranker'):
            model=registry['models'][uid];model.pop('api_key_env',None)
            model.update(api_key='SYNTHETIC_MODEL_KEY',model='synthetic-model',base_url=f'http://127.0.0.1:{model_server.server_port}/v1/')
        registry['models']['embedding'].update(expected_dimensions=3,allowed_response_models=['synthetic-model'])
        models.write_text(json.dumps(registry),encoding='utf-8')
        source=config.parent/'knowledge';source.mkdir()
        (source/'L1_模块.md').write_text('# 模块\n\nfeature_x 开关控制边界。\n',encoding='utf-8')
        (source/'L2_方案.md').write_text('# 方案\n\nthreshold=0.5；feature_x 开启时检查边界。\n',encoding='utf-8')
        first=json.loads(run('ingest','--expected-revision','0'))
        assert first['status']=='activated' and first['active']['revision']==1
        before=len(calls);repeat=json.loads(run('ingest','--expected-revision','1'))
        assert repeat['status']=='unchanged' and len(calls)==before
        listed=json.loads(run('documents'));assert len(listed['documents'])==2
        # Query persists across a fresh service process; original source unavailable.
        source.rename(source.with_name('source-offline'))
        result=json.loads(run('query','feature_x threshold','--expected-revision','1'))
        assert result['schema_version']==2 and result['status']=='retrieved' and result['evidence']
        assert result['observations']['rerank']['usage']['total_tokens']==15
        assert result['query_sha256']==hashlib.sha256(b'feature_x threshold').hexdigest()
        assert any(p.endswith('/chat/completions') for p in calls)
        # Parent pipe EOF and Ctrl+C have separate ownership paths.
        service=subprocess.Popen([str(command)],cwd=root,env=environment,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
        from naiyue_rag.local_client import LocalClient,LocalServiceError
        from naiyue_rag import load_application_settings
        settings=load_application_settings(config)
        try:
            with LocalClient(settings) as client:
                deadline=time.monotonic()+45
                while True:
                    try:health=client.health();break
                    except LocalServiceError:
                        assert service.poll() is None and time.monotonic()<deadline
                        time.sleep(.05)
                rendered=run('chat',input='feature_x threshold\n/exit\n')
                if '终端检索' not in rendered or 'feature_x' not in rendered:
                    print(f'chat_smoke_diagnostic rendered={rendered[:1000]!r}',file=sys.stderr)
                assert '终端检索' in rendered and 'feature_x' in rendered
                assert client.health()==health and service.poll() is None
                service.send_signal(signal.CTRL_BREAK_EVENT if os.name=='nt' else signal.SIGINT)
                service.wait(timeout=30)
                assert service.returncode==0,service.stderr.read().decode('utf-8',errors='replace')
        finally:
            if service.poll() is None:service.kill();service.wait()
            service.stdout.close();service.stderr.close()
        with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',settings.service.port))!=0
        crashed=subprocess.Popen([str(command),'--parent-watch'],cwd=root,env=environment,stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            with LocalClient(settings) as client:
                deadline=time.monotonic()+45
                while True:
                    try:client.health();break
                    except LocalServiceError:
                        assert crashed.poll() is None and time.monotonic()<deadline
                        time.sleep(.05)
                assert client.request('query',{'query':'feature_x'})['status']=='retrieved'
                crashed.kill();crashed.wait(timeout=15)
        finally:
            if crashed.poll() is None:crashed.kill();crashed.wait()
            crashed.stdin.close()
        recovered=json.loads(run('query','feature_x threshold','--expected-revision','1'))
        assert recovered['status']=='retrieved' and recovered['active']==result['active']
        print(json.dumps({'status':'passed','platform':platform.platform(),'machine':platform.machine(),
            'python':platform.python_version(),'installed_version':metadata.version('naiyue-rag'),
            'native_documents':2,'active_revision':1,'query_evidence':len(result['evidence']),
            'model_requests':len(calls),'real_vendor_requests':0,'weights_downloaded':False,'reopened_after_process_crash':True}))
    finally:model_server.shutdown();worker.join();model_server.server_close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--expected-version');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nyr-installed-smoke-') as temporary:smoke(Path(temporary),args.expected_version)
