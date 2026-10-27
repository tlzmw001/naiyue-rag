"""Independent CLI, strict file config and SDK/native-index cross-process wiring."""
import json
from pathlib import Path
import os
import subprocess
import sys
import pytest
from test_ingestion_pipeline_wiring import launch as ingest

ROOT=Path(__file__).resolve().parents[1]


def write_config(tmp_path):
    import yaml
    job=json.loads((tmp_path/'job.json').read_text())
    from test_sparse_encoding_settings import sparse_config
    groups=dict(storage=job['storage'],encoding=job['encoding'],sparse=sparse_config(tmp_path).to_dict(),
        chroma=dict(collection_name='knowledge_hub',batch_size=2),bm25=dict(k1=1.5,b=.75),
        hybrid=dict(dense_top_k=20,sparse_top_k=20,fusion_top_k=10,rrf_k=60,bm25_statistics_scope='global',parallel_retrieval=True),
        rerank=dict(enabled=True,top_k=5,max_candidates=20,max_input_characters=100000),
        evidence=dict(max_context_characters=10000,max_response_bytes=1000000),
        llm_rerank=dict(model='synthetic-model',base_url='https://synthetic.invalid/v1/',timeout_seconds=5,
            deadline_seconds=10,max_response_bytes=10000,max_output_tokens=1024,temperature=0,extra_body={}))
    for k,v in groups.items():(tmp_path/f'{k}.yaml').write_text(yaml.safe_dump(v))
    app=dict(project_root=str(tmp_path),knowledge_base_root='source',key_env='NAIYUE_RAG_ZHIPU_API_KEY',
        chunk_size=40,chunk_overlap=10,rerank_backend='llm',model_settings='llm_rerank.yaml',
        **{k:f'{k}.yaml' for k in groups if k!='llm_rerank'})
    (tmp_path/'app.yaml').write_text(yaml.safe_dump(app))


def native(root,action):
    import socket
    def deny(*args,**kwargs):raise AssertionError('unexpected network')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
    import httpx
    from test_openai_embedding import payload
    seen=[]
    def respond(request):
        data=json.loads(request.content);seen.append(request.url.path)
        if request.url.path.endswith('/embeddings'):return httpx.Response(200,json=payload(len(data['input'])))
        passages=json.loads(data['messages'][1]['content'])['passages']
        return httpx.Response(200,json={'model':'synthetic-model','choices':[{'finish_reason':'stop','message':{'role':'assistant',
            'content':json.dumps({'scores':[{'passage_id':p['passage_id'],'score':i} for i,p in enumerate(passages)]})}}],
            'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
    httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
    from naiyue_rag.app import main
    args=['--config',str(root/'app.yaml'),action]
    if action=='query':args+=['--query',' \ncvr_ltv 开关 TC-01 0.5\t','--expected-revision','1']
    if action=='ingest':args+=['--expected-revision','1']
    code=main(args)
    assert code==0
    if action=='query':assert len(seen)==2 and seen[0].endswith('/embeddings') and seen[1].endswith('/chat/completions')
    else:assert seen==[]


SCRIPT='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_core_app import native
native(Path(sys.argv[2]),sys.argv[3])
'''


@pytest.mark.parametrize('action',['query','documents','ingest'])
def test_cli_real_assembly_sdk_and_native_indexes(tmp_path,action):
    (tmp_path/'.env').write_text('NAIYUE_RAG_ZHIPU_API_KEY=SYNTHETIC-NOT-A-KEY\nANONYMIZED_TELEMETRY=false\n')
    ingest(tmp_path,'build','normal');write_config(tmp_path)
    before=(tmp_path/'.env').read_bytes()
    if action=='query':(tmp_path/'source').rename(tmp_path/'source-offline')
    proc=subprocess.run([sys.executable,'-I','-c',SCRIPT,str(ROOT),str(tmp_path),action],cwd=tmp_path,
        env={'HOME':str(tmp_path),'PATH':os.defpath,'OMP_NUM_THREADS':'1'},text=True,capture_output=True,timeout=60)
    assert proc.returncode==0,proc.stderr
    result=json.loads(proc.stdout)
    if action=='query':
        import hashlib
        assert result['schema_version']==2
        assert result['query_sha256']==hashlib.sha256('cvr_ltv 开关 TC-01 0.5'.encode()).hexdigest()
        assert result['raw_query_sha256']==hashlib.sha256(' \ncvr_ltv 开关 TC-01 0.5\t'.encode()).hexdigest()
        assert result['status']=='retrieved' and result['evidence']
        assert result['observations']['rerank']['usage']['total_tokens']==15
        assert 'dense_vector' not in proc.stdout and 'SYNTHETIC-NOT-A-KEY' not in proc.stdout+proc.stderr
    assert (tmp_path/'.env').read_bytes()==before


def test_bad_config_is_safe_json_and_nonzero(tmp_path,capsys):
    from naiyue_rag.app import main
    (tmp_path/'bad.yaml').write_text('SYNTHETIC_PRIVATE: true')
    assert main(['--config',str(tmp_path/'bad.yaml'),'documents'])==2
    captured=capsys.readouterr();result=json.loads(captured.out)
    assert result['error']['code']=='invalid_app_settings'
    assert 'SYNTHETIC_PRIVATE' not in captured.out+captured.err


def test_module_entry_help():
    proc=subprocess.run([sys.executable,'-m','naiyue_rag','--help'],capture_output=True,text=True,timeout=30)
    assert proc.returncode==0 and 'ingest' in proc.stdout and 'query' in proc.stdout


def test_example_paths_pass_the_existing_resource_boundaries():
    from naiyue_rag.app import load_app_settings
    from naiyue_rag.core.storage_settings import load_storage_settings
    from naiyue_rag.core.sparse_encoding_settings import load_sparse_encoding_settings
    cfg=load_app_settings(ROOT/'examples/core-demo/app.example.yaml')
    assert load_storage_settings(cfg['storage']).knowledge_base_id=='core-demo'
    assert load_sparse_encoding_settings(cfg['sparse']).min_chinese_term_length==2
