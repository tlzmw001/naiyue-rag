import copy
import importlib
import json
from pathlib import Path
import subprocess

import pytest
from test_graph_transport import settings


def payload(tmp_path):
    from test_lightrag_mapping import inputs
    from experiments.lightrag_mapping import make_payload
    corpus,index,queries=inputs(tmp_path);cfg=settings(tmp_path)
    return {'config':cfg,'payload':make_payload(corpus,index,[queries[2]]),'action':'build',
            'working_dir':str(tmp_path/'native'),'cache_root':str(tmp_path/'cache')}


def fake_run(job,cwd):
    from experiments.lightrag_runtime import worker_environment
    root=Path(__file__).resolve().parents[1];env=worker_environment(job['config']['tokenizer_cache'])
    env['NAIYUE_RAG_ZHIPU_API_KEY']='test-sentinel'
    script='''import json,sys,asyncio,socket
from experiments.graph_worker import execute
from experiments import graph_transport as t
from experiments.lightrag_runtime import offline_guard
def fake(config,kind,body,key):
 if kind=="chat":
  if body.get("response_format"):
   if "system" in [m["role"] for m in body["messages"]]:
    content=json.dumps({"entities":[{"name":"A","type":"CONCEPT","description":"synthetic A"},{"name":"B","type":"CONCEPT","description":"synthetic B"}],"relationships":[{"source":"A","target":"B","keywords":"related","description":"synthetic A relates B"}]})
   else:content=json.dumps({"high_level_keywords":["related"],"low_level_keywords":["A"]})
  else:content="synthetic merged description"
  return {"model":"glm-5.2","choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":content}}],"usage":{"prompt_tokens":10,"completion_tokens":20,"total_tokens":30}}
 return {"model":"embedding-3","data":[{"index":i,"embedding":[1.0,0.0]+[0.0]*2046} for i,_ in enumerate(body["input"])],"usage":{"prompt_tokens":len(body["input"]),"total_tokens":len(body["input"])}}
t.send=fake
job=json.load(sys.stdin)
with offline_guard([0]): result=asyncio.run(execute(job))
print(json.dumps(result,ensure_ascii=False))'''
    cwd.mkdir(exist_ok=True)
    (cwd/'.env').write_text('B1_DOTENV_SENTINEL=must_not_load\n')
    p=subprocess.run([str(root/'.venv-lightrag/bin/python'),'-c',script],input=json.dumps(job),
                     text=True,capture_output=True,cwd=cwd,env=env,timeout=60)
    assert p.returncode==0,p.stderr[-3000:]
    return json.loads(p.stdout)


def test_actual_sdk_graph_store_scope_and_reloaded_query_with_fake_service(tmp_path):
    job=payload(tmp_path);built=fake_run(job,tmp_path/'build-worker')
    assert built['status']=='complete' and built['audit']['chunk_count']==10
    assert built['audit']['graph_nodes']==2 and built['audit']['graph_edges']==1
    assert built['audit']['source_ids_valid'] is True and built['dotenv_sentinel_loaded'] is False
    queried=fake_run(dict(job,action='query'),tmp_path/'query-worker')
    assert queried['status']=='complete' and queried['queries'][0]['mix']['data']['chunks']
    assert all(c['file_path']=='doc-MOCK-CASE-001.md' for c in queried['queries'][0]['mix']['data']['chunks'])
    replay=fake_run(dict(job,action='query',config=dict(job['config'],mode='replay')),tmp_path/'replay-worker')
    assert replay['queries']==queried['queries']


@pytest.mark.parametrize('fault',['unknown','partial','scope','duplicate'])
def test_native_order_mapping_rejects_bad_evidence(tmp_path,fault):
    mod=importlib.import_module('experiments.graph_worker');job=payload(tmp_path);unit=job['payload']['units'][0]
    chunks=[{'chunk_id':unit['native_id'],'content':unit['content'],'file_path':unit['native_file_path']}]
    if fault=='unknown':chunks[0]['chunk_id']='absent'
    elif fault=='partial':chunks[0]['content']='part'
    elif fault=='scope':chunks[0]['file_path']='other'
    else:chunks.append(copy.deepcopy(chunks[0]))
    with pytest.raises(mod.ProbeError):mod.map_native(job['payload'],chunks)


def test_native_order_mapping_preserves_score_unknown_and_whole_case(tmp_path):
    mod=importlib.import_module('experiments.graph_worker');job=payload(tmp_path)
    unit=next(u for u in job['payload']['units'] if u['kind']=='test_case')
    row=mod.map_native(job['payload'],[{'chunk_id':unit['native_id'],'content':unit['content'],'file_path':unit['native_file_path']}])[0]
    assert row['score'] is None and row['score_kind']=='native_order' and row['body']==unit['body']
    from experiments.vector_index import pack_evidence
    packed=pack_evidence([row],8000)
    assert packed['context_text'].startswith('[graph_mix rank=01 order=native]   \n')
    assert len(packed['context_text'])==36+unit['rendered_characters']


def test_vector_audit_keeps_each_successful_response_for_same_text(tmp_path):
    import asyncio,hashlib
    from experiments.graph_callbacks import Journal
    mod=importlib.import_module('experiments.graph_worker');cfg=settings(tmp_path)
    journal=Journal(tmp_path/'cache',cfg,'live')
    async def scenario():
        for inputs,coordinate in [(['x'],0),(['y','x'],1)]:
            values=[0.0]*2048;values[coordinate]=1.0
            async def send():
                return {'model':'embedding-3','data':[{'index':i,'embedding':values} for i in range(len(inputs))],
                        'usage':{'prompt_tokens':len(inputs),'total_tokens':len(inputs)}}
            await journal.request('embedding','document',{'input':inputs},send,lambda p:p)
    asyncio.run(scenario())
    values=mod.vector_pool({'vectors':{}},journal)[hashlib.sha256(b'x').hexdigest()]
    assert len(values)==2 and {tuple(v[:2]) for record,v in values}=={(1.0,0.0),(0.0,1.0)}
