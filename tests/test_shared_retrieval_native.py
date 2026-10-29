"""Actual Chroma/BM25, ten requests and concurrent publication, in an isolated process."""
import json
import os
from pathlib import Path
import subprocess
import sys


def native(root):
    import threading
    import httpx
    from naiyue_rag import load_application_settings
    from naiyue_rag.serving import RetrievalService
    from naiyue_rag.encoding import OpenAICompatibleEmbedding
    from test_storage_bundle import ingredients
    from test_model_registry import settings_at
    from test_application_settings import write
    from test_openai_embedding import payload
    ingredients(root)
    cfg = settings_at(root);raw = cfg.to_dict()
    raw['rerank'].update(backend='none', model=None)
    cfg = load_application_settings(write(root / 'config.yaml', raw))
    def response(request):
        return httpx.Response(200, json=payload(len(json.loads(request.content)['input'])))
    httpx.HTTPTransport = lambda **kwargs: httpx.MockTransport(response)
    barrier, release, entered_old, release_old = threading.Barrier(3), threading.Event(), threading.Event(), threading.Event()
    original = OpenAICompatibleEmbedding.embed
    started = [];lock = threading.Lock();enabled = False
    def tracked(self, texts, **kwargs):
        if enabled:
            if any('hold_query' in text for text in texts):
                entered_old.set();assert release_old.wait(15)
            else:
                with lock:
                    started.append(id(self));number = len(started)
                if number <= 2:
                    barrier.wait(10);assert release.wait(10)
        return original(self, texts, **kwargs)
    OpenAICompatibleEmbedding.embed = tracked
    try:
        with RetrievalService(cfg) as service:
            service.ingest(expected_revision=0)
            enabled = True
            handles = [service.submit('feature_x TC-01') for _ in range(10)]
            try:
                barrier.wait(10)
                assert service.status()['executing'] == 2
                assert service.status()['queued'] == 8
                assert len(set(started)) == 2
            finally:
                release.set()
            results = [h.result(20) for h in handles]
            assert all(h.wait_backend(10) for h in handles)
            assert all(r['evidence'] == results[0]['evidence'] for r in results) and results[0]['evidence']
            import naiyue_rag.storage.artifact_bundle_v2 as bundle
            prepare = bundle.prepare_knowledge_base
            def forbid(*args, **kwargs):raise AssertionError('warm corpus replay')
            bundle.prepare_knowledge_base = forbid
            try:assert service.query('feature_x')['evidence']
            finally:bundle.prepare_knowledge_base = prepare
            old = service.submit('hold_query feature_x')
            try:
                assert entered_old.wait(10)
                enabled = False
                source = next(Path(cfg.knowledge_base_root).rglob('*.md'))
                source.write_text(source.read_text() + '\nUpdated native acceptance material.\n')
                assert service.ingest(expected_revision=1)['active']['revision'] == 2
                assert service.query('feature_x')['active']['revision'] == 2
            finally:release_old.set()
            assert old.result(15)['active']['revision'] == 1
            assert old.wait_backend(10)
    finally:
        release.set();release_old.set();OpenAICompatibleEmbedding.embed = original
    from naiyue_rag.serving.benchmark import benchmark
    report = benchmark(cfg, 'feature_x', requests=10)
    assert report['status'] == 'passed' and report['completed'] == report['admitted'] == 10
    assert report['errors'] == {} and report['revisions'] == [2]
    print(json.dumps(dict(status='passed', accepted=10, returned=10, overlap=2,
                          warm_corpus_replays=0, old_revision=1, new_revision=2,
                          benchmark_completed=report['completed'])))


def test_real_shared_service_ten_requests_and_concurrent_publication(tmp_path):
    project = Path(__file__).resolve().parents[1]
    script = """
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_shared_retrieval_native import native
native(Path(sys.argv[2]))
"""
    result = subprocess.run([sys.executable, '-I', '-c', script, str(project), str(tmp_path)],
        cwd=tmp_path, env={'HOME': str(tmp_path), 'PATH': os.defpath, 'OMP_NUM_THREADS': '1'},
        text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['returned'] == report['accepted'] == 10 and report['overlap'] == 2
