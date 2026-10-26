"""Spec0009 strict native formats and bounded standard HTTP; no provider SDK."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from experiments.embedding_probe import APPROVED_ENDPOINT, NoRedirect, ProbeError, validate_usage, validate_vectors
from experiments.generation_probe import APPROVED_ENDPOINT as CHAT_ENDPOINT, generation_usage, unique_object

FIXED = {'sdk_version':'1.5.7','chat_endpoint':CHAT_ENDPOINT,'embedding_endpoint':APPROVED_ENDPOINT,
         'chat_model':'glm-5.2','embedding_model':'embedding-3','tokenizer_encoding':'o200k_base',
         'language':'Chinese','kg_chunk_pick_method':'VECTOR'}
LIMITS = {'dimensions':2048,'candidate_k':20,'max_context_chars':8000,'max_total_tokens':32768,
          'max_entity_tokens':6000,'max_relation_tokens':6000,'entity_extract_max_records':40,
          'entity_extract_max_entities':20,'force_llm_summary_on_merge':8,'summary_context_size':12000,
          'summary_max_tokens':1200,'summary_length_recommended':600,'related_chunk_number':5,
          'max_source_ids_per_entity':128,'max_source_ids_per_relation':128,'max_file_paths':64,
          'extract_initial_max_tokens':4096,'extract_summary_max_tokens':1200,'keyword_max_tokens':1024,
          'timeout_seconds':60,'role_timeout_seconds':70,'deadline_seconds':3600,'pilot_timeout_seconds':120,
          'history_build_timeout_seconds':1800,'single_build_timeout_seconds':600,'query_timeout_seconds':300,
          'max_chat_requests':160,'max_embedding_requests':128,'max_embedding_inputs':2048,
          'http_concurrency':2,'batch_size':16,'max_embedding_tokens':3072,'max_input_utf8_bytes':12288,
          'chat_max_response_bytes':1048576,'embedding_max_response_bytes':4194304}
PATHS = ['dataset','corpus_run','tasks','vector_run','b0_run','a2_run','runtime_python','runtime_lock','output_root','tokenizer_cache']


def _validate_shared(config):
    try:
        expected=set(FIXED)|set(LIMITS)|set(PATHS)|{'mode','graph_run','entity_extraction_use_json','entity_extract_max_gleaning','cosine_threshold'}
        if set(config)!=expected:raise ValueError('fields')
        if any(config[k]!=v for k,v in FIXED.items()):raise ValueError('target')
        if config['mode'] not in ['live','replay']:
            raise ValueError('mode')
        if any(not isinstance(config[k],str) or not config[k].strip() for k in PATHS):raise ValueError('path')
        for key,cap in LIMITS.items():
            if type(config[key]) is not int or not 0<config[key]<=cap:raise ValueError('limit')
        if config['dimensions']!=2048 or config['candidate_k']!=20 or config['max_context_chars']!=8000:
            raise ValueError('shared policy')
        if config['entity_extraction_use_json'] is not True or type(config['entity_extract_max_gleaning']) is not int or config['entity_extract_max_gleaning']!=0:
            raise ValueError('graph policy')
        if type(config['cosine_threshold']) not in (int,float) or config['cosine_threshold']!=-1:raise ValueError('threshold')
    except (ValueError,KeyError,TypeError):raise ProbeError('config','invalid_graph_config') from None


def validate_config(config):
    _validate_shared(config)
    if config['mode']=='replay' and (not isinstance(config['graph_run'],str) or not config['graph_run'].strip()):
        raise ProbeError('config','invalid_graph_config')


def validate_worker_config(config):
    _validate_shared(config)


def chat_body(config, role, prompt, system_prompt, response_format):
    if role not in ['extract_initial','extract_summary','keyword'] or not isinstance(prompt,str) or not prompt.strip():
        raise ProbeError('callback','unexpected_llm_call')
    if role=='extract_initial' and (not system_prompt or response_format!={'type':'json_object'}):
        raise ProbeError('callback','invalid_native_protocol')
    if role=='keyword' and (system_prompt or response_format!={'type':'json_object'}):
        raise ProbeError('callback','invalid_native_protocol')
    if role=='extract_summary' and (system_prompt or response_format is not None):
        raise ProbeError('callback','invalid_native_protocol')
    messages=[]
    if system_prompt:messages.append({'role':'system','content':system_prompt})
    messages.append({'role':'user','content':prompt})
    body={'model':config['chat_model'],'messages':messages,'max_tokens':config[role+'_max_tokens'],
          'thinking':{'type':'disabled'},'stream':False}
    if response_format is not None:body['response_format']=response_format
    return body


def validate_content(text, role, config):
    try:
        if not isinstance(text,str) or not text.strip():raise ValueError('empty')
        if role=='extract_summary':return text
        data=json.loads(text,object_pairs_hook=unique_object)
        if role=='keyword':
            if set(data)!={'high_level_keywords','low_level_keywords'}:raise ValueError('fields')
            for values in data.values():
                if not isinstance(values,list) or any(not isinstance(v,str) or not v.strip() for v in values):raise ValueError('keywords')
            return data
        if role!='extract_initial' or set(data)!={'entities','relationships'}:raise ValueError('fields')
        entities,relations=data['entities'],data['relationships']
        if not isinstance(entities,list) or not isinstance(relations,list) or len(entities)>config['entity_extract_max_entities'] or len(entities)+len(relations)>config['entity_extract_max_records']:
            raise ValueError('count')
        names=set()
        for entity in entities:
            if not isinstance(entity,dict) or set(entity)!={'name','type','description'} or any(not isinstance(v,str) or not v.strip() for v in entity.values()):raise ValueError('entity')
            name=entity['name'].strip()
            if name in names:raise ValueError('duplicate')
            names.add(name)
        for rel in relations:
            if not isinstance(rel,dict) or set(rel)!={'source','target','keywords','description'} or any(not isinstance(v,str) or not v.strip() for v in rel.values()):raise ValueError('relation')
            if rel['source'].strip() not in names or rel['target'].strip() not in names or rel['source'].strip()==rel['target'].strip():raise ValueError('endpoint')
        return data
    except (ValueError,TypeError,KeyError):raise ProbeError('protocol','invalid_native_content') from None


def usage_record(payload,kind):
    try:
        value=generation_usage(payload.get('usage')) if kind=='chat' else validate_usage(payload.get('usage'))
        return {'usage':value,'usage_status':'known'}
    except ProbeError:return {'usage':None,'usage_status':'unknown'}


def parse_chat(payload,config,role):
    meta=usage_record(payload,'chat')
    try:
        choices=payload['choices']
        if payload['model']!=config['chat_model'] or not isinstance(choices,list) or len(choices)!=1:raise ValueError('identity')
        choice=choices[0];msg=choice['message']
        if choice['index']!=0 or choice['finish_reason']!='stop' or msg['role']!='assistant' or msg.get('tool_calls') or msg.get('reasoning_content'):
            raise ValueError('termination')
        text=msg['content'];validate_content(text,role,config)
        return text,{**meta,'response_model':payload['model'],'finish_reason':choice['finish_reason']}
    except ProbeError:raise
    except (KeyError,ValueError,TypeError):raise ProbeError('response','invalid_completion') from None


def send(config,kind,body,key):
    if kind not in ['chat','embedding'] or not key:raise ProbeError('preflight','missing_key')
    endpoint=config[kind+'_endpoint']
    if endpoint!=(CHAT_ENDPOINT if kind=='chat' else APPROVED_ENDPOINT):raise ProbeError('config','invalid_endpoint')
    model=config[kind+'_model']
    if body.get('model')!=model:raise ProbeError('config','invalid_model')
    cap=config[kind+'_max_response_bytes']
    request=Request(endpoint,data=json.dumps(body,ensure_ascii=False,allow_nan=False).encode(),method='POST',
                    headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
    try:
        with build_opener(NoRedirect()).open(request,timeout=config['timeout_seconds']) as reply:
            if reply.status!=200:raise ProbeError('http','http_error',reply.status)
            raw=reply.read(cap+1)
        if len(raw)>cap:raise ProbeError('response','response_too_large',200)
        if key.encode() in raw:raise ProbeError('response','secret_in_response',200)
        try:payload=json.loads(raw,object_pairs_hook=unique_object)
        except (ValueError,UnicodeError):raise ProbeError('response','invalid_json',200) from None
        if key in json.dumps(payload,ensure_ascii=False):raise ProbeError('response','secret_in_response',200)
        return payload
    except HTTPError as error:raise ProbeError('http','http_error',error.code) from None
    except (TimeoutError,URLError,OSError):raise ProbeError('http','transport_error') from None
