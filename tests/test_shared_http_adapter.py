import asyncio
from dataclasses import replace
import json
import threading
import pytest
from test_application_runtime import runtime_job, native_query, safe_ambient, offline
from test_local_service import client_for, auth


def test_default_http_adapter_supports_concurrent_queries_and_status(runtime_job, monkeypatch):
    from naiyue_rag.encoding import OpenAICompatibleEmbedding
    _, _, cfg = runtime_job
    barrier, release = threading.Barrier(3), threading.Event()
    original = OpenAICompatibleEmbedding.embed
    def blocked(self, texts, **kwargs):
        barrier.wait(10);assert release.wait(10)
        return original(self, texts, **kwargs)
    with client_for(cfg) as client:
        assert client.post('/v1/ingest', json={'expected_revision':0}, headers=auth(cfg)).status_code == 200
        monkeypatch.setattr(OpenAICompatibleEmbedding, 'embed', blocked)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(client.post, '/v1/query', json={'query':'feature_x'}, headers=auth(cfg)) for _ in range(2)]
            try:
                barrier.wait(10)
                status = client.get('/v1/status', headers=auth(cfg))
                assert status.status_code == 200 and status.json()['executing'] == 2
                assert client.get('/v1/status').status_code == 401
                assert client.get('/v1/health', headers=auth(cfg)).status_code == 200
            finally:release.set()
            assert all(job.result(15).status_code == 200 for job in jobs)


def test_http_timeout_and_queue_overload_keep_status_available(runtime_job, monkeypatch):
    from naiyue_rag.serving.engine import RetrievalEngine
    _, _, cfg = runtime_job
    cfg = replace(cfg, retrieval=replace(cfg.retrieval,max_concurrent_queries=1,max_queued_queries=0,request_timeout_seconds=.1))
    entered, release = threading.Event(), threading.Event()
    def blocked(self, slot, control, *args, **kwargs):
        entered.set();assert release.wait(10)
        return {'status':'synthetic'}
    monkeypatch.setattr(RetrievalEngine, 'execute', blocked)
    with client_for(cfg) as client:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(client.post, '/v1/query', json={'query':'feature_x'}, headers=auth(cfg))
            try:
                assert entered.wait(5)
                assert client.post('/v1/query', json={'query':'feature_x'}, headers=auth(cfg)).status_code == 429
                timed = first.result(5)
                assert timed.status_code == 504 and timed.json()['error']['code'] == 'retrieval_timeout'
                assert client.get('/v1/status',headers=auth(cfg)).json()['draining'] == 1
            finally:release.set()


def test_document_detail_remove_and_query_scope_http_roundtrip(runtime_job):
    _, _, cfg = runtime_job
    with client_for(cfg) as client:
        client.post('/v1/ingest', json={'expected_revision':0}, headers=auth(cfg)).raise_for_status()
        listing = client.post('/v1/documents',json={},headers=auth(cfg)).json()
        document_id = listing['documents'][0]['document_id']
        detail = client.post('/v1/document',json={'document_id':document_id,'expected_revision':1},headers=auth(cfg))
        assert detail.status_code == 200 and detail.json()['document']['document_id'] == document_id
        missing_revision = client.post('/v1/remove',json={'document_id':document_id},headers=auth(cfg))
        assert missing_revision.status_code == 400
        from pathlib import Path
        source=Path(cfg.knowledge_base_root)
        source.rename(source.with_name('source-offline'))
        removed = client.post('/v1/remove',json={'document_id':document_id,'expected_revision':1},headers=auth(cfg))
        assert removed.status_code == 200 and removed.json()['status'] == 'removed'
        assert removed.json()['active']['revision'] == 2
        assert client.post('/v1/remove',json={'document_id':document_id,'expected_revision':1},headers=auth(cfg)).status_code == 409


def test_authenticated_partial_body_has_configured_timeout(runtime_job):
    from naiyue_rag.service import LocalBoundary
    _, _, cfg = runtime_job
    cfg = replace(cfg,service=replace(cfg.service,request_timeout_seconds=.05))
    async def run():
        sent=[];calls=0;never=asyncio.Event()
        async def receive():
            nonlocal calls
            calls+=1
            if calls==1:return {'type':'http.request','body':b'{','more_body':True}
            await never.wait()
        async def send(message):sent.append(message)
        async def app(*args):raise AssertionError('incomplete body reached handler')
        scope={'type':'http','headers':[(b'host',b'127.0.0.1'),
            (b'authorization',('Bearer '+cfg.service.access_token).encode())]}
        await asyncio.wait_for(LocalBoundary(app,cfg)(scope,receive,send),3)
        assert sent[0]['status']==408
    asyncio.run(run())


def test_parallel_updates_fail_fast_without_blocking_document_reads(runtime_job,monkeypatch):
    from naiyue_rag.runtime import ApplicationRuntime
    from concurrent.futures import ThreadPoolExecutor
    _,_,cfg=runtime_job;entered=threading.Event();release=threading.Event()
    def blocked(self,**kwargs):
        entered.set();assert release.wait(10)
        return {'status':'synthetic_ingested'}
    monkeypatch.setattr(ApplicationRuntime,'ingest',blocked)
    with client_for(cfg) as client, ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(client.post,'/v1/ingest',json={'expected_revision':0},headers=auth(cfg))
        try:
            assert entered.wait(5)
            second=pool.submit(client.post,'/v1/ingest',json={'expected_revision':0},headers=auth(cfg))
            response=second.result(3)
            assert response.status_code==409 and response.json()['error']['code']=='retrieval_update_busy'
            removed=client.post('/v1/remove',json={'document_id':'doc-'+'a'*64,'expected_revision':0},headers=auth(cfg))
            assert removed.status_code==409
            assert client.post('/v1/documents',json={},headers=auth(cfg)).status_code==200
        finally:release.set()
        assert first.result(5).status_code==200
