"""Small explicit observation contract shared by request and Dense boundaries."""
import logging
import math
from ..core.errors import EmbeddingExecutionError

LOGGER=logging.getLogger(__name__)


def new_report():
    return {'attempted_requests':0,'http_status':None,'response_bytes':0,
            'elapsed_seconds':0.,'error_code':None,'response_close_error_code':None,
            'client_close_error_code':None}


def valid_seconds(value):
    try:return type(value) in (int,float) and math.isfinite(value) and value>0
    except OverflowError:return False


def raise_execution_error(code,report):
    report['error_code']=code
    LOGGER.error('embedding_execution_failed code=%s',code)
    raise EmbeddingExecutionError(code,report) from None
