"""One isolated real LightRAG 1.5.7 lifecycle; never calls a model service."""
import asyncio
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
import time

from experiments.embedding_probe import ProbeError
from experiments.lightrag_runtime import check_tokenizer, offline_guard, verify_runtime
from experiments.vector_index import digest


class Callbacks:
    def __init__(self, payload, sanitize):
        import numpy as np
        self.np = np; self.payload = payload
        self.trace = {'chunk_calls': [], 'document_texts': 0, 'query_texts': 0, 'embedding_batches': [],
                      'llm_calls': 0, 'network_attempts': 0, 'callback_error': None}
        self.sources = {}
        for doc in payload['documents']:
            key = digest(sanitize(doc['content']).encode())
            if key in self.sources: raise ProbeError('mapping', 'ambiguous_source_input')
            self.sources[key] = doc
        for unit in payload['units']:
            key = digest(unit['content'].encode())
            if key != unit['input_sha256'] or key not in payload['vectors']:
                raise ProbeError('cache', 'embedding_cache_miss')
        for vectors in [payload['vectors'], payload['query_vectors']]:
            for value in vectors.values():
                array = np.asarray(value, dtype=np.float64)
                if array.shape != (payload['dimensions'],) or not np.isfinite(array).all() or np.linalg.norm(array) == 0:
                    raise ProbeError('cache', 'invalid_cached_vector')

    def chunk(self, tokenizer, content, split_by_character, split_by_character_only, overlap, size):
        key = digest(content.encode())
        if key not in self.sources: raise ProbeError('mapping', 'unknown_source_input')
        doc = self.sources[key]
        self.trace['chunk_calls'].append(doc['document_id'])
        units = [u for u in self.payload['units'] if u['document_id'] == doc['document_id']]
        result = []
        for i, unit in enumerate(units):
            tokens = len(tokenizer.encode(unit['content']))
            if tokens > 3072: raise ProbeError('mapping', 'shared_corpus_token_limit')
            result.append({'chunk_id': unit['native_id'], 'content': unit['content'],
                           'tokens': tokens, 'chunk_order_index': i})
        return result

    async def embedding(self, texts, context=None, **kwargs):
        if context not in ['document', 'query']:
            self.trace['callback_error'] = 'unknown_embedding_context'
            raise ProbeError('cache', 'unknown_embedding_context')
        vectors = self.payload['vectors' if context == 'document' else 'query_vectors']
        hashes = [digest(text.encode()) for text in texts]
        if any(key not in vectors for key in hashes):
            self.trace['callback_error'] = 'embedding_cache_miss'
            raise ProbeError('cache', 'embedding_cache_miss')
        self.trace[context+'_texts'] += len(texts)
        self.trace['embedding_batches'].append({'context': context, 'input_sha256': hashes})
        return self.np.asarray([vectors[key] for key in hashes], dtype=self.np.float64).reshape(len(texts), self.payload['dimensions'])

    async def llm(self, *args, **kwargs):
        self.trace['llm_calls'] += 1
        self.trace['callback_error'] = 'unexpected_llm_call'
        raise ProbeError('model', 'unexpected_llm_call')


async def audit(rag, payload, sanitize):
    import numpy as np
    ids = [u['native_id'] for u in payload['units']]
    actual = await rag.text_chunks.get_by_ids(ids)
    if set(rag.text_chunks._data) != set(ids): raise ProbeError('storage', 'shared_corpus_mismatch')
    for unit, row in zip(payload['units'], actual, strict=True):
        if row is None or row['content'] != unit['content'] or \
                row['full_doc_id'] != 'doc-'+unit['document_id'] or row['file_path'] != unit['native_file_path']:
            raise ProbeError('storage', 'shared_corpus_mismatch')
    doc_ids = [d['native_id'] for d in payload['documents']]
    statuses = await rag.doc_status.get_by_ids(doc_ids)
    if set(rag.doc_status._data) != set(doc_ids) or set(rag.full_docs._data) != set(doc_ids):
        raise ProbeError('storage', 'native_document_mismatch')
    source_rows = await rag.full_docs.get_by_ids(doc_ids)
    for doc, status, source in zip(payload['documents'], statuses, source_rows, strict=True):
        meta = status.get('metadata', {}) if status else {}
        expected_ids = [u['native_id'] for u in payload['units'] if u['document_id'] == doc['document_id']]
        if not status or status['status'] != 'processed' or meta.get('skip_kg') is not True or \
                meta.get('chunk_method') != 'custom_chunking_func' or meta.get('hard_fallback_split') or \
                set(status['chunks_list']) != set(expected_ids) or status['chunks_count'] != len(expected_ids):
            raise ProbeError('storage', 'native_document_mismatch')
        if source['content'] != sanitize(doc['content']) or source['file_path'] != doc['native_file_path']:
            raise ProbeError('storage', 'native_document_mismatch')
    # Pinned Nano private storage: inspect the actual array, not the callback's claimed result.
    native = rag.chunks_vdb._client._NanoVectorDB__storage
    rows, matrix = native['data'], native['matrix']
    if {r['__id__'] for r in rows} != set(ids) or len(rows) != len(ids) or \
            matrix.shape != (len(ids), payload['dimensions']) or matrix.dtype != np.float32:
        raise ProbeError('storage', 'native_vector_mismatch')
    by_id = {u['native_id']: u for u in payload['units']}; error = 0.
    for i, row in enumerate(rows):
        unit = by_id[row['__id__']]
        vector = np.asarray(payload['vectors'][unit['input_sha256']], dtype=np.float64)
        expected = (vector/np.linalg.norm(vector)).astype(np.float32)
        if not np.allclose(matrix[i], expected, rtol=1e-6, atol=1e-8):
            raise ProbeError('storage', 'native_vector_mismatch')
        error = max(error, float(np.max(np.abs(matrix[i]-expected))))
        if row['content'] != unit['content']: raise ProbeError('storage', 'native_vector_mismatch')
    nodes = rag.chunk_entity_relation_graph._graph.number_of_nodes()
    edges = rag.chunk_entity_relation_graph._graph.number_of_edges()
    if nodes or edges or rag.entities_vdb._client._NanoVectorDB__storage['data'] or \
            rag.relationships_vdb._client._NanoVectorDB__storage['data']:
        raise ProbeError('storage', 'unexpected_graph_data')
    return {'chunk_count': len(ids), 'document_count': len(doc_ids), 'graph_nodes': nodes, 'graph_edges': edges,
            'max_vector_error': error, 'vector_dtype': str(matrix.dtype),
            'chunk_content_sha256': {u['native_id']: u['input_sha256'] for u in payload['units']}}


async def execute(payload, callbacks, runtime):
    import numpy as np
    from lightrag import LightRAG, QueryParam
    from lightrag.utils import EmbeddingFunc, TiktokenTokenizer, sanitize_text_for_encoding
    from lightrag.prompt import PROMPTS
    tokenizer = TiktokenTokenizer(model_name='gpt-4o-mini')
    # SDK asdict deep-copies bound-method owners; plain closures preserve callback identity and trace.
    def chunk(*args): return callbacks.chunk(*args)
    async def embedding(*args, **kwargs): return await callbacks.embedding(*args, **kwargs)
    async def llm(*args, **kwargs): return await callbacks.llm(*args, **kwargs)
    rag = LightRAG(working_dir=payload['working_dir'], workspace=payload['scope_key'],
                   kv_storage='JsonKVStorage', vector_storage='NanoVectorDBStorage', graph_storage='NetworkXStorage',
                   doc_status_storage='JsonDocStatusStorage', tokenizer=tokenizer, chunking_func=chunk,
                   chunk_token_size=3072, chunk_overlap_token_size=0, embedding_chunk_overlap_token_size=0,
                   embedding_func=EmbeddingFunc(embedding_dim=payload['dimensions'], max_token_size=3072,
                                                func=embedding, model_name=payload['model'],
                                                send_dimensions=False, supports_asymmetric=True),
                   llm_model_func=llm, llm_model_name='glm-5.2',
                   max_parallel_insert=1, embedding_func_max_async=1, embedding_batch_num=16,
                   enable_content_headings=False, rerank_model_func=None,
                   vector_db_storage_cls_kwargs={'cosine_better_than_threshold': payload['cosine_threshold']})
    await rag.initialize_storages()
    results = []
    try:
        if rag.chunks_vdb.cosine_better_than_threshold != payload['cosine_threshold']:
            raise ProbeError('config', 'native_threshold_mismatch')
        if payload['action'] == 'build':
            await rag.apipeline_enqueue_documents([d['content'] for d in payload['documents']],
                ids=[d['native_id'] for d in payload['documents']],
                file_paths=[d['native_file_path'] for d in payload['documents']], process_options='C!')
            await rag.apipeline_process_enqueue_documents()
            await rag._insert_done()
            if sorted(callbacks.trace['chunk_calls']) != sorted(d['document_id'] for d in payload['documents']):
                raise ProbeError('mapping', 'chunk_callback_mismatch')
        elif payload['action'] == 'query':
            # Check reloaded stores before the first retrieval; never silently rebuild missing data.
            await audit(rag, payload, sanitize_text_for_encoding)
            param = QueryParam(mode='naive', chunk_top_k=payload['candidate_k'], top_k=payload['candidate_k'],
                               enable_rerank=False, disable_user_prompt_prefix=True,
                               max_total_tokens=payload['max_total_tokens'], max_entity_tokens=0, max_relation_tokens=0)
            for query in payload['queries']:
                data = await rag.aquery_data(query['query'], param)
                if data.get('status') == 'failure' and data.get('metadata', {}).get('failure_reason') != 'no_results':
                    raise ProbeError('query', 'native_query_failure')
                chunks = data.get('data', {}).get('chunks', [])
                qvector = np.asarray(payload['query_vectors'][digest(query['query'].encode())], dtype=np.float64)
                raw = await rag.chunks_vdb.query(query['query'], top_k=payload['candidate_k'], query_embedding=qvector)
                template = PROMPTS['naive_rag_response'].format(response_type=param.response_type, user_prompt='n/a', content_data='')
                available = payload['max_total_tokens']-len(tokenizer.encode(template))-len(tokenizer.encode(query['query']))-200
                worst = sum(len(tokenizer.encode(u['content'])) for u in payload['units'])
                results.append({'task_id': query['task_id'], 'raw': raw, 'chunks': chunks,
                                'metadata': data.get('metadata', {}), 'native_status': data.get('status'),
                                'available_chunk_tokens': available, 'scope_total_content_tokens': worst})
        else: raise ProbeError('worker', 'invalid_action')
        verified = await audit(rag, payload, sanitize_text_for_encoding)
        if callbacks.trace['callback_error'] or callbacks.trace['llm_calls']:
            raise ProbeError('callback', callbacks.trace['callback_error'] or 'unexpected_llm_call')
    finally:
        await rag.finalize_storages()
    return {'status': 'complete', 'runtime': runtime, 'audit': verified, 'queries': results,
            'trace': callbacks.trace, 'dotenv_sentinel_loaded': 'B0_DOTENV_SENTINEL' in os.environ}


def main():
    counter = [0]; callbacks = None; started = time.monotonic()
    try:
        payload = json.load(sys.stdin)
        if os.environ.get('PYTHON_DOTENV_DISABLED') != '1': raise ProbeError('runtime', 'dotenv_not_disabled')
        check_tokenizer(payload['tokenizer_cache'], payload['tokenizer_encoding'])
        runtime = verify_runtime(payload['runtime_lock'], payload['sdk_version'])
        with offline_guard(counter), redirect_stdout(sys.stderr):
            import pipmaster
            def no_install(*args, **kwargs): raise ProbeError('runtime', 'runtime_install_forbidden')
            for name in ['install', 'install_async', 'install_requirements', 'install_requirements_async']:
                if hasattr(pipmaster, name): setattr(pipmaster, name, no_install)
            def forbid_process(event, args):
                if event in ['subprocess.Popen', 'os.system']: raise ProbeError('runtime', 'runtime_install_forbidden')
            sys.addaudithook(forbid_process)
            from lightrag.utils import sanitize_text_for_encoding
            callbacks = Callbacks(payload, sanitize_text_for_encoding)
            result = asyncio.run(execute(payload, callbacks, runtime))
    except ProbeError as error:
        result = {'status': 'error', 'sanitized_error': error.record()}
    except Exception as error:
        result = {'status': 'error', 'sanitized_error': ProbeError('sdk', 'sdk_error').record(),
                  'error_type': type(error).__name__}
    trace = callbacks.trace if callbacks else {'chunk_calls': [], 'document_texts': 0, 'query_texts': 0, 'llm_calls': 0}
    trace['network_attempts'] = counter[0]
    result.update(trace=trace, elapsed_ms=round((time.monotonic()-started)*1000, 3))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__': raise SystemExit(main())
