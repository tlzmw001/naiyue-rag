"""Opt-in trace persistence that preserves the original retrieval outcome."""
import logging

from .core.errors import RetrievalError, TraceError
from .core.trace_collector import TraceCollector
from .retrieval import retrieve_once

LOGGER = logging.getLogger(__name__)


def _persist(collector, report):
    try:
        collector.collect(report)
    except TraceError:
        LOGGER.error('trace_failed trace_id=%s code=trace_write_failed', report['trace_id'])
        return {'status':'failed', 'code':'trace_write_failed'}
    return {'status':'written', 'code':None}


def retrieve_with_trace(request, resources, embed_query, collector):
    """Collect exactly once; trace storage failure never masks query results."""
    if not isinstance(collector, TraceCollector):
        raise TraceError('invalid_trace') from None
    try:
        result = retrieve_once(request, resources, embed_query)
    except RetrievalError as error:
        error.trace_persistence = _persist(collector, error.trace_report)
        raise
    result['trace_persistence'] = _persist(collector, result['trace_report'])
    return result
