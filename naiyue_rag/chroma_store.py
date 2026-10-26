"""Explicit-vector Chroma adapter with source binding and pre-recall authorization.

SDK imports are lazy. Native callers must use a controlled environment and a
working directory without .env; the experiment launches a dedicated worker.
"""
import copy
import importlib.metadata
import json
import logging
import math
from pathlib import Path
import re

from experiments.vector_index import make_index_text, validate_scope
from experiments.embedding_probe import ProbeError
from .retrieval import RetrievalError

LOGGER = logging.getLogger(__name__)
CONFIG_FIELDS = {'persist_directory', 'collection_name', 'embedding_identity', 'corpus_id',
                 'index_id', 'authorized_document_ids', 'excluded_document_ids'}


def fail(code, stage='chroma'):
    LOGGER.error('chroma_failed stage=%s code=%s', stage, code)
    raise RetrievalError(stage, code) from None


def validate_config(config):
    try:
        if type(config) is not dict or set(config) != CONFIG_FIELDS:
            raise ValueError('fields')
        path = config['persist_directory']
        if type(path) is not str or not Path(path).is_absolute() or '..' in Path(path).parts:
            raise ValueError('path')
        name = config['collection_name']
        if type(name) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{1,510}[A-Za-z0-9]', name):
            raise ValueError('name')
        ident = config['embedding_identity']
        if type(ident) is not dict or set(ident) != {'endpoint','model','dimensions','policy_id'} or \
                type(ident['dimensions']) is not int or ident['dimensions'] <= 0:
            raise ValueError('identity')
        if any(type(ident[k]) is not str or not ident[k] for k in ['endpoint','model','policy_id']) or \
                any(type(config[k]) is not str or not config[k] for k in ['corpus_id','index_id']):
            raise ValueError('identity')
        for key in ['authorized_document_ids','excluded_document_ids']:
            values = config[key]
            if type(values) is not list or any(type(i) is not str or not i for i in values) or \
                    len(values) != len(set(values)):
                raise ValueError('ids')
        if not config['authorized_document_ids']:
            raise ValueError('authorization')
    except (ValueError, TypeError, KeyError, OSError):
        fail('invalid_chroma_config')


class ChromaStore:
    """Local serial store; canonical evidence comes from a validated source snapshot.

    create=True authorizes upsert. Reopened query stores never create/backfill.
    client injection is for SDK contract tests, not a replacement backend.
    """

    def __init__(self, config, canonical_units, *, create=False, client=None):
        validate_config(config)
        self.config = copy.deepcopy(config)
        self.units = copy.deepcopy(canonical_units)
        self._writable = create
        self._records = {}
        try:
            if type(create) is not bool or type(self.units) is not dict or not self.units:
                raise ValueError('units')
            for uid, unit in self.units.items():
                if type(uid) is not str or unit['unit_id'] != uid:
                    raise ValueError('id')
                metadata = {k: unit[k] for k in ['document_id','source_sha256','role','kind']}
                if any(type(v) is not str or not v for v in metadata.values()):
                    raise ValueError('metadata')
                metadata['canonical_json'] = json.dumps(unit, ensure_ascii=False, sort_keys=True, allow_nan=False)
                self._records[uid] = (make_index_text(unit), metadata)
            self._source_ids = sorted({u['document_id'] for u in self.units.values()})
            if not set(config['authorized_document_ids']) <= set(self._source_ids):
                raise ValueError('authorization')
        except (ValueError, TypeError, KeyError):
            fail('invalid_canonical_units')
        self._metadata = {'corpus_id':config['corpus_id'], 'index_id':config['index_id'],
            'embedding_identity':json.dumps(config['embedding_identity'], sort_keys=True, allow_nan=False)}
        if client is None:
            # Chroma constructs Settings at import time, so guard before importing.
            if Path('.env').exists():
                fail('uncontrolled_sdk_environment')
            try:
                if importlib.metadata.version('chromadb') != '1.5.9':
                    fail('runtime_mismatch')
                import chromadb
                from chromadb.config import Settings
                client = chromadb.PersistentClient(path=config['persist_directory'],
                    settings=Settings(_env_file=None, allow_reset=False, anonymized_telemetry=False))
            except RetrievalError:
                raise
            except Exception:
                fail('chroma_init_failed')
        self.client = client
        try:
            if create:
                self.collection = client.get_or_create_collection(name=config['collection_name'],
                    embedding_function=None, metadata=self._metadata, configuration={'hnsw':{'space':'cosine'}})
            else:
                self.collection = client.get_collection(name=config['collection_name'], embedding_function=None)
        except Exception:
            fail('chroma_open_failed')
        self.verify_collection()

    def verify_collection(self):
        try:
            configuration = self.collection.configuration
            if self.collection.metadata != self._metadata or configuration['hnsw']['space'] != 'cosine' or \
                    configuration.get('embedding_function') is not None:
                raise ValueError('configuration')
        except Exception:
            fail('collection_mismatch')

    def _call(self, operation, **kwargs):
        try:
            return getattr(self.collection, operation)(**kwargs)
        except Exception:
            fail('chroma_' + operation + '_failed')

    def _vector(self, value):
        dimensions = self.config['embedding_identity']['dimensions']
        if type(value) is not list or len(value) != dimensions or \
                any(type(v) not in (int,float) or not math.isfinite(v) for v in value) or \
                not any(v != 0 for v in value):
            fail('invalid_vector')
        return value

    def count(self):
        count = self._call('count')
        if type(count) is not int or count < 0:
            fail('invalid_chroma_result')
        return count

    def upsert(self, vectors):
        if not self._writable:
            fail('write_not_allowed')
        self.verify_collection()
        if type(vectors) is not dict or not vectors or not set(vectors) <= set(self.units):
            fail('invalid_upsert')
        if any(self.units[uid]['document_id'] not in self.config['authorized_document_ids'] for uid in vectors):
            fail('invalid_scope')
        ids = list(vectors)
        embeddings = [self._vector(vectors[uid]) for uid in ids]
        self._call('upsert', ids=ids, embeddings=embeddings,
            documents=[self._records[uid][0] for uid in ids],
            metadatas=[copy.deepcopy(self._records[uid][1]) for uid in ids])

    def _bound_unit(self, uid, document, metadata, allowed):
        if uid not in self.units or self.units[uid]['document_id'] not in allowed or \
                (document, metadata) != self._records[uid]:
            fail('invalid_chroma_result')
        return copy.deepcopy(self.units[uid])

    def get_by_ids(self, ids):
        if type(ids) is not list or not ids or len(set(ids)) != len(ids) or \
                any(type(uid) is not str or uid not in self.units for uid in ids):
            fail('invalid_get_ids')
        allowed = self.config['authorized_document_ids']
        if any(self.units[uid]['document_id'] not in allowed for uid in ids):
            fail('invalid_scope')
        self.verify_collection()
        result = self._call('get', ids=ids, include=['embeddings','metadatas','documents'])
        mapped = {}
        try:
            rows = [result[key] for key in ['ids','embeddings','metadatas','documents']]
            if any(len(values) != len(ids) for values in rows) or set(rows[0]) != set(ids):
                raise ValueError('mapping')
            for uid, vector, metadata, document in zip(*rows, strict=True):
                unit = self._bound_unit(uid, document, metadata, allowed)
                vector = vector.tolist() if hasattr(vector, 'tolist') else vector
                mapped[uid] = {'unit':unit, 'vector':copy.deepcopy(self._vector(vector))}
        except RetrievalError:
            raise
        except Exception:
            fail('invalid_chroma_result')
        return mapped

    def query(self, vector, scope_ids, exclude_ids, candidate_k):
        try:
            validate_scope(self._source_ids, self.config['excluded_document_ids'], scope_ids, exclude_ids)
            if scope_ids is not None and not set(scope_ids) <= set(self.config['authorized_document_ids']):
                raise ValueError('authorization')
            allowed = (set(self.config['authorized_document_ids']) if scope_ids is None else set(scope_ids)) - set(exclude_ids)
        except (ProbeError, ValueError, TypeError):
            fail('invalid_scope')
        if type(candidate_k) is not int or not 0 < candidate_k <= 20:
            fail('invalid_candidate_k')
        self._vector(vector)
        self.verify_collection()
        count = sum(u['document_id'] in allowed for u in self.units.values())
        if not count:
            return {'candidates':[], 'compared_count':0}
        result = self._call('query', query_embeddings=[vector], n_results=min(candidate_k,count),
            where={'document_id':{'$in':sorted(allowed)}}, include=['metadatas','distances','documents'])
        candidates = []
        try:
            groups = [result[key] for key in ['ids','distances','metadatas','documents']]
            if any(type(group) is not list or len(group) != 1 for group in groups):
                raise ValueError('groups')
            rows = [group[0] for group in groups]
            if any(type(row) is not list for row in rows) or len(rows[0]) > min(candidate_k,count) or \
                    any(len(row) != len(rows[0]) for row in rows) or len(set(rows[0])) != len(rows[0]):
                raise ValueError('shape')
            for uid, distance, metadata, document in zip(*rows, strict=True):
                unit = self._bound_unit(uid, document, metadata, allowed)
                if type(distance) not in (int,float) or not math.isfinite(distance) or not -1e-6 <= distance <= 2+1e-6:
                    raise ValueError('distance')
                candidates.append(dict(unit, score=1-distance, score_kind='cosine', distance=distance,
                    reference_similarity=max(0.,1-distance/2), retrieval_method='vector'))
            candidates.sort(key=lambda row:(-row['score'],row['unit_id']))
            for rank, row in enumerate(candidates,1): row['rank'] = rank
        except RetrievalError:
            raise
        except Exception:
            fail('invalid_chroma_result')
        # This count describes the permitted pool, not ANN's visited nodes.
        return {'candidates':candidates, 'compared_count':count}
