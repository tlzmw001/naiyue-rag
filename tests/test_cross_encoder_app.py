"""CLI selects the real local adapter; only the heavy model and HTTP are simulated."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
import yaml
from test_core_app import write_config,ROOT
from test_ingestion_pipeline_wiring import launch as ingest


def native(root,scenario):
    import socket
    from types import SimpleNamespace
    def deny(*args,**kwargs):raise AssertionError('unexpected network')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
    import httpx
    from test_openai_embedding import payload
    calls=[];predictions=[]
    def respond(request):
        assert request.url.path.endswith('/embeddings')
        calls.append(1);return httpx.Response(200,json=payload())
    httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
    class Tokenizer:
        model_max_length=512
        def __call__(self,q,text,**kwargs):
            assert kwargs['truncation'] is False;return {'input_ids':list(range(30))}
    class Native:
        def __init__(self,path,**kwargs):
            assert kwargs['local_files_only'] is True and kwargs['trust_remote_code'] is False and kwargs['token'] is False
            assert kwargs['device']=='cpu' and kwargs['model_kwargs']=={'use_safetensors':True} and 'max_length' not in kwargs
            self.tokenizer=Tokenizer()
        def predict(self,pairs,**kwargs):
            assert self.max_seq_length==128 and kwargs['batch_size']==3
            predictions.append(1)
            if scenario=='failure':raise RuntimeError('SYNTHETIC_PRIVATE')
            return [float(i) for i in range(len(pairs))]
    sys.modules['sentence_transformers']=SimpleNamespace(CrossEncoder=Native)
    from naiyue_rag.app import main
    args=['--config',str(root/'app.yaml'),'query','--query','cvr_ltv 开关 TC-01 0.5','--expected-revision','1']
    if scenario=='empty':args+=['--scope']
    code=main(args)
    assert code==(2 if scenario=='failure' else 0)
    assert len(calls)==len(predictions)==(0 if scenario=='empty' else 1)


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_cross_encoder_app import native
native(Path(sys.argv[2]),sys.argv[3])
'''


@pytest.mark.parametrize('scenario',['normal','failure','empty'])
def test_cli_local_backend_whole_chain_and_failure(tmp_path,scenario):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\nANONYMIZED_TELEMETRY=false\n')
    ingest(tmp_path,'build','normal');write_config(tmp_path)
    model=tmp_path/'model';model.mkdir();files={}
    for name in ('config.json','tokenizer.json','tokenizer_config.json','model.safetensors'):
        raw=b'SYNTHETIC_MODEL_FILE';(model/name).write_bytes(raw)
        files[name]={'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    (model/'naiyue-model.json').write_text(json.dumps(dict(model_id='synthetic/model',revision='a'*40,files=files)))
    cfg=dict(model_id='synthetic/model',model_revision='a'*40,model_path=str(model),device='cpu',batch_size=3,
        max_pair_tokens=128,max_model_bytes=10000)
    (tmp_path/'local.yaml').write_text(yaml.safe_dump(cfg))
    app=yaml.safe_load((tmp_path/'app.yaml').read_text());app['rerank_backend']='cross_encoder';app['model_settings']='local.yaml'
    (tmp_path/'app.yaml').write_text(yaml.safe_dump(app))
    (tmp_path/'source').rename(tmp_path/'source-offline')
    process=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(ROOT),str(tmp_path),scenario],cwd=tmp_path,
        env={'HOME':str(tmp_path),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},capture_output=True,text=True,timeout=60)
    assert process.returncode==0,process.stderr
    value=json.loads(process.stdout)
    if scenario=='failure':
        assert value['error']['code']=='rerank_model_failed' and value['error']['encoding_report']['status']=='success'
        assert 'SYNTHETIC_PRIVATE' not in process.stdout+process.stderr
    else:
        assert value['observations']['rerank_configuration']['provider']=='cross_encoder'
        assert value['observations']['rerank_configuration']['model']=='synthetic/model'
        assert value['status']==('empty' if scenario=='empty' else 'retrieved')
        assert value['observations']['rerank']['attempted_requests']==0
