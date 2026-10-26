"""Verify shared synthetic model/Chroma dotenv settings with the pinned SDK.

No project dotenv reads, inherited credentials, model calls or production imports.
"""
from importlib import metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


CHILD = r'''
import json, pathlib, socket, sys
stage = 'import'
opens = network = 0
def audit(event, args):
    global opens
    if event == 'open' and isinstance(args[0], (str, bytes)):
        if pathlib.Path(args[0]).name == '.env': opens += 1
sys.addaudithook(audit)
def deny(*args, **kwargs):
    global network
    network += 1
    raise RuntimeError('synthetic_network_denied')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
result = {}
try:
    import chromadb
    from chromadb.config import Settings
    result['import_allow_reset'] = chromadb.get_settings().allow_reset
    stage = 'settings'
    # Deliberately allow normal SDK dotenv reading for this coexistence probe.
    settings = Settings(allow_reset=False, anonymized_telemetry=False)
    result.update(memory_limit_from_dotenv=settings.chroma_memory_limit_bytes,
                  actual_allow_reset=settings.allow_reset,
                  actual_telemetry=settings.anonymized_telemetry)
    stage = 'client'
    database = pathlib.Path(sys.argv[1])
    with chromadb.PersistentClient(path=str(database), settings=settings) as client:
        result['explicit_path_wins'] = client.get_settings().persist_directory == str(database)
        collection = client.create_collection('shared_env_probe', embedding_function=None,
            configuration={'hnsw':{'space':'cosine'}})
        collection.upsert(ids=['synthetic-chunk'], embeddings=[[1.,0.,0.]],
            documents=['synthetic text'], metadatas=[{'document_id':'synthetic-doc'}])
        rows = collection.get(ids=['synthetic-chunk'], include=['documents'])
        result['written_and_read'] = (collection.count()==1 and rows['documents']==['synthetic text'])
    result['status'] = 'ok'
except Exception as error:
    result.update(status='error', error_stage=stage, error_type=type(error).__name__)
result.update(dotenv_opens=opens, python_network_attempts=network)
print(json.dumps(result))
'''

MODEL_FIELDS = '''NAIYUE_RAG_ZHIPU_API_KEY=synthetic-not-a-real-key
OPENAI_API_KEY=synthetic-not-a-real-key
ANTHROPIC_API_KEY=synthetic-not-a-real-key
NAIYUE_RAG_EMBEDDING_MODEL=synthetic-model
NAIYUE_RAG_CHROMA_COLLECTION_NAME=synthetic_collection
'''


def main():
    cases = {
        'model_fields_only': MODEL_FIELDS,
        'model_and_chroma': MODEL_FIELDS + 'ALLOW_RESET=false\nANONYMIZED_TELEMETRY=false\n'
            'CHROMA_MEMORY_LIMIT_BYTES=104857600\nPERSIST_DIRECTORY=unused-synthetic-path\n',
        'valid_bool_overridden_explicitly': MODEL_FIELDS + 'ALLOW_RESET=true\n',
        'invalid_bool': MODEL_FIELDS + 'ALLOW_RESET=synthetic-invalid\n',
        'invalid_integer': MODEL_FIELDS + 'CHROMA_SERVER_HTTP_PORT=synthetic-invalid\n',
        'invalid_json': MODEL_FIELDS + 'CHROMA_SERVER_HEADERS=synthetic-invalid\n',
        'different_working_directory': MODEL_FIELDS + 'CHROMA_MEMORY_LIMIT_BYTES=104857600\n',
        'environment_then_explicit_override': MODEL_FIELDS + 'ALLOW_RESET=false\n',
    }
    results = {}
    with tempfile.TemporaryDirectory(prefix='naiyue-shared-env-') as temporary:
        root = Path(temporary)
        for name, content in cases.items():
            work = root/name; work.mkdir()
            (work/'.env').write_text(content)
            cwd = work
            if name == 'different_working_directory':
                cwd = work/'nested'; cwd.mkdir()
            env = {'HOME':str(work), 'PATH':os.defpath, 'OMP_NUM_THREADS':'1'}
            if name == 'environment_then_explicit_override': env['ALLOW_RESET'] = 'true'
            child = subprocess.run([sys.executable,'-I','-c',CHILD,str(work/'database')],
                                   cwd=cwd,env=env,capture_output=True,timeout=30)
            if child.returncode != 0:
                results[name] = {'status':'child_failed','exit_code':child.returncode,
                                 'stderr_bytes':len(child.stderr)}
            else:
                results[name] = json.loads(child.stdout)
                results[name]['stderr_bytes'] = len(child.stderr)
    expected = []
    for name, row in results.items():
        if name.startswith('invalid_'):
            expected.append(row['status']=='error' and row['error_stage']=='import')
        else:
            expected.append(row['status']=='ok' and row['written_and_read'] and
                            row['explicit_path_wins'] and row['actual_allow_reset'] is False and
                            row['actual_telemetry'] is False)
        expected.append(row['python_network_attempts']==0)
    expected.append(results['model_and_chroma']['memory_limit_from_dotenv']==104857600)
    expected.append(results['different_working_directory']['memory_limit_from_dotenv']==0)
    expected.append(results['different_working_directory']['dotenv_opens']==0)
    expected.append(results['environment_then_explicit_override']['import_allow_reset'] is True)
    report = {'date':'2026-10-15', 'sdk_version':metadata.version('chromadb'),
              'case_count':len(cases),'cases':results,'expected_checks_passed':all(expected),
              'real_project_env_reads':0,'model_calls':0,
              'native_network_observation':'unknown; client telemetry explicitly disabled',
              'scope':'synthetic same-file coexistence; actual project dotenv not validated'}
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0 if all(expected) else 1


if __name__ == '__main__':
    raise SystemExit(main())
