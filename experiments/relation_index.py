"""Source-bound explicit document relations; no inferred business semantics."""
import heapq
import json
import re
import unicodedata
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from experiments.embedding_probe import ProbeError
from experiments.evidence_units import scan_source
from experiments.markdown_checks import source_span
from experiments.vector_index import digest, read_json, read_rows, validate_scope

POLICY = 'explicit-doc-v1'
LINK = re.compile(r'(?<!!)\[([^\]\n]+)\]\(([^)\n]+)\)')
IDENTITY_FIELDS = ['document_id', 'relative_path', 'role', 'semantic_level', 'source_sha256']


def limit(config, name, maximum):
    value = config.get(name)
    if type(value) is not int or not 0 < value <= maximum:
        raise ProbeError('config', 'invalid_'+name)
    return value


def target_id(raw, source, root, paths):
    if re.search(r'%(?![0-9a-fA-F]{2})', raw):
        return None, 'blocked_target', None
    try:
        parsed = urlsplit(raw)
        if parsed.netloc or raw.startswith('//'):
            return None, 'blocked_target', None
        if parsed.scheme:
            return None, 'external_reference' if parsed.scheme in ['http', 'https'] else 'blocked_target', None
        path = unquote(parsed.path, errors='strict')
        if '%' in path or '\\' in path or '\x00' in path or path.startswith('/') or parsed.query:
            return None, 'blocked_target', None
        if not path:
            return None, 'local_anchor', None
        absolute = (root/PurePosixPath(source['relative_path']).parent/path).resolve()
        if not absolute.is_relative_to(root):
            return None, 'blocked_target', None
        relative = absolute.relative_to(root).as_posix()
        if relative not in paths:
            return None, 'target_not_indexed', relative
        return paths[relative], 'fragment_unresolved' if parsed.fragment else None, relative
    except (ValueError, UnicodeError, OSError):
        return None, 'blocked_target', None


def edge_record(kind, src, dst, quote, span, **extra):
    record = {'schema_version': 1, 'kind': kind, 'from_document_id': src['document_id'],
              'to_document_id': dst['document_id'], 'from_source_sha256': src['source_sha256'],
              'to_source_sha256': dst['source_sha256'], 'quote': quote, 'source_span': span, **extra}
    return {**record, 'edge_id': 'edge-'+digest(json.dumps(record, sort_keys=True, ensure_ascii=False).encode())}


def build_index(corpus, dataset, config):
    if config.get('relation_policy') != POLICY:
        raise ProbeError('config', 'invalid_relation_policy')
    maximum = limit(config, 'max_graph_nodes', 64)
    if len(corpus['sources']) > maximum:
        raise ProbeError('relation', 'resource_error')
    try:
        dataset_root = Path(dataset).resolve(); root = (dataset_root/'knowledge').resolve()
        if not root.is_relative_to(dataset_root):
            raise ValueError('knowledge escapes dataset')
        sources = corpus['sources']
        paths = {s['relative_path']: did for did, s in sources.items()}
        if len(paths) != len(sources):
            raise ValueError('ambiguous paths')
        for did, src in sources.items():
            if src['document_id'] != did or digest(src['text'].encode()) != src['source_sha256'] or \
                    not (root/src['relative_path']).resolve().is_relative_to(root):
                raise ValueError('invalid source identity')
        edges, diagnostics, corresponding = [], [], {}
        for did in sorted(sources):
            src = sources[did]
            records, _, observed = scan_source(src)
            if any(d['severity'] == 'blocked' for d in observed):
                raise ProbeError('relation', 'unsupported_structure')
            diagnostics.extend(observed)
            preamble = True
            for row in records:
                if any(h['level'] >= 2 for h in row['headings']):
                    preamble = False
                if row['fenced']:
                    continue
                visible = re.sub(r'`[^`]*`', lambda m: ' '*len(m.group()), row['text'])
                leftover = LINK.sub(lambda m: ' '*len(m.group()), visible)
                leftover = re.sub(r'!\[[^\]]*\]\([^)]*\)', lambda m: ' '*len(m.group()), leftover)
                unsupported_code = '``' in row['text'] or bool(visible.count('`'))
                if unsupported_code or '](' in leftover or re.search(r'\]\[[^\]]*\]|\]\s*$', visible):
                    diagnostics.append({'document_id': did, 'category': 'unsupported_reference',
                                        'span': source_span(src, row['start'], row['end'])})
                    if unsupported_code:
                        continue
                for match in LINK.finditer(visible):
                    span = source_span(src, row['start']+match.start(), row['start']+match.end())
                    raw = match.group(2)
                    if '(' in raw or '\\' in match.group() or any(c.isspace() for c in raw):
                        diagnostics.append({'document_id': did, 'category': 'unsupported_reference', 'span': span})
                        continue
                    to_id, issue, relative = target_id(raw, src, root, paths)
                    if issue:
                        diagnostics.append({'document_id': did, 'category': issue, 'span': span})
                    if preamble and re.match(r'^\s*>\s*对应(?:需求|模块)\s*[:：]', row['text']):
                        corresponding.setdefault(did, []).append(to_id)
                    if to_id is None:
                        continue
                    edges.append(edge_record('markdown_link', src, sources[to_id],
                                 src['text'][span['start_char']:span['end_char']], span,
                                 raw_target=raw, canonical_target=relative,
                                 heading_path=[h['text'] for h in row['headings']]))
        for did in sorted(sources):
            src = sources[did]
            if src['role'] != 'historical_test_cases':
                continue
            stem = unicodedata.normalize('NFC', PurePosixPath(src['relative_path']).stem)
            if not stem.endswith('_测试用例'):
                diagnostics.append({'document_id': did, 'category': 'unsupported_naming'})
                continue
            wanted = stem.removesuffix('_测试用例')
            matches = [s for s in sources.values() if
                       unicodedata.normalize('NFC', PurePosixPath(s['relative_path']).stem) == wanted]
            issue = 'missing_pair' if not matches else ('ambiguous_pair' if len(matches) > 1 else None)
            if issue is None and matches[0]['role'] not in ['module', 'historical_requirement']:
                issue = 'invalid_pair_role'
            if issue is None and any(t != matches[0]['document_id'] for t in corresponding.get(did, [])):
                issue = 'pair_conflict'
            if issue:
                diagnostics.append({'document_id': did, 'category': issue})
                continue
            dst = matches[0]
            edges.append(edge_record('filename_pair', src, dst, None, None,
                         derivation={'rule': 'filename-suffix-v1', 'stem': wanted,
                                     'case_path': src['relative_path'], 'origin_path': dst['relative_path']}))
        unique = {e['edge_id']: e for e in edges}
        return {'schema_version': 1, 'policy': POLICY, 'parser_policy': 'bounded-inline-ref-v1',
                'fingerprint': corpus['fingerprint'],
                'nodes': {did: {k: s[k] for k in IDENTITY_FIELDS} for did, s in sorted(sources.items())},
                'edges': [unique[k] for k in sorted(unique)], 'diagnostics': diagnostics}
    except ProbeError:
        raise
    except (ValueError, TypeError, KeyError, OSError):
        raise ProbeError('relation', 'invalid_relation_material') from None


def write_index(folder, graph):
    root = Path(folder)
    try:
        root.mkdir(parents=True, exist_ok=False)
        for name, rows in [('edges.jsonl', graph['edges']), ('diagnostics.jsonl', graph['diagnostics'])]:
            with (root/name).open('x', encoding='utf-8') as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
        header = {k: v for k, v in graph.items() if k not in ['edges', 'diagnostics']}
        header.update(status='complete', edge_count=len(graph['edges']), diagnostic_count=len(graph['diagnostics']),
                      files={n: digest((root/n).read_bytes()) for n in ['edges.jsonl', 'diagnostics.jsonl']})
        with (root/'relation_manifest.json').open('x', encoding='utf-8') as handle:
            json.dump(header, handle, ensure_ascii=False, indent=2, allow_nan=False)
    except (OSError, ValueError, TypeError):
        raise ProbeError('output', 'output_error') from None


def load_index(folder, corpus, dataset, config):
    root = Path(folder)
    try:
        header = read_json(root/'relation_manifest.json', 'relation-cache')
        names = ['edges.jsonl', 'diagnostics.jsonl']
        if header['status'] != 'complete' or set(header['files']) != set(names) or any(
                digest((root/n).read_bytes()) != header['files'][n] for n in names):
            raise ValueError('state/files')
        graph = {k: header[k] for k in ['schema_version', 'policy', 'parser_policy', 'fingerprint', 'nodes']}
        graph.update(edges=read_rows(root/names[0]), diagnostics=read_rows(root/names[1]))
        # Re-derive facts for integrity, never replace invalid cached records or save a repaired index.
        expected = build_index(corpus, dataset, config)
        if json.dumps(graph, sort_keys=True, ensure_ascii=False, allow_nan=False) != \
                json.dumps(expected, sort_keys=True, ensure_ascii=False, allow_nan=False) or \
                type(header['edge_count']) is not int or type(header['diagnostic_count']) is not int or \
                header['edge_count'] != len(graph['edges']) or \
                header['diagnostic_count'] != len(graph['diagnostics']):
            raise ValueError('source/derivation/count')
        return graph
    except Exception:
        raise ProbeError('relation-cache', 'relation_cache_mismatch') from None


def expand(graph, candidates, corpus, scope_ids, exclude_ids, config):
    validate_scope(corpus['sources'], corpus['excluded_ids'], scope_ids, exclude_ids)
    seed_k = limit(config, 'seed_k', 5); seed_max = limit(config, 'max_seed_documents', 3)
    hops_max = limit(config, 'max_hops', 2); docs_max = limit(config, 'max_related_documents', 8)
    visits_max = limit(config, 'max_edge_visits', 128)
    allowed = set(scope_ids if scope_ids is not None else corpus['sources'])-set(exclude_ids)
    canonical = {u['unit_id']: u for u in corpus['units']}
    seeds, seen_seeds = [], set()
    for rank, row in enumerate(candidates[:seed_k], 1):
        did = row['document_id']
        if row['unit_id'] not in canonical or canonical[row['unit_id']]['document_id'] != did or row['rank'] != rank:
            raise ProbeError('relation', 'invalid_seeds')
        if did not in allowed:
            raise ProbeError('relation', 'invalid_seeds')
        if graph['nodes'][did]['semantic_level'] == 'L0' or did in seen_seeds:
            continue
        seen_seeds.add(did); seeds.append({'document_id': did, 'unit_id': row['unit_id'], 'rank': rank})
        if len(seeds) == seed_max:
            break
    adjacency = {did: [] for did in allowed}
    for e in graph['edges']:
        a, b = e['from_document_id'], e['to_document_id']
        if a in allowed and b in allowed:
            adjacency[a].append((b, e, 'forward')); adjacency[b].append((a, e, 'reverse'))
    heap, counter = [], 0
    def push(did, seed, path):
        nonlocal counter
        key = (len(path), seed['rank'], did, tuple(p['edge_id'] for p in path), tuple(p['direction'] for p in path))
        counter += 1; heapq.heappush(heap, (key, counter, did, seed, path))
    for s in seeds:
        push(s['document_id'], s, [])
    visited, rejected, related, excluded, visits = set(), set(), [], [], 0
    while heap:
        _, _, did, s, path = heapq.heappop(heap)
        if did in visited or did in rejected:
            continue
        best = {'seed_document_id': s['document_id'], 'seed_unit_id': s['unit_id'],
                'seed_rank': s['rank'], 'hop_count': len(path), 'hops': path}
        if did not in seen_seeds:
            row = {'document_id': did, 'best_path': best}
            if len(related) == docs_max:
                rejected.add(did); excluded.append(row); continue
            related.append(row)
        visited.add(did)
        if len(path) == hops_max or graph['nodes'][did]['semantic_level'] == 'L0':
            continue
        for target, e, direction in sorted(adjacency[did], key=lambda t: (t[0], t[1]['edge_id'], t[2])):
            visits += 1
            if visits > visits_max:
                raise ProbeError('relation', 'resource_error')
            if target in visited or target in rejected:
                continue
            step = {'edge_id': e['edge_id'], 'kind': e['kind'], 'direction': direction,
                    'from_document_id': did, 'to_document_id': target}
            push(target, s, path+[step])
    return {'seeds': seeds, 'related_documents': related, 'document_limit_excluded': excluded,
            'edge_visits': visits, 'allowed_document_count': len(allowed)}
