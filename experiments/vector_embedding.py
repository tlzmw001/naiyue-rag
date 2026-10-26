"""One bounded batch job with observable usage and no automatic retry."""
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from experiments.embedding_probe import APPROVED_ENDPOINT, KEY_ENV, NoRedirect, ProbeError, validate_usage, validate_vectors
from experiments.generation_probe import unique_object
from experiments.vector_eval import load_queries
from experiments.vector_index import digest, load_corpus, make_index_text, write_index


def validate_config(config):
    try:
        if config['endpoint'] != APPROVED_ENDPOINT or config['model'] != 'embedding-3' or config['dimensions'] != 2048:
            raise ValueError('target')
        for name, cap in [('dimensions',2048),('batch_size',16),('max_inputs',56),('max_requests',5),
                          ('timeout_seconds',30),('deadline_seconds',180),('max_response_bytes',4194304),
                          ('max_input_utf8_bytes',3072),('candidate_k',20),('max_context_chars',8000)]:
            if type(config[name]) is not int or not 0 < config[name] <= cap:
                raise ValueError('bound')
        price = config['unit_price_cny_per_million']
        if type(price) not in (int,float) or not math.isfinite(price) or price < 0:
            raise ValueError('price')
        if config['mode'] not in ['live','replay']:
            raise ValueError('mode')
        for name in ['dataset','corpus_run','tasks','output_root']:
            if not isinstance(config[name],str) or not config[name]:
                raise ValueError('path')
        if config['mode']=='replay' and (not isinstance(config.get('replay_run'),str) or not config['replay_run']):
            raise ValueError('replay')
    except (ValueError,TypeError,KeyError):
        raise ProbeError('preflight','invalid_config') from None


def plan_batches(config, corpus, queries):
    texts = [make_index_text(u) for u in corpus['units']]
    query_texts = [q['query'] for q in queries]
    if len(texts)+len(query_texts)>config['max_inputs']:
        raise ProbeError('preflight','too_many_inputs')
    if any(not t.strip() or len(t.encode())>config['max_input_utf8_bytes'] for t in texts+query_texts):
        raise ProbeError('preflight','input_too_large')
    size=config['batch_size']
    batches=[(stage,items[i:i+size]) for stage,items in [('documents',texts),('queries',query_texts)]
             for i in range(0,len(items),size)]
    if len(batches)>config['max_requests']:
        raise ProbeError('preflight','too_many_requests')
    return batches


def send_batch(config,texts,key):
    if not isinstance(texts,list) or not 1<=len(texts)<=config['batch_size'] or any(
            not isinstance(t,str) or not t.strip() or len(t.encode())>config['max_input_utf8_bytes'] for t in texts):
        raise ProbeError('preflight','invalid_input')
    body=json.dumps({'model':config['model'],'dimensions':config['dimensions'],'input':texts},ensure_ascii=False).encode()
    request=Request(config['endpoint'],data=body,method='POST',headers={
        'Content-Type':'application/json','Authorization':'Bearer '+key})
    try:
        with build_opener(NoRedirect()).open(request,timeout=config['timeout_seconds']) as reply:
            if reply.status!=200:
                raise ProbeError('http','http_error',reply.status)
            raw=reply.read(config['max_response_bytes']+1)
        if len(raw)>config['max_response_bytes']:
            raise ProbeError('response','response_too_large',200)
        if key.encode() in raw:
            raise ProbeError('response','secret_in_response',200)
        try:
            payload=json.loads(raw,object_pairs_hook=unique_object)
        except (ValueError,UnicodeError):
            raise ProbeError('response','invalid_json',200) from None
        if key in json.dumps(payload,ensure_ascii=False):
            raise ProbeError('response','secret_in_response',200)
        return payload
    except HTTPError as error:
        raise ProbeError('http','http_error',error.code) from None
    except (TimeoutError,URLError,OSError):
        raise ProbeError('http','transport_error') from None


def initial_state(config):
    return {'schema_version':1,'status':'running','config':dict(config),'attempt_count':0,'requests':[],
            'known_estimated_cost_cny':0.0,'estimated_cost_cny':0.0,'provider_billed_cost_cny':None,
            'sanitized_error':None,'elapsed_ms':None}


def update_cost(state):
    known=sum(r['usage']['prompt_tokens'] for r in state['requests'] if r.get('usage') is not None)
    state['known_estimated_cost_cny']=known*state['config']['unit_price_cny_per_million']/1e6
    state['estimated_cost_cny']=state['known_estimated_cost_cny'] if all(r.get('usage') is not None
                                       for r in state['requests']) else None


def run_worker(job,emit):
    config=job['config'];state=initial_state(config);started=time.monotonic()
    try:
        validate_config(config)
        corpus=load_corpus(config['corpus_run'],config['dataset'])
        if corpus['fingerprint']!=job['fingerprint']:
            raise ProbeError('corpus','corpus_changed')
        queries=load_queries(config['tasks'],corpus)
        batches=plan_batches(config,corpus,queries)
        key=os.environ.get(KEY_ENV,'').strip()
        if not key:
            raise ProbeError('preflight','missing_key')
        all_vectors={'documents':[],'queries':[]}
        for stage,texts in batches:
            record={'request_number':len(state['requests'])+1,'stage':stage,'input_count':len(texts),
                    'input_hashes':[digest(t.encode()) for t in texts],'usage':None,'http_status':None}
            state['requests'].append(record);state['attempt_count']+=1;update_cost(state)
            emit(json.loads(json.dumps(state)))
            began=time.monotonic()
            payload=send_batch(config,texts,key)
            record['http_status']=200
            if not isinstance(payload,dict):
                raise ProbeError('response','invalid_vectors',200)
            if key in json.dumps(payload,ensure_ascii=False):
                raise ProbeError('response','secret_in_response',200)
            record['usage']=validate_usage(payload.get('usage'));update_cost(state)
            emit(json.loads(json.dumps(state)))
            vectors=validate_vectors(payload,len(texts),config['dimensions'],config['model'])
            all_vectors[stage].extend(vectors)
            record['elapsed_ms']=round((time.monotonic()-began)*1000,3)
            emit(json.loads(json.dumps(state)))
        write_index(job['folder'],corpus,queries,all_vectors['documents'],all_vectors['queries'],config)
        state['status']='complete'
    except ProbeError as error:
        state['status']='error';state['sanitized_error']=error.record()
        if state['requests'] and error.http_status is not None:
            state['requests'][-1]['http_status']=error.http_status
    except Exception:
        state['status']='error';state['sanitized_error']=ProbeError('worker','unexpected_error').record()
    update_cost(state);state['elapsed_ms']=round((time.monotonic()-started)*1000,3)
    return state


def supervise(job,started):
    config=job['config'];state=initial_state(config)
    if config['deadline_seconds']-(time.monotonic()-started)<=0:
        state.update(status='error',sanitized_error=ProbeError('deadline','deadline_exceeded').record())
        return state
    try:
        child=subprocess.Popen([sys.executable,'-m','experiments.vector_probe','--worker'],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                               text=True,cwd=Path(__file__).resolve().parents[1],env=dict(os.environ))
    except OSError:
        raise ProbeError('worker','spawn_error') from None
    timed_out=False
    try:
        remaining=config['deadline_seconds']-(time.monotonic()-started)
        if remaining<=0:
            raise subprocess.TimeoutExpired('worker',0)
        output,_=child.communicate(input=json.dumps(job),timeout=remaining)
    except subprocess.TimeoutExpired:
        timed_out=True;child.kill();output,_=child.communicate()
    final=False
    for line in output.splitlines():
        try:
            event=json.loads(line)
            if event['event'] not in ['checkpoint','result'] or not isinstance(event['summary'],dict):
                raise ValueError('event')
            state=event['summary'];final=event['event']=='result'
        except (ValueError,TypeError,KeyError):
            state.update(status='error',sanitized_error=ProbeError('worker','invalid_worker_output').record())
            return state
    if timed_out or not final or child.returncode not in (0,2):
        state.update(status='error',sanitized_error=ProbeError('deadline' if timed_out else 'worker',
                     'deadline_exceeded' if timed_out else 'worker_failed').record())
    update_cost(state)
    return state
