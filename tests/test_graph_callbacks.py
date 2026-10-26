import asyncio
import importlib
import json

import pytest

from test_graph_transport import settings,completion


@pytest.fixture
def mod():return importlib.import_module('experiments.graph_callbacks')


def test_exact_success_cache_replay_and_failure_no_retry(mod,tmp_path):
    cfg=settings(tmp_path);calls=[]
    async def scenario():
        journal=mod.Journal(tmp_path/'cache',cfg,'live')
        async def send():calls.append('call');return completion()
        def parse(p):return p['choices'][0]['message']['content']
        body={'messages':['same']}
        first=await journal.request('chat','extract_initial',body,send,parse)
        assert await journal.request('chat','extract_initial',body,send,parse)==first
        replay=mod.Journal(tmp_path/'cache',cfg,'replay')
        assert await replay.request('chat','extract_initial',body,send,parse)==first
        async def fail():calls.append('failed');raise mod.ProbeError('http','http_error',429)
        with pytest.raises(mod.ProbeError):await journal.request('chat','keyword',{'x':1},fail,parse)
        with pytest.raises(mod.ProbeError):await journal.request('chat','keyword',{'x':1},fail,parse)
        assert calls==['call','failed'] and journal.summary()['failed_requests']==1
    asyncio.run(scenario())


def test_malformed_completion_keeps_usage_and_poisoned_state(mod,tmp_path):
    async def scenario():
        journal=mod.Journal(tmp_path/'cache',settings(tmp_path),'live')
        async def send():return completion()
        def reject(p):raise mod.ProbeError('response','invalid_completion')
        with pytest.raises(mod.ProbeError):await journal.request('chat','extract_initial',{},send,reject)
        summary=journal.summary()
        assert summary['known_usage']['chat']['prompt_tokens']==10
        assert summary['failed_requests']==1 and summary['chat_requests']==1
    asyncio.run(scenario())


def test_intent_io_failure_never_calls_service(mod,tmp_path,monkeypatch):
    calls=[];cfg=settings(tmp_path)
    async def scenario():
        journal=mod.Journal(tmp_path/'cache',cfg,'live')
        def fail(*a,**k):raise mod.ProbeError('output','output_error')
        monkeypatch.setattr(journal,'append',fail)
        async def send():calls.append('called');return completion()
        with pytest.raises(mod.ProbeError):await journal.request('chat','keyword',{},send,lambda p:p)
        assert calls==[]
    asyncio.run(scenario())


def test_replay_miss_and_corrupt_success_are_errors(mod,tmp_path):
    cfg=settings(tmp_path)
    async def scenario():
        journal=mod.Journal(tmp_path/'cache',cfg,'live')
        async def send():return completion()
        await journal.request('chat','extract_initial',{},send,lambda p:'text')
        cache=next((tmp_path/'cache').glob('success-*.json'));cache.write_text('{}')
        with pytest.raises(mod.ProbeError):await journal.request('chat','extract_initial',{},send,lambda p:'text')
        replay=mod.Journal(tmp_path/'cache',cfg,'replay')
        with pytest.raises(mod.ProbeError):await replay.request('chat','keyword',{'new':True},send,lambda p:p)
    asyncio.run(scenario())


def test_global_limit_and_simultaneous_exact_request_single_call(mod,tmp_path):
    cfg=settings(tmp_path);cfg['max_chat_requests']=1;calls=[]
    async def scenario():
        journal=mod.Journal(tmp_path/'cache',cfg,'live');ready=asyncio.Event()
        async def send():calls.append(1);await ready.wait();return completion()
        one=asyncio.create_task(journal.request('chat','keyword',{},send,lambda p:'ok'))
        two=asyncio.create_task(journal.request('chat','keyword',{},send,lambda p:'ok'))
        await asyncio.sleep(0);ready.set()
        assert await one==await two=='ok' and len(calls)==1
        with pytest.raises(mod.ProbeError):await journal.request('chat','keyword',{'different':1},send,lambda p:'ok')
    asyncio.run(scenario())


def test_async_native_validation_finishes_before_success_cache(mod,tmp_path):
    async def scenario():
        journal=mod.Journal(tmp_path/'cache',settings(tmp_path),'live')
        async def send():return completion()
        async def reject(payload):raise mod.ProbeError('protocol','native_parser_dropped_records')
        with pytest.raises(mod.ProbeError,match='native_parser_dropped_records'):
            await journal.request('chat','extract_initial',{},send,reject)
        assert not list((tmp_path/'cache').glob('success-*.json'))
        assert journal.summary()['failed_requests']==1
    asyncio.run(scenario())


def test_uncommitted_success_file_is_not_replayed(mod,tmp_path,monkeypatch):
    cfg=settings(tmp_path)
    async def scenario():
        journal=mod.Journal(tmp_path/'cache',cfg,'live');old=journal.append
        def append(event):
            if event['status']=='success':raise mod.ProbeError('output','output_error')
            old(event)
        monkeypatch.setattr(journal,'append',append)
        async def send():return completion()
        with pytest.raises(mod.ProbeError):await journal.request('chat','keyword',{},send,lambda p:'ok')
        assert list((tmp_path/'cache').glob('success-*.json'))
        replay=mod.Journal(tmp_path/'cache',cfg,'replay')
        with pytest.raises(mod.ProbeError):await replay.request('chat','keyword',{},send,lambda p:'ok')
    asyncio.run(scenario())
