"""Small closed local HTTP contract, independent of framework validation echoes."""
import hashlib
import json
from .core.errors import SettingsError,StorageError,IngestionJobError,QueryJobError
from .reranking.report import RerankError
from .response.builder import EvidenceError
from .serving.control import RetrievalError

PROTOCOL_VERSION=1


def configuration_identity(settings,registry=None):
    from .core.model_registry import load_model_registry
    registry=registry or load_model_registry(settings)
    wire=json.dumps({'settings':settings.to_dict(),'models_identity':registry.identity,
        'execution_contract':'shared-retrieval-v1'},sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    return hashlib.sha256(wire.encode('utf-8')).hexdigest()


def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError()
        value[key]=item
    return value


def parse_request(body,operation):
    try:
        def invalid(value):raise ValueError()
        data=json.loads(body.decode('utf-8'),object_pairs_hook=_unique,parse_constant=invalid)
        required={'query'} if operation=='query' else {'expected_revision'} if operation=='ingest' else \
            {'document_id','expected_revision'} if operation=='remove' else {'document_id'} if operation=='document' else set()
        allowed={'query','scope_document_ids','exclude_document_ids','expected_revision'} if operation=='query' else \
            {'expected_revision','force'} if operation=='ingest' else \
            {'document_id','expected_revision'} if operation in ('document','remove') else {'expected_revision'}
        if type(data) is not dict or not required<=set(data) or set(data)-allowed:raise ValueError()
        revision=data.get('expected_revision')
        if revision is not None and (type(revision) is not int or revision<0):raise ValueError()
        if 'force' in data and type(data['force']) is not bool:raise ValueError()
        if operation in ('document','remove'):
            from .storage.document_views import _valid_document_id
            if not _valid_document_id(data['document_id']):raise ValueError()
            if operation=='remove' and revision is None:raise ValueError()
        if operation=='query':
            if type(data['query']) is not str or not data['query'].strip():raise ValueError()
            for field in ('scope_document_ids','exclude_document_ids'):
                ids=data.get(field)
                if ids is not None and (type(ids) is not list or any(type(v) is not str or not v for v in ids)):raise ValueError()
        return data
    except Exception:raise SettingsError('service_invalid_request') from None


def error_response(error):
    if type(error) is RetrievalError:
        detail={'code':error.code}
        status={'retrieval_timeout':504,'retrieval_overloaded':429,'retrieval_cancelled':409,
            'retrieval_invalid_request':400,'retrieval_update_busy':409}.get(error.code,503)
    elif type(error) in (IngestionJobError,QueryJobError,RerankError,EvidenceError):
        detail=error.to_dict();status=409 if detail['code'] in ('catalog_revision_conflict','catalog_busy') else 422
    elif type(error) is StorageError:
        detail={'code':error.code};status=409 if error.code in ('catalog_revision_conflict','catalog_busy') else 422
    elif type(error) is SettingsError and error.code in {
            'application_busy','application_closed','model_credential_invalid','model_selection_invalid','service_invalid_request'}:
        detail={'code':error.code};status=409 if error.code=='application_busy' else 400
    else:detail={'code':'service_internal_error'};status=500
    return status,{'error':detail}
