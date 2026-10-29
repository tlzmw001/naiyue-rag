"""One OpenAI-compatible request with explicit configuration and bounded HTTP IO."""
import json
import logging
import os
import threading
import time
import httpx
from ..core.encoding_settings import validate_encoding_settings
from ..core.errors import EmbeddingExecutionError
from .bounded_transport import BoundedTransport,BoundaryFailure
from .execution_report import new_report,raise_execution_error,valid_seconds
from ..serving.control import remaining_timeout,RetrievalError

LOGGER=logging.getLogger(__name__)

def _check_environment(report):
    # This guard reads no credential values and changes no global logging policy.
    if 'OPENAI_CUSTOM_HEADERS' in os.environ or os.environ.get('OPENAI_LOG') in ('debug','info'):
        raise_execution_error('embedding_unsafe_sdk_environment',report)
    for name,level in [('openai._base_client',logging.DEBUG),('openai._response',logging.DEBUG),
                       ('httpx',logging.INFO),('httpcore.connection',logging.DEBUG),
                       ('httpcore.http11',logging.DEBUG),('httpcore.http2',logging.DEBUG),
                       ('httpcore.proxy',logging.DEBUG)]:
        if logging.getLogger(name).isEnabledFor(level):
            raise_execution_error('embedding_unsafe_sdk_environment',report)


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError()
        result[key]=value
    return result


def _nonstandard_constant(value):raise ValueError()


class OpenAICompatibleEmbedding:
    def __init__(self,settings,*,api_key):
        validate_encoding_settings(settings)
        report=new_report();_check_environment(report)
        if type(api_key) is not str or not api_key.strip() or any(ord(c)<33 or ord(c)>126 for c in api_key):
            raise_execution_error('embedding_invalid_credential',report)
        self.settings=settings;self._closed=False;self._close_failed=False;self._lock=threading.Lock()
        self._http=None;self._client=None;self._transport=None
        try:
            # Import after environment checks: SDK import may honor OPENAI_LOG.
            import openai
            self._sdk=openai
            self._transport=BoundedTransport(httpx.HTTPTransport(retries=0,trust_env=False),settings.runtime.max_response_bytes)
            self._http=httpx.Client(transport=self._transport,trust_env=False,follow_redirects=False,
                                    timeout=settings.runtime.timeout_seconds)
            self._client=openai.OpenAI(api_key=api_key,base_url=settings.embedding.base_url,
                admin_api_key='',organization='',project='',webhook_secret='',
                max_retries=0,timeout=settings.runtime.timeout_seconds,http_client=self._http,
                default_headers={'Accept-Encoding':'identity','OpenAI-Organization':openai.Omit(),
                                 'OpenAI-Project':openai.Omit()})
        except Exception:
            resource=self._http if self._http is not None else self._transport
            if resource is not None:
                try:resource.close()
                except Exception:
                    report['client_close_error_code']='embedding_client_close_failed'
                    LOGGER.error('embedding_execution_failed code=embedding_client_close_failed')
            raise_execution_error('embedding_initialization_failed',report)

    @property
    def closed(self):return self._closed

    def embed(self,texts,*,timeout_seconds):
        report=new_report();start=time.monotonic()
        if not self._lock.acquire(blocking=False):raise_execution_error('embedding_provider_busy',report)
        try:
            if self.closed:raise_execution_error('embedding_provider_closed',report)
            _check_environment(report)
            if not valid_seconds(timeout_seconds):raise_execution_error('embedding_invalid_timeout',report)
            timeout_seconds=remaining_timeout(timeout_seconds)
            if type(texts) is not list or not texts or len(texts)>min(self.settings.runtime.batch_size,self.settings.runtime.max_inputs):
                raise_execution_error('embedding_invalid_batch',report)
            sizes=[]
            try:
                for text in texts:
                    if type(text) is not str or not text.strip():raise ValueError()
                    sizes.append(len(text.encode('utf-8')))
            except (ValueError,UnicodeError):raise_execution_error('embedding_invalid_batch',report)
            if max(sizes)>self.settings.runtime.max_input_utf8_bytes or sum(sizes)>self.settings.runtime.max_batch_input_utf8_bytes:
                raise_execution_error('encoding_input_limit',report)
            deadline=start+min(timeout_seconds,self.settings.runtime.deadline_seconds)
            self._transport.begin(report,deadline)
            remaining=deadline-time.monotonic()
            if remaining<=0:raise_execution_error('embedding_deadline_exceeded',report)
            kwargs={'input':list(texts),'model':self.settings.embedding.model,'encoding_format':'float',
                    'timeout':min(remaining,self.settings.runtime.timeout_seconds)}
            if self.settings.embedding.request_dimensions is not None:
                kwargs['dimensions']=self.settings.embedding.request_dimensions
            with self._client.embeddings.with_streaming_response.create(**kwargs) as response:
                body=b''.join(response.iter_bytes())
            if time.monotonic()>=deadline:raise_execution_error('embedding_deadline_exceeded',report)
            try:
                payload=json.loads(body.decode('utf-8'),object_pairs_hook=_unique_object,
                                   parse_constant=_nonstandard_constant)
                if type(payload) is not dict:raise ValueError()
            except (ValueError,UnicodeError,RecursionError):raise_execution_error('embedding_invalid_json',report)
            if time.monotonic()>=deadline:raise_execution_error('embedding_deadline_exceeded',report)
            report['elapsed_seconds']=max(0.,time.monotonic()-start)
            return payload,report.copy()
        except RetrievalError:
            raise
        except EmbeddingExecutionError as error:
            error.report['elapsed_seconds']=max(0.,time.monotonic()-start)
            raise
        except Exception as error:
            report['elapsed_seconds']=max(0.,time.monotonic()-start)
            code=report['error_code']
            if isinstance(error,BoundaryFailure):code=error.code
            elif code is None:
                if isinstance(error,(self._sdk.APITimeoutError,httpx.TimeoutException)):code='embedding_timeout'
                elif isinstance(error,self._sdk.APIStatusError):code=f'embedding_http_{error.status_code}'
                elif isinstance(error,(self._sdk.APIConnectionError,httpx.TransportError)):code='embedding_connection_failed'
                else:code='embedding_request_failed'
            raise_execution_error(code,report)
        finally:self._lock.release()

    def close(self):
        report=new_report()
        if not self._lock.acquire(blocking=False):raise_execution_error('embedding_provider_busy',report)
        try:
            if self.closed and not self._close_failed:return
            self._closed=True
            try:self._client.close()
            except Exception:
                self._close_failed=True
                report['client_close_error_code']='embedding_client_close_failed'
                raise_execution_error('embedding_client_close_failed',report)
            self._close_failed=False
        finally:self._lock.release()

    def __enter__(self):
        if self.closed:raise_execution_error('embedding_provider_closed',new_report())
        return self

    def __exit__(self,exc_type,exc,tb):
        try:self.close()
        except EmbeddingExecutionError:
            if exc is None:raise
            if isinstance(exc,EmbeddingExecutionError):exc.report['client_close_error_code']='embedding_client_close_failed'
        return False
