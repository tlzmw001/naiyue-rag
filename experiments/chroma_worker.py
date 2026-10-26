"""Isolated native Chroma writer/reloader using frozen vectors; no model calls."""
import base64
from importlib import metadata
import json
import os
from pathlib import Path
import re
import sys

import numpy as np

from experiments.embedding_probe import ProbeError, cosine
from experiments.lightrag_runtime import offline_guard
from experiments.vector_eval import load_queries
from experiments.vector_index import digest, load_corpus, load_index, read_json
from naiyue_rag.chroma_store import ChromaStore
from naiyue_rag.retrieval import RetrievalError


def verify_runtime(lock_path):
    try:
        lock = Path(lock_path).read_bytes()
        pins = re.findall(rb'^([\w.-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})$',lock,re.M)
        if len(pins) != 49:
            raise ValueError('lock')
        versions = {name.decode():version.decode() for name,version,_ in pins}
        if versions.get('chromadb') != '1.5.9' or any(metadata.version(k) != v for k,v in versions.items()):
            raise ValueError('version')
        files = {}
        sdk = metadata.distribution('chromadb')
        for file in sdk.files:
            if str(file).startswith('chromadb/') and str(file).endswith(('.py','.so')):
                value = digest(file.locate().read_bytes())
                if not file.hash or file.hash.mode != 'sha256' or \
                        base64.urlsafe_b64encode(bytes.fromhex(value)).decode().rstrip('=') != file.hash.value:
                    raise ValueError('record')
                files[str(file)] = value
        if not files:
            raise ValueError('sdk')
        return {'sdk_version':'1.5.9', 'lock_sha256':digest(lock), 'versions':versions,
                'sdk_source_count':len(files), 'sdk_source_sha256':digest(json.dumps(files,sort_keys=True).encode())}
    except Exception:
        raise ProbeError('runtime','runtime_mismatch') from None


def audit(store, index):
    ids = list(index['units'])
    got = store.get_by_ids(ids)
    if store.count() != len(ids):
        raise ProbeError('chroma-audit','native_count_mismatch')
    max_error = 0.
    for uid in ids:
        expected = np.asarray(index['vectors'][uid],dtype=np.float32)
        actual = np.asarray(got[uid]['vector'],dtype=np.float32)
        if got[uid]['unit'] != index['units'][uid] or not np.allclose(actual,expected,rtol=1e-6,atol=1e-8):
            raise ProbeError('chroma-audit','native_content_mismatch')
        max_error = max(max_error,float(np.max(np.abs(actual.astype(float)-expected.astype(float)))))
    return {'unit_count':len(ids), 'max_vector_error':max_error,
            'comparison':'float32 conversion, rtol=1e-6 atol=1e-8; evidence exact'}


def execute(job, network_counter):
    if Path('.env').exists():
        raise ProbeError('runtime','uncontrolled_sdk_environment')
    runtime = verify_runtime(job['runtime_lock'])
    cfg = job['config']
    corpus = load_corpus(cfg['corpus_run'],cfg['dataset'])
    index = load_index(cfg['vector_run'],corpus['fingerprint'],cfg)
    queries = load_queries(cfg['tasks'],corpus)
    if set(index['query_hashes']) != {q['task_id'] for q in queries} or any(
            index['query_hashes'][q['task_id']] != digest(q['query'].encode()) for q in queries):
        raise ProbeError('cache','cache_mismatch')
    action = job['action']
    if action not in ['build','query']:
        raise ProbeError('worker','invalid_action')
    counts = {'creation_calls':0,'upsert_calls':0}
    if action == 'query':
        # Guard the actual SDK methods in this process, not just our wrapper.
        from chromadb.api.client import Client
        from chromadb.api.models.Collection import Collection
        def no_create(*args,**kwargs):
            counts['creation_calls'] += 1
            raise ProbeError('worker','unexpected_creation')
        def no_upsert(*args,**kwargs):
            counts['upsert_calls'] += 1
            raise ProbeError('worker','unexpected_write')
        Client.get_or_create_collection = Client.create_collection = no_create
        Collection.upsert = no_upsert
    store = ChromaStore(job['store_config'],index['units'],create=(action=='build'))
    settings = store.client.get_settings()
    if settings.allow_reset or settings.anonymized_telemetry:
        raise ProbeError('chroma-audit','settings_mismatch')
    result = {'status':'complete','pid':os.getpid(),'runtime':runtime,**counts,
              'settings':{'allow_reset':settings.allow_reset,'anonymized_telemetry':settings.anonymized_telemetry},
              'configuration':store.collection.configuration,
              'trace':{'python_network_attempts':network_counter[0], 'model_calls':0,
                       'native_network_observation':'unknown; telemetry explicitly disabled'}}
    if action == 'build':
        # Match the reference ingestion batch default without changing vectors.
        items = list(index['vectors'].items())
        for start in range(0,len(items),job['batch_size']):
            store.upsert(dict(items[start:start+job['batch_size']]))
        result['count'] = store.count()
        for start in range(0,len(items),job['batch_size']):
            store.upsert(dict(items[start:start+job['batch_size']]))
        result['repeat_count'] = store.count()
    else:
        result.update(count=store.count(),audit=audit(store,index))
        try:
            store.client.reset()
        except Exception as error:
            from chromadb.errors import AuthorizationError
            if not isinstance(error,AuthorizationError):
                raise ProbeError('chroma-audit','reset_check_failed') from None
            result['reset_denied'] = True
            result['reset_error_type'] = type(error).__name__
            result['reset_error_code'] = error.code()
        else:
            raise ProbeError('chroma-audit','reset_unexpectedly_allowed')
        try:
            store.client.get_collection(name=job['store_config']['collection_name']+'-missing',embedding_function=None)
        except Exception as error:
            from chromadb.errors import NotFoundError
            if not isinstance(error,NotFoundError):
                raise ProbeError('chroma-audit','missing_collection_check_failed') from None
            result['missing_collection_denied'] = True
        else:
            raise ProbeError('chroma-audit','missing_collection_unexpected')
        result['results'] = []
        for query in queries:
            ranked = store.query(index['query_vectors'][query['task_id']],query['scope_ids'],
                                 query['exclude_ids'],job['candidate_k'])
            maximum = 0.
            for unit in ranked['candidates']:
                expected = 1-cosine(index['query_vectors'][query['task_id']],index['vectors'][unit['unit_id']])
                maximum = max(maximum,abs(unit['distance']-expected))
            if maximum > 1e-6:
                raise ProbeError('chroma-audit','distance_mismatch')
            result['results'].append({**query,**ranked,'distance_audit':{'max_error':maximum}})
        result.update(counts)
    if network_counter[0]:
        raise ProbeError('network','unexpected_network_attempt')
    return result


def main():
    counter = [0]
    try:
        raw = sys.stdin.read(16*1024*1024+1)
        if len(raw) > 16*1024*1024:
            raise ProbeError('worker','oversized_input')
        job = json.loads(raw)
        with offline_guard(counter):
            result = execute(job,counter)
    except RetrievalError as error:
        result = {'status':'error','sanitized_error':{'stage':error.stage,'category':error.code}}
    except ProbeError as error:
        result = {'status':'error','sanitized_error':error.record()}
    except Exception:
        result = {'status':'error','sanitized_error':{'stage':'worker','category':'worker_failed'}}
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 0 if result['status']=='complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
