import copy
import importlib
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest


def settings(tmp_path):
    root=Path(__file__).resolve().parents[1]
    return {'mode':'live','graph_run':None,'dataset':str(root/'examples/mock-v1'),
            'corpus_run':str(root/'data/experiments/common-evidence-corpus/20261010T021859Z-647de42b'),
            'tasks':str(root/'examples/mock-v1/tasks.json'),
            'vector_run':str(root/'data/experiments/a1-vector-baseline/20261010T031953Z-52cfda4e'),
            'b0_run':str(root/'data/experiments/b0-lightrag-naive/20261010T082212Z-fae04e9e'),
            'a2_run':str(root/'data/experiments/a2-bm25-rrf/20261010T054002Z-99569e55'),
            'runtime_python':str(root/'.venv-lightrag/bin/python'),'runtime_lock':str(root/'requirements-lightrag-runtime.lock.txt'),
            'sdk_version':'1.5.7','chat_endpoint':'https://open.bigmodel.cn/api/paas/v4/chat/completions',
            'embedding_endpoint':'https://open.bigmodel.cn/api/paas/v4/embeddings','chat_model':'glm-5.2',
            'embedding_model':'embedding-3','dimensions':2048,'output_root':str(tmp_path/'b1'),
            'tokenizer_cache':str(root/'data/runtime/lightrag/o200k-cache'),'tokenizer_encoding':'o200k_base',
            'candidate_k':20,'max_context_chars':8000,'max_total_tokens':32768,'max_entity_tokens':6000,'max_relation_tokens':6000,
            'entity_extraction_use_json':True,'entity_extract_max_gleaning':0,'entity_extract_max_records':40,
            'entity_extract_max_entities':20,'force_llm_summary_on_merge':8,'summary_context_size':12000,
            'summary_max_tokens':1200,'summary_length_recommended':600,'kg_chunk_pick_method':'VECTOR',
            'related_chunk_number':5,'max_source_ids_per_entity':128,'max_source_ids_per_relation':128,'max_file_paths':64,
            'language':'Chinese','cosine_threshold':-1.0,'extract_initial_max_tokens':4096,
            'extract_summary_max_tokens':1200,'keyword_max_tokens':1024,'timeout_seconds':60,
            'role_timeout_seconds':70,'deadline_seconds':3600,'pilot_timeout_seconds':120,
            'history_build_timeout_seconds':1800,'single_build_timeout_seconds':600,'query_timeout_seconds':300,
            'max_chat_requests':160,'max_embedding_requests':128,'max_embedding_inputs':2048,
            'http_concurrency':2,'batch_size':16,'max_embedding_tokens':3072,'max_input_utf8_bytes':12288,
            'chat_max_response_bytes':1048576,'embedding_max_response_bytes':4194304}


def extraction():
    return {'entities':[{'name':'A','type':'CONCEPT','description':'synthetic A'},
                        {'name':'B','type':'CONCEPT','description':'synthetic B'}],
            'relationships':[{'source':'A','target':'B','keywords':'related','description':'synthetic A relates B'}]}


def completion(content=None):
    return {'model':'glm-5.2','choices':[{'index':0,'finish_reason':'stop',
              'message':{'role':'assistant','content':content or json.dumps(extraction()),'reasoning_content':''}}],
            'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}


@pytest.fixture
def mod():return importlib.import_module('experiments.graph_transport')


def test_native_request_formats_and_no_hidden_provider_arguments(mod,tmp_path):
    cfg=settings(tmp_path)
    initial=mod.chat_body(cfg,'extract_initial','user','system',{'type':'json_object'})
    assert initial['max_tokens']==4096 and initial['thinking']=={'type':'disabled'}
    assert initial['messages']==[{'role':'system','content':'system'},{'role':'user','content':'user'}]
    summary=mod.chat_body(cfg,'extract_summary','summary',None,None)
    assert summary['max_tokens']==1200 and 'response_format' not in summary
    assert 'tools' not in initial and 'temperature' not in initial and 'reasoning_effort' not in initial
    with pytest.raises(mod.ProbeError):mod.chat_body(cfg,'query','x',None,None)


@pytest.mark.parametrize('fault',['extra','duplicate','dangling','self','empty','type','records'])
def test_strict_native_json_rejects_bad_records(mod,tmp_path,fault):
    data=extraction()
    if fault=='extra':data['relations']=[]
    elif fault=='duplicate':data['entities'].append(dict(data['entities'][0]))
    elif fault=='dangling':data['relationships'][0]['target']='C'
    elif fault=='self':data['relationships'][0]['target']='A'
    elif fault=='empty':data['entities'][0]['description']=''
    elif fault=='type':data['relationships'][0]['keywords']=[]
    else:data['entities']*=21
    with pytest.raises(mod.ProbeError):mod.validate_content(json.dumps(data),'extract_initial',settings(tmp_path))
    with pytest.raises(mod.ProbeError):mod.validate_content('{"entities":[],"entities":[],"relationships":[]}','extract_initial',settings(tmp_path))


def test_empty_extraction_keywords_and_unknown_usage_are_separate(mod,tmp_path):
    cfg=settings(tmp_path)
    assert mod.validate_content('{"entities":[],"relationships":[]}','extract_initial',cfg)['entities']==[]
    assert mod.validate_content('{"high_level_keywords":[],"low_level_keywords":[]}','keyword',cfg)['low_level_keywords']==[]
    response=completion();response.pop('usage')
    text,meta=mod.parse_chat(response,cfg,'extract_initial')
    assert text and meta['usage'] is None and meta['usage_status']=='unknown'


@pytest.mark.parametrize('fault',['model','length','reasoning','tools','role','empty'])
def test_bad_completion_preserves_known_usage_in_journal_layer(mod,tmp_path,fault):
    response=completion();choice=response['choices'][0];msg=choice['message']
    if fault=='model':response['model']='other'
    elif fault=='length':choice['finish_reason']='length'
    elif fault=='reasoning':msg['reasoning_content']='unexpected'
    elif fault=='tools':msg['tool_calls']=[{}]
    elif fault=='role':msg['role']='user'
    else:msg['content']=''
    with pytest.raises(mod.ProbeError):mod.parse_chat(response,settings(tmp_path),'extract_initial')


def test_http_target_secret_guard_and_zero_retry(mod,tmp_path,monkeypatch):
    cfg=settings(tmp_path);calls=[]
    class Reply:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,n):return json.dumps(completion()).encode()
    class Opener:
        def open(self,request,timeout):
            calls.append(request)
            assert request.get_header('Authorization')=='Bearer test-sentinel'
            return Reply()
    monkeypatch.setattr(mod,'build_opener',lambda *a:Opener())
    body=mod.chat_body(cfg,'extract_initial','x','s',{'type':'json_object'})
    assert mod.send(cfg,'chat',body,'test-sentinel')['model']=='glm-5.2'
    assert len(calls)==1
    def failing(*a,**k):calls.append('failure');raise HTTPError(cfg['chat_endpoint'],429,'private',{},None)
    monkeypatch.setattr(Opener,'open',failing)
    with pytest.raises(mod.ProbeError,match='http_error'):mod.send(cfg,'chat',body,'test-sentinel')
    assert len(calls)==2
    with pytest.raises(mod.ProbeError):mod.send(dict(cfg,chat_endpoint='https://example.com'), 'chat',body,'test-sentinel')


@pytest.mark.parametrize('value',[True,0,-1])
def test_invalid_count_config_rejected(mod,tmp_path,value):
    cfg=settings(tmp_path);cfg['max_chat_requests']=value
    with pytest.raises(mod.ProbeError):mod.validate_config(cfg)
