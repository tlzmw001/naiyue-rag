"""Authenticated loopback HTTP adapter; RAG work stays in the existing runtime."""
from contextlib import asynccontextmanager
import hmac
import logging
from urllib.parse import urlsplit
import uuid
from fastapi import FastAPI,Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from .runtime import ApplicationRuntime
from .service_protocol import PROTOCOL_VERSION,configuration_identity,parse_request,error_response

LOGGER=logging.getLogger(__name__)


class LocalBoundary:
    def __init__(self,app,settings):self.app=app;self.settings=settings

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers={}
        for key,value in scope['headers']:headers.setdefault(key.lower(),[]).append(value)
        async def reject(status,code):
            LOGGER.warning('service_request_rejected code=%s',code)
            await JSONResponse({'error':{'code':code}},status_code=status)(scope,receive,send)
        auth=headers.get(b'authorization',[])
        expected=('Bearer '+self.settings.service.access_token).encode('ascii')
        if len(auth)!=1 or not hmac.compare_digest(auth[0],expected):return await reject(401,'service_unauthorized')
        try:
            hosts=headers.get(b'host',[])
            host=urlsplit('http://'+hosts[0].decode('ascii')) if len(hosts)==1 else None
            local=host is not None and host.hostname in ('127.0.0.1','localhost') and not host.username and not host.password \
                and not host.path and not host.query and not host.fragment
        except Exception:local=False
        if not local or b'origin' in headers:return await reject(403,'service_local_access_required')
        parts=[];size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            chunk=message.get('body',b'');size+=len(chunk)
            if size>self.settings.service.max_request_bytes:return await reject(413,'service_request_limit')
            parts.append(chunk)
            if not message.get('more_body',False):break
        delivered=False
        async def buffered():
            nonlocal delivered
            if not delivered:
                delivered=True;return {'type':'http.request','body':b''.join(parts),'more_body':False}
            return await receive()
        started=False
        async def tracked(message):
            nonlocal started
            if message['type']=='http.response.start':started=True
            await send(message)
        try:await self.app(scope,buffered,tracked)
        except Exception as error:
            status,result=error_response(error)
            LOGGER.error('service_request_failed code=%s',result['error']['code'])
            if not started:await JSONResponse(result,status_code=status)(scope,buffered,send)


def create_service(settings,*,runtime_factory=ApplicationRuntime,instance_id=None):
    instance_id=instance_id or uuid.uuid4().hex
    @asynccontextmanager
    async def lifespan(app):
        with runtime_factory(settings) as runtime:
            app.state.runtime=runtime
            app.state.identity=configuration_identity(settings,runtime.registry)
            yield
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(LocalBoundary,settings=settings)

    @app.get('/v1/health')
    async def health():
        return dict(protocol=PROTOCOL_VERSION,instance_id=instance_id,config_identity=app.state.identity)

    async def execute(request,operation):
        if request.headers.get('content-type','').split(';')[0].strip().lower()!='application/json':
            return JSONResponse({'error':{'code':'service_json_required'}},status_code=415)
        data=parse_request(await request.body(),operation)
        return await run_in_threadpool(getattr(request.app.state.runtime,operation),**data)

    @app.post('/v1/documents')
    async def documents(request:Request):return await execute(request,'documents')

    @app.post('/v1/ingest')
    async def ingest(request:Request):return await execute(request,'ingest')

    @app.post('/v1/query')
    async def query(request:Request):return await execute(request,'query')
    return app


def run_service(settings,*,parent_watch=False,instance_id=None):
    import re
    import signal
    import sys
    import threading
    import uvicorn
    from .local_client import LocalServiceError
    if instance_id is not None and (not parent_watch or re.fullmatch('[0-9a-f]{32}',instance_id) is None):
        raise LocalServiceError('service_invalid_request')
    config=uvicorn.Config(create_service(settings,instance_id=instance_id),host=settings.service.host,port=settings.service.port,
        loop='asyncio',http='h11',workers=1,reload=False,proxy_headers=False,
        access_log=False,log_level='warning',timeout_graceful_shutdown=settings.service.shutdown_timeout_seconds)
    server=uvicorn.Server(config)
    if parent_watch:
        def watch():
            try:sys.stdin.buffer.read()
            except Exception:LOGGER.error('service_parent_failed code=service_parent_pipe_failed')
            finally:server.should_exit=True
        threading.Thread(target=watch,daemon=True,name='nyr-parent-watch').start()
    previous=None
    handles_break=hasattr(signal,'SIGBREAK') and threading.current_thread() is threading.main_thread()
    if handles_break:
        def stop(signum,frame):server.should_exit=True
        previous=signal.signal(signal.SIGBREAK,stop)
    try:server.run()
    finally:
        if handles_break:signal.signal(signal.SIGBREAK,previous)
