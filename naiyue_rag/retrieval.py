"""One request through existing A2 retrieval, with explicit scope and safe failures."""
import copy
import hashlib
import logging

from experiments.embedding_probe import ProbeError, validate_vectors, validate_usage
from experiments.rank_fusion import fuse
from experiments.vector_index import pack_evidence
from .core.errors import ContractError, RetrievalError
from .core.types import QueryRequest, RetrievalResult, REQUEST_FIELDS
from .core.trace_context import TraceContext, STAGES

LOGGER = logging.getLogger(__name__)


def _validate_request(request):
    return QueryRequest.from_dict(request).to_dict()


def _contract_rows(rows):
    return [RetrievalResult.from_candidate(row).to_candidate() for row in rows]


def _embedding(query, identity, embed_query):
    if not callable(embed_query):
        raise RetrievalError('embedding', 'invalid_embedding_adapter')
    try:
        payload = embed_query(query, copy.deepcopy(identity))
    except Exception:
        raise RetrievalError('embedding', 'embedding_failed') from None
    try:
        required = {'query_sha256', 'embedding_identity', 'vector', 'source_kind'}
        if type(payload) is not dict or not required <= set(payload) or set(payload) - required - {'usage'}:
            raise ValueError('schema')
        if payload['query_sha256'] != hashlib.sha256(query.encode()).hexdigest() or \
                payload['embedding_identity'] != identity or payload['source_kind'] not in (
                    'cached', 'simulated', 'service', 'unknown'):
            raise ValueError('binding')
        validate_vectors({'model': identity['model'], 'data': [{'index': 0, 'embedding': payload['vector']}]},
                         1, identity['dimensions'], identity['model'])
        if payload.get('usage') is not None:
            validate_usage(payload['usage'])
        return copy.deepcopy(payload)
    except (ProbeError, ValueError, TypeError, KeyError, OverflowError):
        raise RetrievalError('embedding', 'invalid_query_embedding') from None


def retrieve_once(request, resources, embed_query):
    """Return complete evidence; adapter calls and source declarations are not API proofs."""
    from .a2_snapshot import A2Snapshot
    trace = []
    stage = 'request'
    context = TraceContext()

    def record(name, **details):
        safe = details
        if name == 'embedding' and details['usage'] is not None:
            safe = {**details, 'usage':validate_usage(details['usage'])}
        elapsed = context.record_stage(name, safe)
        trace.append({'stage':name, 'elapsed_ms':elapsed, **details})

    def failed(error):
        error_stage = error.stage if error.stage in STAGES else stage
        context.finish('error', error_stage=error_stage, error_code=error.code)
        error.trace_report = context.to_dict()
        LOGGER.error('retrieval_failed trace_id=%s stage=%s code=%s', context.trace_id,
                     error.trace_report['error']['stage'], error.trace_report['error']['code'])

    try:
        req = _validate_request(request)
        if not isinstance(resources, A2Snapshot):
            raise RetrievalError('resources', 'invalid_resources')
        scope = resources.resolve_scope(req['scope_document_ids'], req['exclude_document_ids'])
        exclusions = req['exclude_document_ids']
        record('request', status='validated')
        stage = 'resources'
        resources.verify_current()
        record('resources', status='verified', corpus_id=resources.fingerprint, index_id=resources.index_id)
        stage = 'embedding'
        payload = _embedding(req['query'], resources.embedding_identity, embed_query)
        record('embedding', adapter_calls=1, source_kind=payload['source_kind'], usage=payload.get('usage'))
        stage = 'dense'
        dense = resources.dense(payload['vector'], scope, exclusions, req['candidate_k'])
        dense['candidates'] = _contract_rows(dense['candidates'])
        record('dense', compared_count=dense['compared_count'], candidate_count=len(dense['candidates']))
        stage = 'sparse'
        sparse = resources.sparse(req['query'], scope, exclusions, req['candidate_k'])
        sparse['candidates'] = _contract_rows(sparse['candidates'])
        record('sparse', compared_count=sparse['compared_count'], candidate_count=len(sparse['candidates']))
        stage = 'fusion'
        fused = fuse(dense['candidates'], sparse['candidates'], resources.canonical_units(),
                     resources.config['rrf_k'], req['candidate_k'])
        fused['candidates'] = _contract_rows(fused['candidates'])
        fused['union_candidates'] = _contract_rows(fused['union_candidates'])
        record('fusion', union_count=len(fused['union_candidates']), candidate_count=len(fused['candidates']))
        stage = 'packing'
        dense = {**dense, **pack_evidence(dense['candidates'], req['max_context_chars'])}
        sparse = {**sparse, **pack_evidence(sparse['candidates'], req['max_context_chars'])}
        hybrid = {'candidates': fused['candidates'],
                  **pack_evidence(fused['candidates'], req['max_context_chars'])}
        record('packing', selected_count=len(hybrid['selected']), status=hybrid['status'],
               context_characters=hybrid['context_characters'])
        context.finish('success')
        return copy.deepcopy({'query': req['query'], 'scope_document_ids': scope,
            'exclude_document_ids': exclusions, 'candidate_k': req['candidate_k'],
            'corpus_id': resources.fingerprint, 'index_id': resources.index_id,
            'dense': dense, 'sparse': sparse, 'hybrid': hybrid, **hybrid,
            'union_candidates': fused['union_candidates'], 'embedding_adapter_calls': 1,
            'embedding': {'identity': payload['embedding_identity'], 'query_sha256': payload['query_sha256'],
                          'source_kind': payload['source_kind'], 'usage': payload.get('usage')},
            'trace':trace, 'trace_report':context.to_dict()})
    except RetrievalError as error:
        failed(error)
        raise
    except ProbeError as error:
        converted = RetrievalError(stage, error.category)
        failed(converted)
        raise converted from None
    except ContractError as error:
        converted = RetrievalError(stage, error.code)
        failed(converted)
        raise converted from None
    except Exception:
        converted = RetrievalError(stage, 'retrieval_failed')
        failed(converted)
        raise converted from None
