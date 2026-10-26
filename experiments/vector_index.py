"""Validated source binding, file vectors, exact cosine, and evidence packing."""
import hashlib
import json
from pathlib import Path

from experiments.embedding_probe import ProbeError, cosine, validate_vectors
from experiments.evidence_units import render_unit
from experiments.generation_probe import unique_object
from experiments.markdown_checks import source_span, table_cells
from experiments.markdown_probe import load_sources

POLICY = 'context-body-v1'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path, stage='preflight'):
    try:
        return json.loads(Path(path).read_bytes(), object_pairs_hook=unique_object)
    except (OSError, ValueError, UnicodeError):
        raise ProbeError(stage, 'invalid_file') from None


def read_rows(path, stage='preflight'):
    try:
        return [json.loads(line, object_pairs_hook=unique_object)
                for line in Path(path).read_text(encoding='utf-8').splitlines() if line]
    except (OSError, ValueError, UnicodeError):
        raise ProbeError(stage, 'invalid_file') from None


def make_index_text(unit):
    return '\n'.join([c['text'] for c in unit['contexts']] + [unit['body']])


def check_span(src, text, span):
    if any(type(span[k]) is not int for k in ['start_char', 'end_char', 'line_start', 'line_end']):
        raise ValueError('span type')
    start, end = span['start_char'], span['end_char']
    if not 0 <= start < end <= len(src['text']) or src['text'][start:end] != text:
        raise ValueError('span content')
    if span != source_span(src, start, end):
        raise ValueError('span location/version')


def load_corpus(corpus_run, dataset):
    rule = 'source'
    try:
        root = Path(corpus_run)
        manifest = read_json(Path(dataset) / 'manifest.json', 'corpus')
        if manifest.get('synthetic') is not True or manifest.get('dataset_id') != 'naiyue-rag-mock-v1':
            raise ValueError('unauthorized material')
        all_sources = {s['document_id']: s for s in load_sources(dataset)}
        summary = read_json(root / 'summary.json', 'corpus')
        registry, units = read_rows(root / 'sources.jsonl', 'corpus'), read_rows(root / 'units.jsonl', 'corpus')
        rule = 'state'
        if summary['status'] != 'complete' or summary['blocked_count'] != 0:
            raise ValueError('blocked corpus')
        excluded = summary['parameters']['exclude_ids']
        included = summary['parameters']['include_ids']
        expected = {k for k in all_sources if (not included or k in included) and k not in excluded}
        rule = 'registry'
        if len(registry) != len(expected) or {r['document_id'] for r in registry} != expected:
            raise ValueError('scope')
        sources = {k: all_sources[k] for k in expected}
        for record in registry:
            src = sources[record['document_id']]
            for field in ['document_id', 'relative_path', 'role', 'semantic_level', 'directory_level', 'source_sha256']:
                if record[field] != src[field]:
                    raise ValueError('identity')
            if record['line_count'] != len(src['line_starts']) or record['character_count'] != len(src['text']):
                raise ValueError('count')
        seen = set()
        for unit in units:
            rule = 'unit_identity'
            src = sources[unit['document_id']]
            if unit['unit_id'] in seen or unit['eligible'] is not True or unit['schema_version'] != 1:
                raise ValueError('identity')
            seen.add(unit['unit_id'])
            for field in ['source_sha256', 'role', 'semantic_level', 'directory_level']:
                if unit[field] != src[field]:
                    raise ValueError('source')
            if unit['source_path'] != src['relative_path'] or unit['kind'] not in ('text', 'test_case'):
                raise ValueError('kind/path')
            rule = 'body_span'
            check_span(src, unit['body'], unit['body_span'])
            rule = 'context_span'
            for context in unit['contexts']:
                check_span(src, context['text'], context['span'])
            identity = [unit['document_id'], unit['source_sha256'], unit['kind'],
                        unit['body_span']['start_char'], unit['body_span']['end_char']]
            expected_id = 'unit-' + digest(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode())
            if unit['unit_id'] != expected_id:
                raise ValueError('id')
            if unit['kind'] == 'test_case' and (table_cells(unit['body']) != unit['case_fields'] or
                                               unit['case_id'] != unit['case_fields'][0]):
                raise ValueError('case fields')
            rule = 'render'
            if render_unit(unit) != unit['rendered_text'] or len(unit['rendered_text']) != unit['rendered_characters']:
                raise ValueError('render')
            if unit['rendered_characters'] > summary['parameters']['max_evidence_chars']:
                raise ValueError('eligibility')
        rule = 'counts'
        if summary['source_count'] != len(registry) or summary['unit_count'] != len(units):
            raise ValueError('counts')
        raw = (root / 'sources.jsonl').read_bytes() + b'\n' + (root / 'units.jsonl').read_bytes() + POLICY.encode()
        return {'units': units, 'sources': sources, 'registry': registry,
                'fingerprint': digest(raw), 'excluded_ids': excluded}
    except ProbeError:
        raise
    except (ValueError, TypeError, KeyError, OSError, IndexError):
        raise ProbeError('corpus', 'invalid_corpus_' + rule) from None


def identity(config):
    return {k: config[k] for k in ['endpoint', 'model', 'dimensions']} | {'policy_id': POLICY}


def write_index(run_dir, corpus, queries, vectors, query_vectors, config):
    root = Path(run_dir)
    validate_vectors({'model': config['model'], 'data': [{'index': i, 'embedding': v} for i,v in enumerate(vectors)]},
                     len(corpus['units']), config['dimensions'], config['model'])
    validate_vectors({'model': config['model'], 'data': [{'index': i, 'embedding': v} for i,v in enumerate(query_vectors)]},
                     len(queries), config['dimensions'], config['model'])
    try:
        rows = [{'unit_id': u['unit_id'], 'input_sha256': digest(make_index_text(u).encode()), 'vector': v}
                for u,v in zip(corpus['units'], vectors, strict=True)]
        qrows = [{'task_id': q['task_id'], 'query_sha256': digest(q['query'].encode()), 'vector': v}
                 for q,v in zip(queries, query_vectors, strict=True)]
        with (root / 'index_vectors.jsonl').open('x', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        with (root / 'query_vectors.json').open('x', encoding='utf-8') as handle:
            json.dump(qrows, handle, ensure_ascii=False, allow_nan=False)
        files = {name: digest((root / name).read_bytes()) for name in ['index_vectors.jsonl', 'query_vectors.json']}
        descriptor = {'identity': identity(config), 'fingerprint': corpus['fingerprint'], 'files': files}
        header = {'schema_version': 1, 'status': 'complete', **descriptor,
                  'index_id': digest(json.dumps(descriptor, sort_keys=True).encode()),
                  'source_ids': sorted(corpus['sources']), 'excluded_ids': corpus['excluded_ids'],
                  'unit_count': len(rows), 'provider_revision': 'unknown'}
        with (root / 'index_manifest.json').open('x', encoding='utf-8') as handle:
            json.dump(header, handle, ensure_ascii=False, allow_nan=False, indent=2)
        return header
    except (OSError, ValueError, TypeError):
        raise ProbeError('output', 'output_error') from None


def load_index(run_dir, expected_fingerprint, config):
    try:
        root = Path(run_dir)
        corpus = load_corpus(config['corpus_run'], config['dataset'])
        header = read_json(root / 'index_manifest.json', 'cache')
        if header['status'] != 'complete' or header['identity'] != identity(config) or \
                header['fingerprint'] != expected_fingerprint or corpus['fingerprint'] != expected_fingerprint:
            raise ValueError('identity')
        names = ['index_vectors.jsonl', 'query_vectors.json']
        if set(header['files']) != set(names) or any(digest((root / name).read_bytes()) != header['files'][name] for name in names):
            raise ValueError('hash')
        descriptor = {k: header[k] for k in ['identity', 'fingerprint', 'files']}
        if header['index_id'] != digest(json.dumps(descriptor, sort_keys=True).encode()):
            raise ValueError('index id')
        rows, qrows = read_rows(root / names[0], 'cache'), read_json(root / names[1], 'cache')
        units = {u['unit_id']: u for u in corpus['units']}
        if len(rows) != len(units) or header['unit_count'] != len(rows) or len({r['unit_id'] for r in rows}) != len(rows):
            raise ValueError('mapping')
        for row in rows:
            if row['input_sha256'] != digest(make_index_text(units[row['unit_id']]).encode()):
                raise ValueError('text')
        for records in [rows, qrows]:
            validate_vectors({'model': config['model'], 'data': [{'index': i, 'embedding': r['vector']} for i,r in enumerate(records)]},
                             len(records), config['dimensions'], config['model'])
        if len({q['task_id'] for q in qrows}) != len(qrows):
            raise ValueError('query mapping')
        if header['source_ids'] != sorted(corpus['sources']) or header['excluded_ids'] != corpus['excluded_ids']:
            raise ValueError('scope')
        return {'units': units, 'vectors': {r['unit_id']: r['vector'] for r in rows},
                'query_vectors': {r['task_id']: r['vector'] for r in qrows},
                'query_hashes': {r['task_id']: r['query_sha256'] for r in qrows},
                'dimensions': config['dimensions'], 'model': config['model'], 'index_id': header['index_id'],
                'source_ids': header['source_ids'], 'excluded_ids': header['excluded_ids']}
    except (ProbeError, ValueError, TypeError, KeyError, OSError, IndexError):
        raise ProbeError('cache', 'cache_mismatch') from None


def validate_scope(source_ids, excluded_ids, scope_ids, exclude_ids):
    for ids in [scope_ids, exclude_ids]:
        if ids is not None and (not isinstance(ids, list) or any(not isinstance(i,str) or not i for i in ids) or len(set(ids)) != len(ids)):
            raise ProbeError('query', 'invalid_scope')
    if scope_ids is not None and (not scope_ids or not set(scope_ids) <= set(source_ids)):
        raise ProbeError('query', 'invalid_scope')
    if not set(exclude_ids) <= set(source_ids) | set(excluded_ids):
        raise ProbeError('query', 'invalid_scope')


def search(index, query_vector, scope_ids, exclude_ids, candidate_k):
    validate_scope(index['source_ids'], index['excluded_ids'], scope_ids, exclude_ids)
    if type(candidate_k) is not int or not 0 < candidate_k <= 20:
        raise ProbeError('query', 'invalid_candidate_k')
    validate_vectors({'model': index['model'], 'data': [{'index': 0, 'embedding': query_vector}]},
                     1, index['dimensions'], index['model'])
    pool = [u for u in index['units'].values() if (scope_ids is None or u['document_id'] in scope_ids)
            and u['document_id'] not in exclude_ids]
    scored = [(cosine(query_vector, index['vectors'][u['unit_id']]), u) for u in pool]
    scored.sort(key=lambda item: (-item[0], item[1]['unit_id']))
    candidates = [dict(u, score=s, rank=i+1, retrieval_method='vector') for i,(s,u) in enumerate(scored[:candidate_k])]
    return {'candidates': candidates, 'compared_count': len(pool)}


def pack_evidence(candidates, max_context_chars):
    if type(max_context_chars) is not int or not 0 < max_context_chars <= 8000:
        raise ProbeError('query', 'invalid_context_budget')
    selected, skipped, blocks, seen = [], [], [], set()
    chars = 0
    for row in candidates:
        if row['unit_id'] in seen:
            continue
        seen.add(row['unit_id'])
        method = row.get('retrieval_method', 'vector')
        kind = row.get('score_kind', 'cosine' if method == 'vector' else None)
        if (method, kind) == ('vector', 'cosine'):
            prefix = f"[vector rank={row['rank']:02d} cosine={row['score']:+.8f}]\n"
        elif (method, kind) == ('hybrid', 'rrf'):
            prefix = f"[hybrid rank={row['rank']:02d} rrf={row['score']:+.8f}]".ljust(35)+'\n'
        elif (method, kind) == ('sparse', 'bm25'):
            prefix = f"[bm25 rank={row['rank']:02d} bm25={row['score']:.8e}]".ljust(35)+'\n'
        elif (method, kind) == ('graph_mix', 'native_order') and row.get('score') is None:
            prefix = f"[graph_mix rank={row['rank']:02d} order=native]".ljust(35)+'\n'
        else:
            raise ProbeError('query', 'invalid_score_kind')
        if len(prefix) != 36:
            raise ProbeError('query', 'invalid_score_prefix')
        block = prefix + row['rendered_text']
        extra = len(block) + (2 if blocks else 0)
        if chars + extra > max_context_chars:
            skipped.append(dict(row, reason='budget_excluded'))
            continue
        blocks.append(block); chars += extra; selected.append(row)
    text = '\n\n'.join(blocks)
    return {'selected': selected, 'budget_excluded': skipped, 'context_text': text,
            'context_characters': len(text), 'max_context_chars': max_context_chars,
            'status': 'retrieved' if selected else ('no_evidence_fits' if candidates else 'empty'),
            'answerability': 'unknown'}
