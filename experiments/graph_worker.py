"""Isolated native graph lifecycle, provenance and original-evidence mapping."""
import asyncio
from contextlib import redirect_stdout
import json
import logging
import os
from pathlib import Path
import sys
import time

from experiments.embedding_probe import ProbeError
from experiments.graph_callbacks import GraphCallbacks, Journal, canonical
from experiments.graph_transport import validate_worker_config, validate_vectors
from experiments.lightrag_runtime import verify_runtime, check_tokenizer, offline_guard
from experiments.vector_index import digest, read_json


def map_native(payload,chunks):
    units={u['native_id']:u for u in payload['units']};seen=set();rows=[]
    try:
        if len(chunks)>20:raise ValueError('count')
        for i,chunk in enumerate(chunks,1):
            key=chunk['chunk_id'];unit=units[key]
            if key in seen or chunk['content']!=unit['content'] or chunk['file_path']!=unit['native_file_path']:raise ValueError('native source')
            seen.add(key)
            rows.append(dict(unit,rank=i,score=None,score_kind='native_order',retrieval_method='graph_mix',
                             retrieval_info={'native_chunk_id':key,'native_rank':i,'score_kind':'native_order'}))
        return rows
    except (KeyError,ValueError,TypeError):raise ProbeError('query','native_query_mismatch') from None


class Events(logging.Handler):
    def __init__(self):super().__init__();self.counts={}
    def emit(self,record):
        message=record.getMessage()
        for needle,kind in [('falling back','native_fallback'),('fallback to','native_fallback'),
                            ('VDB content truncated','derived_text_truncated'),('Failed to batch pre-compute','embedding_batch_fallback')]:
            if needle in message:self.counts[kind]=self.counts.get(kind,0)+1


def vector_pool(payload,journal):
    values={key:[('a1-cache',vector)] for key,vector in payload['vectors'].items()}
    for path in journal.root.glob('success-*.json'):
        data=read_json(path,'cache');descriptor=data['descriptor'];response=data['payload']
        if data['payload_sha256']!=digest(canonical(response).encode()):raise ProbeError('cache','provider_cache_mismatch')
        if descriptor['kind']=='embedding' and descriptor['role']=='document':
            texts=descriptor['body']['input']
            vectors=validate_vectors(response,len(texts),journal.config['dimensions'],journal.config['embedding_model'])
            for text,vector in zip(texts,vectors,strict=True):values.setdefault(digest(text.encode()),[]).append((path.name,vector))
    return values


async def audit(rag,payload,journal,sanitize):
    import numpy as np
    ids={u['native_id']:u for u in payload['units']};docs={d['native_id']:d for d in payload['documents']}
    if set(rag.text_chunks._data)!=set(ids) or set(rag.full_docs._data)!=set(docs) or set(rag.doc_status._data)!=set(docs):
        raise ProbeError('storage','shared_corpus_mismatch')
    for key,unit in ids.items():
        row=await rag.text_chunks.get_by_id(key)
        if row['content']!=unit['content'] or row['full_doc_id']!='doc-'+unit['document_id'] or row['file_path']!=unit['native_file_path']:
            raise ProbeError('storage','shared_corpus_mismatch')
    for key,doc in docs.items():
        status=(await rag.doc_status.get_by_ids([key]))[0];meta=status['metadata']
        expected={u['native_id'] for u in payload['units'] if u['document_id']==doc['document_id']}
        if status['status']!='processed' or meta.get('chunk_method')!='custom_chunking_func' or meta.get('skip_kg') or meta.get('hard_fallback_split') or set(status['chunks_list'])!=expected:
            raise ProbeError('storage','native_document_mismatch')
        source=await rag.full_docs.get_by_id(key)
        if source['content']!=sanitize(doc['content']):raise ProbeError('storage','native_document_mismatch')
    def check_sources(row):
        sources=row.get('source_id','').split('<SEP>')
        if not sources or any(s not in ids for s in sources):raise ProbeError('storage','graph_source_mismatch')
        paths=set(row.get('file_path','').split('<SEP>'))
        if paths!={ids[s]['native_file_path'] for s in sources}:raise ProbeError('storage','graph_path_mismatch')
    graph=rag.chunk_entity_relation_graph._graph
    for _,row in graph.nodes(data=True):check_sources(row)
    for _,_,row in graph.edges(data=True):check_sources(row)
    if not graph.number_of_nodes() or not graph.number_of_edges():raise ProbeError('graph','no_graph_signal')
    for store in [rag.entity_chunks,rag.relation_chunks]:
        for row in store._data.values():
            if not row.get('chunk_ids') or any(s not in ids for s in row['chunk_ids']) or row['count']!=len(row['chunk_ids']):
                raise ProbeError('storage','graph_anchor_mismatch')
    if not rag.entity_chunks._data or not rag.relation_chunks._data or not set(rag.full_entities._data)<=set(docs) or not set(rag.full_relations._data)<=set(docs):
        raise ProbeError('storage','graph_anchor_mismatch')
    vectors=vector_pool(payload,journal);counts={};error=0.;bindings=[]
    for name,store in [('chunks',rag.chunks_vdb),('entities',rag.entities_vdb),('relationships',rag.relationships_vdb)]:
        native=store._client._NanoVectorDB__storage;matrix=native['matrix'];rows=native['data'];counts[name]=len(rows)
        if matrix.shape!=(len(rows),journal.config['dimensions']) or matrix.dtype!=np.float32 or not np.isfinite(matrix).all():
            raise ProbeError('storage','native_vector_mismatch')
        if name=='chunks' and {r['__id__'] for r in rows}!=set(ids):raise ProbeError('storage','shared_corpus_mismatch')
        for i,row in enumerate(rows):
            key=digest(row['content'].encode())
            if key not in vectors:raise ProbeError('storage','unknown_native_vector_input')
            matches=[]
            for record,value in vectors[key]:
                value=np.asarray(value,dtype=np.float64);expected=(value/np.linalg.norm(value)).astype(np.float32)
                if np.allclose(matrix[i],expected,rtol=1e-6,atol=1e-8):matches.append((record,float(np.max(np.abs(matrix[i]-expected)))))
            if not matches:raise ProbeError('storage','native_vector_mismatch')
            error=max(error,min(difference for _,difference in matches))
            bindings.append({'namespace':name,'native_id':row['__id__'],'input_sha256':key,'matching_records':[record for record,_ in matches]})
            if name!='chunks':check_sources(row)
    if counts['entities']!=graph.number_of_nodes() or counts['relationships']!=graph.number_of_edges():
        raise ProbeError('storage','graph_vector_count_mismatch')
    return {'chunk_count':len(ids),'document_count':len(docs),'graph_nodes':graph.number_of_nodes(),
            'graph_edges':graph.number_of_edges(),'source_ids_valid':True,'vector_counts':counts,'max_vector_error':error,
            'anchor_counts':{k:len(getattr(rag,k)._data) for k in ['full_entities','full_relations','entity_chunks','relation_chunks']},
            'native_cache_entries':len(rag.llm_response_cache._data),'vector_bindings':bindings}


async def execute(job):
    cfg=job['config'];payload=job['payload'];validate_worker_config(cfg)
    if job['action']=='query' and not (Path(job['working_dir'])/payload['scope_key']).is_dir():
        raise ProbeError('cache','native_cache_missing')
    check_tokenizer(cfg['tokenizer_cache'],cfg['tokenizer_encoding']);runtime=verify_runtime(cfg['runtime_lock'],cfg['sdk_version'])
    if os.environ.get('PYTHON_DOTENV_DISABLED')!='1':raise ProbeError('runtime','dotenv_not_disabled')
    from lightrag import LightRAG,QueryParam
    from lightrag.utils import EmbeddingFunc,TiktokenTokenizer,sanitize_text_for_encoding
    journal=Journal(job['cache_root'],cfg,cfg['mode']);tokenizer=TiktokenTokenizer(model_name='gpt-4o-mini')
    cb=GraphCallbacks(payload,cfg,journal,sanitize_text_for_encoding,tokenizer)
    def chunk(*a):return cb.chunk(*a)
    async def embedding(*a,**k):return await cb.embedding(*a,**k)
    async def extract(*a,**k):return await cb.model('extract',*a,**k)
    async def keyword(*a,**k):return await cb.model('keyword',*a,**k)
    async def forbidden(*a,**k):
        cb.trace['callback_errors'].append(ProbeError('callback','unexpected_llm_call').record())
        raise ProbeError('callback','unexpected_llm_call')
    role_config={role:{'func':func,'max_async':cfg['http_concurrency'],'timeout':cfg['role_timeout_seconds'],
                       'metadata':{'binding':'b1-http','model':cfg['chat_model'],'host':cfg['chat_endpoint']}}
                 for role,func in [('extract',extract),('keyword',keyword),('query',forbidden),('vlm',forbidden)]}
    fields=['max_total_tokens','max_entity_tokens','max_relation_tokens','entity_extraction_use_json','entity_extract_max_gleaning',
            'entity_extract_max_records','entity_extract_max_entities','force_llm_summary_on_merge','summary_context_size',
            'summary_max_tokens','summary_length_recommended','kg_chunk_pick_method','related_chunk_number',
            'max_source_ids_per_entity','max_source_ids_per_relation','max_file_paths']
    rag=LightRAG(working_dir=job['working_dir'],workspace=payload['scope_key'],tokenizer=tokenizer,chunking_func=chunk,
                chunk_token_size=3072,chunk_overlap_token_size=0,embedding_chunk_overlap_token_size=0,
                embedding_func=EmbeddingFunc(embedding_dim=cfg['dimensions'],max_token_size=3072,func=embedding,
                                             model_name=cfg['embedding_model'],supports_asymmetric=True),
                llm_model_func=forbidden,llm_model_name=cfg['chat_model'],role_llm_configs=role_config,
                max_parallel_insert=1,embedding_func_max_async=1,embedding_batch_num=cfg['batch_size'],
                default_embedding_timeout=cfg['role_timeout_seconds'],enable_content_headings=False,rerank_model_func=None,
                vector_db_storage_cls_kwargs={'cosine_better_than_threshold':cfg['cosine_threshold']},
                addon_params={'language':cfg['language']},**{k:cfg[k] for k in fields})
    events=Events();logging.getLogger('lightrag').addHandler(events)
    await rag.initialize_storages();queries=[];verified=None;pilot=None
    try:
        action=job['action']
        if action=='pilot':
            from lightrag.operate import extract_entities,extract_keywords_only
            unit=job['pilot_unit'];chunks={unit['native_id']:{'content':unit['content'],'file_path':unit['native_file_path'],
                   'full_doc_id':'doc-'+unit['document_id'],'tokens':len(tokenizer.encode(unit['content'])),'chunk_order_index':0}}
            state={'cancellation_requested':False,'latest_message':'','history_messages':[]}
            extracted=await extract_entities(chunks,rag._build_global_config(),state,asyncio.Lock(),rag.llm_response_cache)
            nodes=sum(len(n) for n,e in extracted);edges=sum(len(e) for n,e in extracted)
            keywords=await extract_keywords_only(job['pilot_query']['query'],QueryParam(mode='mix'),rag._build_global_config(),rag.llm_response_cache)
            pilot={'entity_names':sorted({name for n,e in extracted for name in n}),
                   'entity_count':nodes,'relation_count':edges,'keywords':keywords,'unit_id':unit['unit_id']}
            if not nodes or not edges:raise ProbeError('pilot','pilot_no_graph_signal')
        elif action=='build':
            await rag.apipeline_enqueue_documents([d['content'] for d in payload['documents']],ids=[d['native_id'] for d in payload['documents']],
                                                  file_paths=[d['native_file_path'] for d in payload['documents']],process_options='C')
            await rag.apipeline_process_enqueue_documents();await rag._insert_done()
            verified=await audit(rag,payload,journal,sanitize_text_for_encoding)
            if sorted(cb.trace['chunk_calls'])!=sorted(d['document_id'] for d in payload['documents']):raise ProbeError('chunk','chunk_callback_mismatch')
        elif action=='query':
            verified=await audit(rag,payload,journal,sanitize_text_for_encoding)
            for query in payload['queries']:
                common={'top_k':cfg['candidate_k'],'chunk_top_k':cfg['candidate_k'],'max_total_tokens':cfg['max_total_tokens'],
                        'enable_rerank':False,'disable_user_prompt_prefix':True}
                naive=await rag.aquery_data(query['query'],QueryParam(mode='naive',max_entity_tokens=0,max_relation_tokens=0,**common))
                mix=await rag.aquery_data(query['query'],QueryParam(mode='mix',max_entity_tokens=cfg['max_entity_tokens'],max_relation_tokens=cfg['max_relation_tokens'],**common))
                for result in [naive,mix]:
                    if result.get('status')=='failure' and result.get('metadata',{}).get('failure_reason')!='no_results':raise ProbeError('query','native_query_failure')
                    map_native(payload,result.get('data',{}).get('chunks',[]))
                vector=cb.np.asarray(payload['query_vectors'][digest(query['query'].encode())],dtype=cb.np.float64)
                raw=await rag.chunks_vdb.query(query['query'],top_k=cfg['candidate_k'],query_embedding=vector)
                queries.append({'task_id':query['task_id'],'naive':naive,'mix':mix,'raw_vector':raw})
        else:raise ProbeError('worker','invalid_action')
        counts=journal.summary()
        if cb.trace['callback_errors'] or journal.errors or counts['failed_requests'] or counts['inflight_requests']:
            raise ProbeError('callback','callback_failed')
    finally:
        await rag.finalize_storages();logging.getLogger('lightrag').removeHandler(events)
    return {'status':'complete','runtime':runtime,'audit':verified,'pilot':pilot,'queries':queries,'trace':cb.trace,
            'requests':journal.summary(),'events':events.counts,'dotenv_sentinel_loaded':'B1_DOTENV_SENTINEL' in os.environ}


def main():
    started=time.monotonic();counter=[0];job=None
    try:
        job=json.load(sys.stdin)
        import pipmaster
        def forbid(*a,**k):raise ProbeError('runtime','runtime_install_forbidden')
        for name in ['install','install_async','install_requirements','install_requirements_async']:
            if hasattr(pipmaster,name):setattr(pipmaster,name,forbid)
        def no_process(event,args):
            if event in ['subprocess.Popen','os.system']:raise ProbeError('runtime','runtime_install_forbidden')
        sys.addaudithook(no_process)
        with redirect_stdout(sys.stderr):
            if job['config']['mode']=='replay':
                with offline_guard(counter):result=asyncio.run(execute(job))
            else:result=asyncio.run(execute(job))
    except ProbeError as error:result={'status':'error','sanitized_error':error.record()}
    except Exception as error:result={'status':'error','sanitized_error':ProbeError('sdk','sdk_error').record(),'error_type':type(error).__name__}
    result.update(elapsed_ms=round((time.monotonic()-started)*1000,3),network_forbidden_attempts=counter[0])
    print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0 if result['status']=='complete' else 2


if __name__=='__main__':raise SystemExit(main())
