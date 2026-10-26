"""Scoped BM25S indexes over the frozen source-bound evidence corpus."""
import importlib.metadata
import json
import math
import re
from pathlib import Path

import bm25s
import jieba
import numpy as np

from experiments.embedding_probe import ProbeError
from experiments.vector_index import digest, make_index_text, read_json, read_rows, validate_scope

TOKEN_POLICY = 'zh-search-ascii-ident-v1'
SEGMENTS = re.compile(r'[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*|[\u4e00-\u9fff]+')
NATIVE_FILES = ['data.csc.index.npy', 'indices.csc.index.npy', 'indptr.csc.index.npy',
                'vocab.index.json', 'params.index.json']
META_FILES = ['mapping.json', 'tokens.jsonl']


class Tokenizer:
    def __init__(self, cache_dir):
        try:
            versions = {name: importlib.metadata.version(name) for name in ['jieba', 'bm25s']}
            if versions != {'jieba': '0.42.1', 'bm25s': '0.3.13'}:
                raise ValueError('unapproved package versions')
            dictionary = Path(jieba.__file__).parent / 'dict.txt'
            self.identity = {**versions, 'policy': TOKEN_POLICY,
                             'dictionary_sha256': digest(dictionary.read_bytes())}
            cache = Path(cache_dir)
            cache.mkdir(parents=True, exist_ok=False)
            self.tokenizer = jieba.Tokenizer()
            self.tokenizer.tmp_dir = str(cache)
            self.tokenizer.initialize()
            # Jieba logs/cache-falls-back internally. Require a fresh successful cache here.
            if not self.tokenizer.initialized or not (cache / 'jieba.cache').is_file():
                raise ValueError('dictionary/cache initialization failed')
            self.cache_hash = digest((cache / 'jieba.cache').read_bytes())
        except Exception:
            raise ProbeError('tokenizer', 'tokenizer_error') from None

    def tokenize(self, text, query=False):
        if not isinstance(text, str):
            raise ProbeError('tokenizer', 'tokenization_error')
        try:
            terms = []
            for match in SEGMENTS.finditer(text):
                value = match.group()
                if value.isascii():
                    terms.append(value.lower())
                else:
                    terms.extend(t for t in self.tokenizer.lcut_for_search(value, HMM=False)
                                 if t.strip() and any(c.isalnum() for c in t))
            return list(dict.fromkeys(terms)) if query else terms
        except Exception:
            raise ProbeError('tokenizer', 'tokenization_error') from None


def parameters(config):
    if config.get('bm25_method') != 'lucene' or config.get('backend') != 'numpy' or \
            config.get('tokenizer_policy') != TOKEN_POLICY:
        raise ProbeError('config', 'invalid_keyword_config')
    for key, expected in [('bm25_k1', 1.5), ('bm25_b', .75)]:
        if type(config.get(key)) not in (int, float) or config[key] != expected:
            raise ProbeError('config', 'invalid_keyword_config')
    return {'k1': config['bm25_k1'], 'b': config['bm25_b'], 'method': config['bm25_method'],
            'idf_method': config['bm25_method'], 'backend': config['backend'],
            'csc_backend': config['backend'], 'dtype': 'float64', 'int_dtype': 'int32', 'auto_compile': False}


def pool_data(corpus, scope_ids, exclude_ids, tokenizer, config):
    validate_scope(corpus['sources'], corpus['excluded_ids'], scope_ids, exclude_ids)
    params = parameters(config)
    units = sorted((u for u in corpus['units'] if (scope_ids is None or u['document_id'] in scope_ids)
                    and u['document_id'] not in exclude_ids), key=lambda u: u['unit_id'])
    rows = [{'unit_id': u['unit_id'], 'input_sha256': digest(make_index_text(u).encode()),
             'tokens': tokenizer.tokenize(make_index_text(u))} for u in units]
    if any(not r['tokens'] for r in rows):
        raise ProbeError('tokenizer', 'tokenization_error')
    if len({u['unit_id'] for u in units}) != len(units):
        raise ProbeError('keyword', 'invalid_units')
    scope = {'scope_ids': sorted(scope_ids) if scope_ids is not None else None,
             'exclude_ids': sorted(exclude_ids)}
    return {'units': units, 'unit_ids': [u['unit_id'] for u in units], 'rows': rows,
            'N': len(units), 'avgdl': sum(len(r['tokens']) for r in rows)/len(rows) if rows else 0,
            'vocab_count': len({t for r in rows for t in r['tokens']}), 'parameters': params,
            'scope': scope, 'identity': tokenizer.identity, 'fingerprint': corpus['fingerprint']}


def build_index(corpus, scope_ids, exclude_ids, tokenizer, config):
    data = pool_data(corpus, scope_ids, exclude_ids, tokenizer, config)
    try:
        bm25 = None
        if data['N']:
            bm25 = bm25s.BM25(**data['parameters'])
            bm25.index([r['tokens'] for r in data['rows']], create_empty_token=False, show_progress=False)
        return {**data, 'bm25': bm25}
    except Exception:
        raise ProbeError('keyword', 'keyword_index_error') from None


def write_index(folder, index):
    root = Path(folder)
    try:
        root.mkdir(parents=True, exist_ok=False)
        names = META_FILES.copy()
        if index['N']:
            index['bm25'].save(root, allow_pickle=False, show_progress=False)
            names += NATIVE_FILES
        with (root/'mapping.json').open('x', encoding='utf-8') as handle:
            json.dump(index['unit_ids'], handle)
        with (root/'tokens.jsonl').open('x', encoding='utf-8') as handle:
            for row in index['rows']:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
        header = {k: index[k] for k in ['scope', 'identity', 'fingerprint', 'parameters',
                                       'N', 'avgdl', 'vocab_count']}
        header.update(schema_version=1, status='complete',
                      files={name: digest((root/name).read_bytes()) for name in names})
        with (root/'manifest.json').open('x', encoding='utf-8') as handle:
            json.dump(header, handle, ensure_ascii=False, allow_nan=False, indent=2)
        return header
    except Exception:
        raise ProbeError('output', 'output_error') from None


def validate_matrix(bm25, data):
    scores = bm25.scores
    values, indices, offsets = [scores[k] for k in ['data', 'indices', 'indptr']]
    vocab = bm25.vocab_dict
    if scores['num_docs'] != data['N'] or len(vocab) != data['vocab_count'] or \
            set(vocab) != {t for r in data['rows'] for t in r['tokens']} or \
            set(vocab.values()) != set(range(len(vocab))):
        raise ValueError('vocab/doc count')
    if any(a.ndim != 1 for a in [values, indices, offsets]) or values.dtype != np.dtype('float64') or \
            indices.dtype != np.dtype('int32') or offsets.dtype != np.dtype('int64') or \
            len(values) != len(indices) or len(offsets) != len(vocab)+1 or offsets[0] != 0 or \
            offsets[-1] != len(values) or np.any(np.diff(offsets) < 0) or \
            not np.isfinite(values).all() or np.any(values < 0) or \
            np.any(indices < 0) or np.any(indices >= data['N']):
        raise ValueError('invalid sparse matrix')
    for start, end in zip(offsets[:-1], offsets[1:], strict=True):
        column = indices[start:end]
        if len(set(column)) != len(column):
            raise ValueError('duplicate postings')


def load_index(folder, corpus, scope_ids, exclude_ids, tokenizer, config):
    expected = pool_data(corpus, scope_ids, exclude_ids, tokenizer, config)
    root = Path(folder)
    try:
        header = read_json(root/'manifest.json', 'keyword-cache')
        names = META_FILES + (NATIVE_FILES if expected['N'] else [])
        if header['schema_version'] != 1 or header['status'] != 'complete' or \
                set(header['files']) != set(names):
            raise ValueError('partial/schema/files')
        for key in ['scope', 'identity', 'fingerprint', 'parameters', 'N', 'avgdl', 'vocab_count']:
            if header[key] != expected[key]:
                raise ValueError('identity/statistics')
        if any(digest((root/name).read_bytes()) != header['files'][name] for name in names) or \
                read_json(root/'mapping.json') != expected['unit_ids'] or \
                read_rows(root/'tokens.jsonl') != expected['rows']:
            raise ValueError('hash/mapping/tokens')
        bm25 = None
        if expected['N']:
            params = read_json(root/'params.index.json')
            for key, value in expected['parameters'].items():
                if key not in ['auto_compile', 'csc_backend'] and params.get(key) != value:
                    raise ValueError('package parameters')
            if params.get('num_docs') != expected['N'] or params.get('version') != tokenizer.identity['bm25s']:
                raise ValueError('package version/count')
            bm25 = bm25s.BM25.load(root, allow_pickle=False, show_progress=False,
                                  override_params={'auto_compile': False, 'csc_backend': 'numpy'})
            validate_matrix(bm25, expected)
        return {**expected, 'bm25': bm25}
    except Exception:
        raise ProbeError('keyword-cache', 'keyword_cache_mismatch') from None


def search(index, query, tokenizer, candidate_k):
    if type(candidate_k) is not int or not 0 < candidate_k <= 20:
        raise ProbeError('query', 'invalid_candidate_k')
    out = score_all(index, query, tokenizer)
    return dict(out, candidates=out['candidates'][:candidate_k])


def score_all(index, query, tokenizer):
    """Same scoped scores as search, before its global top-k truncation."""
    terms = tokenizer.tokenize(query, query=True)
    out = {'candidates': [], 'compared_count': index['N'], 'query_tokens': terms,
           'N': index['N'], 'avgdl': index['avgdl'], 'vocab_count': index['vocab_count']}
    if not index['N'] or not terms or not set(terms) & set(index['bm25'].vocab_dict):
        return out
    try:
        scores = index['bm25'].get_scores(terms)
        if scores.shape != (index['N'],) or not np.isfinite(scores).all():
            raise ValueError('invalid scores')
        scored = []
        for score, row, unit in zip(scores, index['rows'], index['units'], strict=True):
            hits = [term for term in terms if term in set(row['tokens'])]
            if hits:
                if not math.isfinite(float(score)) or score <= 0:
                    raise ValueError('non-positive matched score')
                scored.append((float(score), unit, hits))
        scored.sort(key=lambda item: (-item[0], item[1]['unit_id']))
        out['candidates'] = [dict(unit, score=score, rank=i+1, retrieval_method='sparse',
                                  score_kind='bm25', matched_terms=hits)
                             for i, (score, unit, hits) in enumerate(scored)]
        return out
    except Exception:
        raise ProbeError('keyword', 'keyword_query_error') from None
