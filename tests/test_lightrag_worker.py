import importlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT/'.venv-lightrag/bin/python'
TOKENS = ROOT/'data/runtime/lightrag/o200k-cache'


def job(tmp_path):
    from test_lightrag_mapping import inputs
    from experiments.lightrag_mapping import make_payload
    corpus, index, queries = inputs(tmp_path)
    payload = make_payload(corpus, index, [queries[2]])
    return {**payload, 'action': 'build', 'working_dir': str(tmp_path/'store'),
            'tokenizer_cache': str(TOKENS), 'tokenizer_encoding': 'o200k_base',
            'runtime_lock': str(ROOT/'requirements-lightrag-runtime.lock.txt'), 'sdk_version': '1.5.7',
            'model': 'embedding-3', 'dimensions': 2048, 'candidate_k': 20,
            'max_total_tokens': 32768, 'cosine_threshold': -1.0}


def call(payload, cwd):
    from experiments.lightrag_runtime import worker_environment
    cwd.mkdir(exist_ok=True)
    (cwd/'.env').write_text('B0_DOTENV_SENTINEL=must_not_load\n')
    proc = subprocess.run([str(RUNTIME), '-m', 'experiments.lightrag_worker'],
                          input=json.dumps(payload), text=True, capture_output=True, timeout=60,
                          cwd=cwd, env=worker_environment(TOKENS))
    assert proc.stdout.strip(), proc.stderr[-2000:]
    return proc.returncode, json.loads(proc.stdout)


def test_real_sdk_storage_and_new_process_reload(tmp_path):
    payload = job(tmp_path)
    code, built = call(payload, tmp_path/'build-worker')
    assert code == 0 and built['status'] == 'complete', built
    assert built['audit']['chunk_count'] == 10 and built['audit']['document_count'] == 1
    assert built['audit']['graph_nodes'] == built['audit']['graph_edges'] == 0
    assert built['trace']['document_texts'] == 10 and built['trace']['llm_calls'] == 0
    assert built['trace']['network_attempts'] == 0 and built['dotenv_sentinel_loaded'] is False
    code, queried = call(dict(payload, action='query'), tmp_path/'query-worker')
    assert code == 0 and queried['status'] == 'complete', queried
    assert queried['trace']['document_texts'] == 0 and queried['trace']['query_texts'] == 1
    assert queried['trace']['chunk_calls'] == [] and queried['trace']['llm_calls'] == 0
    assert queried['audit']['chunk_count'] == 10 and len(queried['queries'][0]['chunks']) == 10
    assert queried['audit']['max_vector_error'] <= 1e-6
    native=next((tmp_path/'store').rglob('kv_store_text_chunks.json'))
    data=json.loads(native.read_text());next(iter(data.values()))['content']='corrupt'
    native.write_text(json.dumps(data))
    code,failed=call(dict(payload,action='query'),tmp_path/'corrupt-worker')
    assert code==2 and failed['sanitized_error']['category']=='shared_corpus_mismatch'
    assert failed['trace']['query_texts']==0


@pytest.mark.parametrize('fault', ['missing_vector', 'content_change', 'normalized_duplicate', 'wrong_version'])
def test_real_sdk_rejects_invalid_inputs_without_live_fallback(tmp_path, fault):
    payload = job(tmp_path)
    if fault == 'missing_vector': payload['vectors'].pop(next(iter(payload['vectors'])))
    elif fault == 'content_change': payload['units'][0]['content'] += ' changed'
    elif fault == 'normalized_duplicate':
        doc = dict(payload['documents'][0], native_id='doc-other', content='\n'+payload['documents'][0]['content']+'\n')
        payload['documents'].append(doc)
    else: payload['sdk_version'] = '1.5.8'
    code, result = call(payload, tmp_path/'fault-worker')
    assert code == 2 and result['status'] == 'error'
    assert result['trace']['llm_calls'] == 0 and result['trace']['network_attempts'] == 0


def test_runtime_callbacks_empty_unknown_and_llm_fail(tmp_path):
    payload = job(tmp_path)
    # Execute callbacks inside the actual SDK environment; no fake vectors.
    script = '''import asyncio, json, sys
from experiments.lightrag_worker import Callbacks
from experiments.embedding_probe import ProbeError
p=json.load(sys.stdin); c=Callbacks(p, lambda x:x.strip())
async def main():
 assert (await c.embedding([],context="document")).shape==(0,2048)
 texts=[p['units'][1]['content'],p['units'][0]['content'],p['units'][1]['content']]
 import hashlib, numpy as np
 array=await c.embedding(texts,context="document")
 assert np.array_equal(array,np.array([p['vectors'][hashlib.sha256(t.encode()).hexdigest()] for t in texts]))
 for context,texts in [("other",["x"]),("query",["absent"])]:
  try: await c.embedding(texts,context=context)
  except ProbeError: pass
  else: raise AssertionError("fallback")
 try: await c.llm("x")
 except ProbeError: pass
 else: raise AssertionError("fake LLM")
 print(json.dumps(c.trace))
asyncio.run(main())'''
    from experiments.lightrag_runtime import worker_environment
    proc = subprocess.run([str(RUNTIME), '-c', script], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=tmp_path, env=worker_environment(TOKENS), timeout=30)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout)['llm_calls'] == 1
