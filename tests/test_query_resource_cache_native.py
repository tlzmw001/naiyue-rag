"""Real Chroma/BM25 reuse, isolated from process-wide test doubles."""
import json
import os
from pathlib import Path
import subprocess
import sys


def native(root):
    import httpx
    from naiyue_rag import load_application_settings
    from naiyue_rag.runtime import ApplicationRuntime
    from test_storage_bundle import ingredients
    from test_model_registry import settings_at
    from test_application_settings import write
    from test_openai_embedding import payload
    import naiyue_rag.storage.artifact_bundle_v2 as bundle
    ingredients(root)
    cfg = settings_at(root)
    data = cfg.to_dict()
    data['rerank']['backend'] = 'none'
    data['rerank']['model'] = None
    write(root / 'config.yaml', data)
    cfg = load_application_settings(root / 'config.yaml')
    httpx.HTTPTransport = lambda **kwargs: httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload(len(json.loads(request.content)['input']))))
    with ApplicationRuntime(cfg) as runtime:
        runtime.ingest(expected_revision=0)
        first = runtime.query('feature_x')
        assert runtime._resources.values, 'native reads changed artifact state during query'
        calls = []
        original = bundle.prepare_knowledge_base
        def tracked(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        bundle.prepare_knowledge_base = tracked
        second = runtime.query('feature_x')
        assert second['evidence'] == first['evidence']
        assert calls == [], len(calls)
        assert runtime._resources.values
    print(json.dumps(dict(status='passed', warm_corpus_replays=len(calls), evidence=len(first['evidence']))))


def test_real_indexes_reuse_warm_version(tmp_path):
    project = Path(__file__).resolve().parents[1]
    script = """
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_query_resource_cache_native import native
native(Path(sys.argv[2]))
"""
    child = subprocess.run([sys.executable, '-I', '-c', script, str(project), str(tmp_path)],
                           cwd=tmp_path, env={'HOME': str(tmp_path), 'PATH': os.defpath, 'OMP_NUM_THREADS': '1'},
                           text=True, capture_output=True, timeout=90)
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout)['warm_corpus_replays'] == 0
