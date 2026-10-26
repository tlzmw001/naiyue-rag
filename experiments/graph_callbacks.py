"""Persistent request intent/cache, exact vectors and explicit native LLM roles."""
import asyncio
import inspect
import json
import os
from pathlib import Path
import time

from experiments.embedding_probe import KEY_ENV, ProbeError, validate_vectors
from experiments.generation_probe import unique_object
from experiments import graph_transport as transport
from experiments.lightrag_worker import Callbacks as ChunkCallbacks
from experiments.vector_index import digest, read_json, read_rows


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


class Journal:
    def __init__(self,root,config,mode):
        self.root=Path(root);self.config=config;self.mode=mode;self.errors=[];self.tasks={}
        if mode=='live':self.root.mkdir(parents=True,exist_ok=True)
        if self.root.is_symlink():raise ProbeError('cache','cache_path')
        self.events=read_rows(self.root/'events.jsonl','journal') if (self.root/'events.jsonl').exists() else []
        self.start=len(self.events);self.semaphore=asyncio.Semaphore(config['http_concurrency'])
        policy={k:v for k,v in config.items() if k not in transport.PATHS and k not in ['mode','graph_run']}
        self.identity=digest(canonical(policy).encode())

    def append(self,event):
        if self.mode!='live':raise ProbeError('cache','replay_write_forbidden')
        try:
            with (self.root/'events.jsonl').open('a',encoding='utf-8') as handle:
                handle.write(canonical(event)+'\n');handle.flush();os.fsync(handle.fileno())
            self.events.append(event)
        except OSError:raise ProbeError('output','output_error') from None

    def states(self):
        return {e['request_id']:e for e in self.events}

    def summary(self):
        rows=list(self.states().values());new={e['request_id'] for e in self.events[self.start:] if e['status']=='attempted'}
        out={'chat_requests':0,'embedding_requests':0,'embedding_inputs':0,'failed_requests':0,'inflight_requests':0,
             'new_chat_requests':0,'new_embedding_requests':0,'usage_unknown_requests':0,
             'known_usage':{kind:{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0} for kind in ['chat','embedding']}}
        for row in rows:
            kind=row['kind'];out[kind+'_requests']+=1
            if kind=='embedding':out['embedding_inputs']+=row['input_count']
            if row['request_id'] in new:out['new_'+kind+'_requests']+=1
            if row['status']=='failed':out['failed_requests']+=1
            if row['status']=='attempted':out['inflight_requests']+=1
            usage=row.get('usage')
            if usage is None:out['usage_unknown_requests']+=1
            else:
                for key in out['known_usage'][kind]:out['known_usage'][kind][key]+=usage.get(key,0)
        out['estimated_cost_cny']=None;out['provider_billed_cost_cny']=None
        return out

    async def request(self,kind,role,body,send,parse):
        descriptor={'identity':self.identity,'kind':kind,'role':role,'body':body}
        key=digest(canonical(descriptor).encode())
        if key not in self.tasks:self.tasks[key]=asyncio.create_task(self._request(key,descriptor,send,parse))
        task=self.tasks[key]
        try:return await asyncio.shield(task)
        finally:
            if task.done() and self.tasks.get(key) is task:self.tasks.pop(key)

    async def _request(self,key,descriptor,send,parse):
        kind,role=descriptor['kind'],descriptor['role'];cache=self.root/('success-'+key+'.json')
        try:
            if cache.exists():
                if cache.is_symlink():raise ProbeError('cache','cache_path')
                data=read_json(cache,'cache')
                terminal=self.states().get(key,{})
                if terminal.get('status')!='success' or terminal.get('response_sha256')!=data.get('payload_sha256') or \
                        data.get('descriptor')!=descriptor or digest(canonical(data.get('payload')).encode())!=data.get('payload_sha256'):
                    raise ProbeError('cache','provider_cache_mismatch')
                result=parse(data['payload'])
                return await result if inspect.isawaitable(result) else result
            if self.mode!='live':raise ProbeError('cache','provider_cache_miss')
            if key in self.states():raise ProbeError('cache','failed_or_inflight_request')
            async with self.semaphore:
                counts=self.summary()
                if counts['failed_requests'] or counts['inflight_requests'] and any(e['status']=='attempted' and e['request_id'] not in {t for t in self.tasks} for e in self.states().values()):
                    raise ProbeError('request','previous_request_failed')
                if self.errors:raise ProbeError('request','previous_request_failed')
                amount=len(descriptor['body'].get('input',[])) if kind=='embedding' else 1
                if counts[kind+'_requests']>=self.config['max_'+kind+'_requests'] or \
                        (kind=='embedding' and counts['embedding_inputs']+amount>self.config['max_embedding_inputs']):
                    raise ProbeError('request','request_limit')
                event={'request_id':key,'kind':kind,'role':role,'input_count':amount,'status':'attempted',
                       'utc_epoch':time.time(),'usage':None,'http_status':None}
                self.append(event);began=time.monotonic();payload=None
                try:
                    payload=await send()
                    usage=transport.usage_record(payload,kind)
                    result=parse(payload)
                    if inspect.isawaitable(result):result=await result
                    data={'descriptor':descriptor,'payload':payload,'payload_sha256':digest(canonical(payload).encode())}
                    with cache.open('x',encoding='utf-8') as handle:handle.write(canonical(data))
                    self.append({**event,**usage,'status':'success','http_status':200,
                                 'elapsed_ms':round((time.monotonic()-began)*1000,3),'response_sha256':data['payload_sha256']})
                    return result
                except Exception as error:
                    record=error.record() if isinstance(error,ProbeError) else ProbeError('request','unexpected_error').record()
                    usage=transport.usage_record(payload,kind) if isinstance(payload,dict) else {'usage':None,'usage_status':'unknown'}
                    if payload is not None:
                        with (self.root/('failed-response-'+key+'.json')).open('x',encoding='utf-8') as handle:handle.write(canonical(payload))
                    self.append({**event,**usage,'status':'failed','error':record,'http_status':record['http_status'],
                                 'elapsed_ms':round((time.monotonic()-began)*1000,3)})
                    if isinstance(error,ProbeError):raise
                    raise ProbeError('request','unexpected_error') from None
        except ProbeError as error:
            self.errors.append(error.record());raise
        except (OSError,ValueError,TypeError):
            self.errors.append(ProbeError('cache','provider_cache_mismatch').record())
            raise ProbeError('cache','provider_cache_mismatch') from None


class GraphCallbacks(ChunkCallbacks):
    def __init__(self,payload,config,journal,sanitize,tokenizer):
        super().__init__({**payload,'dimensions':config['dimensions']},sanitize)
        self.config=config;self.journal=journal;self.tokenizer=tokenizer
        self.trace.update(llm_roles={},old_vector_hits=0,new_vector_texts=0,callback_errors=[])

    async def model(self,role,prompt,system_prompt=None,history_messages=None,hashing_kv=None,response_format=None,**kwargs):
        try:
            if history_messages or set(kwargs)-{'max_tokens'}:raise ProbeError('callback','unexpected_provider_kwargs')
            stage=role
            if role=='extract':stage='extract_initial' if response_format=={'type':'json_object'} and system_prompt else 'extract_summary'
            body=transport.chat_body(self.config,stage,prompt,system_prompt,response_format)
            if 'max_tokens' in kwargs and kwargs['max_tokens']!=body['max_tokens']:raise ProbeError('callback','unexpected_max_tokens')
            self.trace['llm_calls']+=1;self.trace['llm_roles'][stage]=self.trace['llm_roles'].get(stage,0)+1
            async def send():
                key=os.environ.get(KEY_ENV,'').strip()
                if not key:raise ProbeError('preflight','missing_key')
                return await asyncio.to_thread(transport.send,self.config,'chat',body,key)
            async def parse(payload):
                content,meta=transport.parse_chat(payload,self.config,stage)
                if stage=='extract_initial':
                    from lightrag.operate import _process_json_extraction_result
                    from lightrag.utils import normalize_entity_name
                    data=transport.validate_content(content,stage,self.config)
                    names=[normalize_entity_name(e['name']) for e in data['entities']]
                    if len(set(names))!=len(names):raise ProbeError('protocol','native_normalization_collision')
                    nodes,edges=await _process_json_extraction_result(content,'validation-only',0,'validation-only.md')
                    if sum(len(v) for v in nodes.values())!=len(data['entities']) or sum(len(v) for v in edges.values())!=len(data['relationships']):
                        raise ProbeError('protocol','native_parser_dropped_records')
                return content,meta
            content,_=await self.journal.request('chat',stage,body,send,parse)
            return content
        except ProbeError as error:
            self.trace['callback_errors'].append(error.record());raise

    async def embedding(self,texts,context=None,**kwargs):
        try:
            if context not in ['document','query'] or set(kwargs)-{'_priority'}:raise ProbeError('callback','unknown_embedding_context')
            known=self.payload['vectors' if context=='document' else 'query_vectors']
            hashes=[digest(t.encode()) for t in texts]
            old=[(i,known[h]) for i,h in enumerate(hashes) if h in known]
            missing=[(i,t) for i,t in enumerate(texts) if hashes[i] not in known]
            # Public chunk inputs have registered hashes and cannot acquire replacement embeddings.
            originals={u['input_sha256'] for u in self.payload['units']}
            if context=='document' and any(h in originals and h not in known for h in hashes):
                raise ProbeError('cache','shared_corpus_mismatch')
            vectors=[None]*len(texts)
            for i,v in old:vectors[i]=v
            self.trace['old_vector_hits']+=len(old);self.trace[context+'_texts']+=len(texts)
            self.trace['embedding_batches'].append({'context':context,'input_sha256':hashes})
            size=self.config['batch_size']
            for start in range(0,len(missing),size):
                batch=missing[start:start+size];items=[t for _,t in batch]
                if any(not t.strip() or len(t.encode())>self.config['max_input_utf8_bytes'] or len(self.tokenizer.encode(t))>self.config['max_embedding_tokens'] for t in items):
                    raise ProbeError('embedding','embedding_input_too_large')
                body={'model':self.config['embedding_model'],'dimensions':self.config['dimensions'],'input':items}
                async def send():
                    key=os.environ.get(KEY_ENV,'').strip()
                    if not key:raise ProbeError('preflight','missing_key')
                    return await asyncio.to_thread(transport.send,self.config,'embedding',body,key)
                values=await self.journal.request('embedding',context,body,send,
                    lambda p:validate_vectors(p,len(items),self.config['dimensions'],self.config['embedding_model']))
                self.trace['new_vector_texts']+=len(items)
                for (i,_),v in zip(batch,values,strict=True):vectors[i]=v
            return self.np.asarray(vectors,dtype=self.np.float64).reshape(len(texts),self.config['dimensions'])
        except ProbeError as error:
            self.trace['callback_errors'].append(error.record());raise
