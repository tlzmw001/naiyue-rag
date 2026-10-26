"""A synchronous HTTP boundary protecting both SDK success and eager error reads."""
import logging
import sys
import time
import httpx

LOGGER=logging.getLogger(__name__)


class BoundaryFailure(Exception):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def _fail(code,report):
    report['error_code']=code
    raise BoundaryFailure(code) from None


def _close_response(response,report,*,suppress):
    try:response.close()
    except Exception:
        code='embedding_response_close_failed'
        report['response_close_error_code']=code
        LOGGER.error('embedding_execution_failed code=%s',code)
        if not suppress:_fail(code,report)


class _BoundedBody(httpx.SyncByteStream):
    def __init__(self,response,limit,report,deadline):
        self.response=response;self.limit=limit;self.report=report;self.deadline=deadline
        self.closed=False

    def __iter__(self):
        try:
            for chunk in self.response.stream:
                self.report['response_bytes']+=len(chunk)
                if time.monotonic()>=self.deadline:_fail('embedding_deadline_exceeded',self.report)
                if self.report['response_bytes']>self.limit:_fail('embedding_response_too_large',self.report)
                yield chunk
        finally:self.close()

    def close(self):
        if self.closed:return
        self.closed=True
        _close_response(self.response,self.report,
                        suppress=self.report['error_code'] is not None or sys.exc_info()[0] is not None)


class BoundedTransport(httpx.BaseTransport):
    def __init__(self,transport,limit):
        self.transport=transport;self.limit=limit;self.report=None;self.deadline=None

    def begin(self,report,deadline):
        self.report=report;self.deadline=deadline

    def handle_request(self,request):
        report=self.report
        if report is None:raise BoundaryFailure('embedding_transport_not_bound')
        if time.monotonic()>=self.deadline:_fail('embedding_deadline_exceeded',report)
        report['attempted_requests']+=1
        response=self.transport.handle_request(request)
        report['http_status']=response.status_code
        if response.status_code>=300:report['error_code']=f'embedding_http_{response.status_code}'
        try:
            if time.monotonic()>=self.deadline:_fail('embedding_deadline_exceeded',report)
            encoding=response.headers.get('content-encoding','identity').strip().lower()
            if encoding!='identity':_fail('embedding_unsupported_content_encoding',report)
            length=response.headers.get('content-length')
            if length is not None:
                if not length.isascii() or not length.isdecimal():_fail('embedding_invalid_response_headers',report)
                if len(length)>20 or int(length)>self.limit:_fail('embedding_response_too_large',report)
            body=_BoundedBody(response,self.limit,report,self.deadline)
            return httpx.Response(response.status_code,headers=response.headers,stream=body,
                                  extensions=response.extensions)
        except Exception:
            _close_response(response,report,suppress=True)
            raise

    def close(self):self.transport.close()
