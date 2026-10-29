"""Direct loopback client; never resolves model credentials or follows proxies."""
import json
import re
import httpx
from .service_protocol import PROTOCOL_VERSION,configuration_identity


class LocalServiceError(ValueError):
    def __init__(self,code):
        self.code=code if type(code) is str and re.fullmatch(r'[a-z][a-z0-9_]{0,95}',code) else 'service_invalid_response'
        super().__init__(self.code)


class LocalClient:
    def __init__(self,settings):
        self.settings=settings;self.identity=configuration_identity(settings)
        self._client=httpx.Client(base_url=f'http://{settings.service.host}:{settings.service.port}',
            headers={'Authorization':'Bearer '+settings.service.access_token},trust_env=False,follow_redirects=False,
            timeout=settings.service.request_timeout_seconds)

    def _request(self,method,path,data=None,*,timeout=None):
        try:
            with self._client.stream(method,path,json=data,timeout=timeout or self.settings.service.request_timeout_seconds) as response:
                parts=[];size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>max(self.settings.service.max_request_bytes,self.settings.evidence.max_response_bytes):
                        raise LocalServiceError('service_response_limit')
                    parts.append(chunk)
                raw=json.loads(b''.join(parts))
                if response.status_code!=200:
                    code=raw.get('error',{}).get('code') if type(raw) is dict else None
                    raise LocalServiceError(code)
                if type(raw) is not dict:raise LocalServiceError('service_invalid_response')
                return raw
        except LocalServiceError:raise
        except httpx.ConnectError:raise LocalServiceError('service_unavailable') from None
        except httpx.TimeoutException:raise LocalServiceError('service_timeout') from None
        except Exception:raise LocalServiceError('service_invalid_response') from None

    def health(self,*,timeout=None):
        raw=self._request('GET','/v1/health',timeout=timeout or min(self.settings.service.request_timeout_seconds,self.settings.service.startup_timeout_seconds))
        if set(raw)!={'protocol','instance_id','config_identity'} or type(raw.get('protocol')) is not int or \
                raw['protocol']!=PROTOCOL_VERSION or raw.get('config_identity')!=self.identity or \
                type(raw.get('instance_id')) is not str or re.fullmatch('[0-9a-f]{32}',raw['instance_id']) is None:
            raise LocalServiceError('service_identity_mismatch')
        return raw

    def request(self,operation,data):
        if operation not in ('documents','document','ingest','remove','query'):raise LocalServiceError('service_invalid_request')
        if operation=='query':
            network=self.settings.service.request_timeout_seconds
            timeout=httpx.Timeout(network,read=self.settings.retrieval.request_timeout_seconds+network)
            return self._request('POST','/v1/query',data,timeout=timeout)
        return self._request('POST','/v1/'+operation,data)

    def status(self):
        raw=self._request('GET','/v1/status')
        if set(raw)!={'closed','executing','queued','draining'} or type(raw['closed']) is not bool or \
                any(type(raw[key]) is not int or raw[key]<0 for key in ('executing','queued','draining')) or \
                raw['draining']>raw['executing']:
            raise LocalServiceError('service_invalid_response')
        return raw

    def close(self):self._client.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
