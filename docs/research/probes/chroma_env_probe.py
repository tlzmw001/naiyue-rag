"""Synthetic, isolated Chroma investigation; never loads project credentials.

Run with the project's Python. Output contains counts and fixed codes only.
This is research code, not the proposed production storage boundary.
"""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


CHILD = r'''
import json, math, pathlib, socket, sys
env_opens = 0
network_attempts = 0
def audit(event, args):
    global env_opens
    if event == 'open' and isinstance(args[0], (str, bytes)):
        if pathlib.Path(args[0]).name == '.env': env_opens += 1
sys.addaudithook(audit)
def denied(*args, **kwargs):
    global network_attempts
    network_attempts += 1
    raise RuntimeError('probe_network_denied')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = denied
action, database = sys.argv[1:]
result = {'action': action}
try:
    import chromadb
    from chromadb.config import Settings
    result.update(import_ok=True, imported_allow_reset=chromadb.get_settings().allow_reset)
    settings = Settings(_env_file=None, allow_reset=False, anonymized_telemetry=False)
    result['explicit_allow_reset'] = settings.allow_reset
    if action != 'import':
        with chromadb.PersistentClient(path=database, settings=settings) as client:
            result['effective_allow_reset'] = client.get_settings().allow_reset
            if action in ('build', 'empty'):
                collection = client.create_collection('synthetic_probe', embedding_function=None,
                    configuration={'hnsw': {'space': 'cosine'}}, metadata={'bundle_id': 'synthetic'})
                if action == 'build':
                    collection.upsert(ids=['chunk-a','chunk-b'], embeddings=[[1.,0.,1.],[0.,1.,1.]],
                        documents=['synthetic alpha','synthetic beta'],
                        metadatas=[{'document_id':'doc-a'},{'document_id':'doc-b'}])
            else:
                def no_create(*args, **kwargs): raise RuntimeError('probe_unexpected_create')
                client.create_collection = client.get_or_create_collection = no_create
                collection = client.get_collection('synthetic_probe', embedding_function=None)
            result['count'] = collection.count()
            config = collection.configuration
            result['cosine'] = config['hnsw']['space'] == 'cosine'
            result['embedding_disabled'] = config.get('embedding_function') is None
            if result['count']:
                rows = collection.get(ids=['chunk-b','chunk-a'], include=['embeddings','documents','metadatas'])
                actual = {uid:(vector.tolist(),text,meta['document_id']) for uid,vector,text,meta in
                    zip(rows['ids'],rows['embeddings'],rows['documents'],rows['metadatas'],strict=True)}
                result['roundtrip_exact'] = actual == {
                    'chunk-a':([1.,0.,1.],'synthetic alpha','doc-a'),
                    'chunk-b':([0.,1.,1.],'synthetic beta','doc-b')}
                originals = {'chunk-a':[1.,0.,1.], 'chunk-b':[0.,1.,1.]}
                result['max_raw_vector_error'] = max(abs(actual[uid][0][i]-value)
                    for uid,values in originals.items() for i,value in enumerate(values))
                result['max_unit_vector_error'] = max(abs(actual[uid][0][i]-value/math.sqrt(2))
                    for uid,values in originals.items() for i,value in enumerate(values))
                result['source_exact'] = all(actual[uid][1:] == source for uid,source in {
                    'chunk-a':('synthetic alpha','doc-a'), 'chunk-b':('synthetic beta','doc-b')}.items())
                result['raw_vector_within_existing_contract'] = all(
                    math.isclose(actual[uid][0][i], value, rel_tol=1e-6, abs_tol=1e-8)
                    for uid,values in originals.items() for i,value in enumerate(values))
        result['closed'] = client._closed  # Diagnostic only; production uses public close().
    result['status'] = 'ok'
except Exception as error:
    result.update(status='error', error_type=type(error).__name__)
result.update(env_open_count=env_opens, python_network_attempts=network_attempts)
print(json.dumps(result,sort_keys=True))
'''


def snapshot(root):
    return {str(p.relative_to(root)): {
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
        'mtime_ns': p.stat().st_mtime_ns, 'bytes': p.stat().st_size,
    } for p in root.rglob('*') if p.is_file()}


def run_child(cwd, action='import', database=None):
    env = {'PATH': os.defpath, 'HOME': str(cwd), 'OMP_NUM_THREADS': '1',
           'TOKENIZERS_PARALLELISM': 'false'}
    completed = subprocess.run([sys.executable, '-I', '-c', CHILD, action,
                                str(database or cwd/'unused')],
                               cwd=cwd, env=env, capture_output=True, timeout=30)
    if completed.returncode != 0:
        return {'status': 'child_failed', 'returncode': completed.returncode,
                'stderr_bytes': len(completed.stderr)}
    result = json.loads(completed.stdout)
    result['stderr_bytes'] = len(completed.stderr)
    return result


def main():
    rows = {}
    with tempfile.TemporaryDirectory(prefix='naiyue-chroma-synthetic-') as temporary:
        root = Path(temporary)
        for name, content in [('clean', None), ('recognized', 'ALLOW_RESET=true\n'),
                              ('unknown_key', 'SYNTHETIC_KEY=not-a-real-key\n'),
                              ('invalid_value', 'ALLOW_RESET=synthetic-invalid\n')]:
            work = root/name; work.mkdir()
            if content is not None: (work/'.env').write_text(content)
            rows[name] = run_child(work)
        clean = root/'clean'
        for name, empty in [('nonempty', False), ('empty', True)]:
            database = root/('db-'+name)
            rows[name+'_build'] = run_child(clean, 'empty' if empty else 'build', database)
            before = snapshot(database)
            rows[name+'_reopen'] = run_child(clean, 'read', database)
            after = snapshot(database)
            rows[name+'_disk_change'] = {
                'added': sorted(set(after)-set(before)), 'removed': sorted(set(before)-set(after)),
                'content_changed': sorted(k for k in set(before)&set(after)
                                          if before[k]['sha256'] != after[k]['sha256']),
                'mtime_changed': sorted(k for k in set(before)&set(after)
                                        if before[k]['mtime_ns'] != after[k]['mtime_ns'])}
            published = root/('published-'+name)
            database.rename(published)
            rows[name+'_after_directory_rename'] = run_child(clean, 'read', published)
    sdk = metadata.distribution('chromadb')
    sources = {name: hashlib.sha256(sdk.locate_file('chromadb/'+name).read_bytes()).hexdigest()
               for name in ['__init__.py','config.py','api/client.py','api/shared_system_client.py']}
    report = {'date': '2026-10-15', 'sdk_version': sdk.version, 'cases': rows,
              'sdk_source_sha256': sources, 'real_project_env_reads': 0,
              'model_calls': 0, 'native_network_observation': 'unknown; telemetry disabled',
              'limits': 'synthetic local probe; no concurrent, crash or business quality claim'}
    expected = [rows['clean']['status']=='ok', rows['clean']['env_open_count']==0,
                rows['recognized'].get('imported_allow_reset') is True,
                rows['recognized'].get('explicit_allow_reset') is False,
                rows['unknown_key']['status']=='ok', rows['invalid_value']['status']=='error']
    for name in ['nonempty', 'empty']:
        expected.extend(rows[name+suffix]['status']=='ok'
                        for suffix in ['_build','_reopen','_after_directory_rename'])
        expected.append(rows[name+'_reopen']['embedding_disabled'])
    for suffix in ['_build','_reopen']:
        expected.append(rows['nonempty'+suffix]['source_exact'])
        expected.append(rows['nonempty'+suffix]['raw_vector_within_existing_contract'])
    expected.append(rows['nonempty_after_directory_rename']['source_exact'])
    expected.append(rows['nonempty_after_directory_rename']['raw_vector_within_existing_contract'])
    report['expected_checks_passed'] = all(expected)
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0 if all(expected) else 1


if __name__ == '__main__':
    raise SystemExit(main())
