"""Compatibility adapter over verified A2 experiment assets; no labels or network."""
import copy
import logging

from experiments.embedding_probe import ProbeError
from experiments.keyword_index import Tokenizer, parameters, build_index, search as sparse_search
from experiments.vector_index import load_corpus, load_index, identity, search as dense_search
from .core.errors import ContractError, RetrievalError
from .core.types import Document, Chunk

LOGGER = logging.getLogger(__name__)
CONFIG_FIELDS = {'dataset', 'corpus_run', 'vector_run', 'endpoint', 'model', 'dimensions',
                 'rrf_k', 'bm25_k1', 'bm25_b', 'bm25_method', 'backend', 'tokenizer_policy'}


class A2Snapshot:
    """Verified serial-query resources; caller authorization is explicit, not model supplied."""

    def __init__(self, config, corpus, index, tokenizer, authorized_ids):
        self._config = copy.deepcopy(config)
        self._corpus, self._index = corpus, index
        self._tokenizer = tokenizer
        self._authorized_ids = frozenset(authorized_ids)
        self._keyword_indices = {}
        self._documents = {uid: Document.from_source_record(source) for uid, source in corpus['sources'].items()}
        self._chunks = {}
        for uid, unit in index['units'].items():
            chunk = Chunk.from_legacy_unit(unit)
            document = self._documents.get(chunk.source_ref)
            if document is None or chunk.metadata['source_sha256'] != document.metadata['source_sha256'] or \
                    document.text[chunk.start_offset:chunk.end_offset] != chunk.text:
                raise ContractError('invalid_chunk')
            self._chunks[uid] = chunk

    @property
    def config(self):
        return copy.deepcopy(self._config)

    @property
    def embedding_identity(self):
        return identity(self._config)

    @property
    def fingerprint(self):
        return self._corpus['fingerprint']

    @property
    def index_id(self):
        return self._index['index_id']

    def resolve_scope(self, scope_ids, exclude_ids):
        if scope_ids is not None and not set(scope_ids) <= self._authorized_ids:
            raise RetrievalError('request', 'invalid_scope')
        permitted_exclusions = self._authorized_ids | set(self._corpus['excluded_ids'])
        if not set(exclude_ids) <= permitted_exclusions:
            raise RetrievalError('request', 'invalid_scope')
        if scope_ids is None and self._authorized_ids != set(self._corpus['sources']):
            return sorted(self._authorized_ids)
        return copy.deepcopy(scope_ids)

    def verify_current(self):
        """Fail closed if original source files or vector snapshot changed since loading."""
        try:
            corpus = load_corpus(self._config['corpus_run'], self._config['dataset'])
            index = load_index(self._config['vector_run'], corpus['fingerprint'], self._config)
            if corpus['fingerprint'] != self.fingerprint or index['index_id'] != self.index_id:
                raise RetrievalError('resources', 'snapshot_changed')
        except ProbeError as error:
            raise RetrievalError('resources', error.category) from None

    def dense(self, vector, scope_ids, exclude_ids, candidate_k):
        return dense_search(self._index, vector, scope_ids, exclude_ids, candidate_k)

    def sparse(self, query, scope_ids, exclude_ids, candidate_k):
        key = (tuple(sorted(scope_ids)) if scope_ids is not None else None, tuple(sorted(exclude_ids)))
        if key not in self._keyword_indices:
            self._keyword_indices[key] = build_index(
                self._corpus, scope_ids, exclude_ids, self._tokenizer, self._config)
        return sparse_search(self._keyword_indices[key], query, self._tokenizer, candidate_k)

    def canonical_units(self):
        return {uid: chunk.to_legacy_unit() for uid, chunk in self._chunks.items()}


def load_snapshot(config, authorized_document_ids, tokenizer_cache_dir):
    """Load explicit frozen resources; cache directory must be fresh, as in A2."""
    try:
        if type(config) is not dict or set(config) != CONFIG_FIELDS:
            raise RetrievalError('resources', 'invalid_resource_config')
        if any(type(config[name]) is not str or not config[name].strip()
               for name in ['dataset', 'corpus_run', 'vector_run', 'endpoint', 'model']):
            raise RetrievalError('resources', 'invalid_resource_config')
        if type(config['dimensions']) is not int or config['dimensions'] <= 0 or \
                type(config['rrf_k']) is not int or config['rrf_k'] != 60:
            raise RetrievalError('resources', 'invalid_resource_config')
        parameters(config)
        corpus = load_corpus(config['corpus_run'], config['dataset'])
        index = load_index(config['vector_run'], corpus['fingerprint'], config)
        ids = authorized_document_ids
        if type(ids) is not list or not ids or any(type(i) is not str or not i for i in ids) or \
                len(set(ids)) != len(ids) or not set(ids) <= set(corpus['sources']):
            raise RetrievalError('resources', 'invalid_authorization')
        tokenizer = Tokenizer(tokenizer_cache_dir)
        return A2Snapshot(config, corpus, index, tokenizer, ids)
    except RetrievalError as error:
        LOGGER.error('snapshot_failed stage=%s code=%s', error.stage, error.code)
        raise
    except ProbeError as error:
        LOGGER.error('snapshot_failed stage=resources code=%s', error.category)
        raise RetrievalError('resources', error.category) from None
    except ContractError as error:
        LOGGER.error('snapshot_failed stage=resources code=%s', error.code)
        raise RetrievalError('resources', error.code) from None
    except Exception:
        LOGGER.error('snapshot_failed stage=resources code=snapshot_load_failed')
        raise RetrievalError('resources', 'snapshot_load_failed') from None
