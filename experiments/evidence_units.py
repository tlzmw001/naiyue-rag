"""Bounded Mock adaptation: pinned Markdown nodes and complete case rows."""

import hashlib
import json
import re

from experiments.markdown_checks import source_span, table_cells
from experiments.markdown_probe import map_exact_source, split_candidate


def render_unit(unit):
    span = unit['body_span']
    lines = [f"[unit={unit['unit_id']} doc={unit['document_id']} source={unit['source_path']} "
             f"version={unit['source_sha256']} L{span['line_start']}-{span['line_end']}]"]
    for context in unit['contexts']:
        at = context['span']
        lines.append(f"[{context['context_kind']} L{at['line_start']}-{at['line_end']}]\n{context['text']}")
    lines.append('[body]\n' + unit['body'])
    return '\n'.join(lines)


def diagnostic(source, category, severity='blocked', rule=None, span=None):
    result = {'document_id': source['document_id'], 'category': category, 'severity': severity}
    if rule is not None:
        result['rule'] = rule
    if span is not None:
        result['span'] = span
    return result


def scan_source(source):
    """Keep physical offsets and heading state; reject unsupported fence forms."""
    records, diagnostics, stack = [], [], []
    cursor, fence_open, fence_span = 0, False, None
    title = None
    for physical in source['text'].splitlines(keepends=True):
        line = physical.rstrip('\r\n')
        start, end = cursor, cursor + len(line)
        cursor += len(physical)
        span = source_span(source, start, end) if line else None
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        fenced = fence_open or marker is not None
        if marker:
            if marker.group(1) != '```' or (fence_open and line.strip() != '```'):
                diagnostics.append(diagnostic(source, 'unsupported_structure', rule='unsupported_fence', span=span))
            else:
                fence_open = not fence_open
                if fence_open:
                    fence_span = span
        elif not fence_open:
            heading = re.match(r'^(#{1,6})\s+\S.*', line)
            if heading:
                level = len(heading.group(1))
                while stack and stack[-1]['level'] >= level:
                    stack.pop()
                item = {'text': line, 'span': span, 'level': level}
                stack.append(item)
                if title is None and level == 1:
                    title = item
            for match in re.finditer(r'(?<![\w-])L(\d+)-L?(\d+)(?![\w-])', line):
                low, high = map(int, match.groups())
                if low < 1 or high < low or high > len(source['line_starts']):
                    hint_span = source_span(source, start + match.start(), start + match.end())
                    diagnostics.append(diagnostic(source, 'stale_header_line_range', 'warning', span=hint_span))
        records.append({'text': line, 'start': start, 'end': end, 'physical_end': cursor,
                        'fenced': fenced, 'headings': list(stack)})
    if fence_open:
        diagnostics.append(diagnostic(source, 'unsupported_structure', rule='unclosed_fence', span=fence_span))
    return records, title, diagnostics


def context_item(kind, heading):
    return {'context_kind': kind, 'text': heading['text'], 'span': dict(heading['span'])}


def make_unit(source, kind, start, end, headings, contexts, metadata, limit, fields=None):
    span = source_span(source, start, end)
    identity = [source['document_id'], source['source_sha256'], kind, start, end]
    encoded = json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    seen, unique_contexts = set(), []
    for item in contexts:
        at = item['span']
        key = (at['source_sha256'], at['start_char'], at['end_char'])
        if key not in seen:
            unique_contexts.append(item)
            seen.add(key)
    unit = {'schema_version': 1, 'unit_id': 'unit-' + hashlib.sha256(encoded).hexdigest(),
            'document_id': source['document_id'], 'source_path': source['relative_path'],
            'source_sha256': source['source_sha256'], 'role': source['role'],
            'semantic_level': source['semantic_level'], 'directory_level': source['directory_level'],
            'kind': kind, 'heading_path': [item['text'] for item in headings],
            'body': source['text'][start:end], 'body_span': span, 'contexts': unique_contexts,
            'case_id': fields[0] if fields else None, 'case_fields': fields or [],
            'component_metadata': dict(metadata), 'eligible': True, 'diagnostics': []}
    unit['rendered_text'] = render_unit(unit)
    unit['rendered_characters'] = len(unit['rendered_text'])
    if unit['rendered_characters'] > limit:
        unit['eligible'] = False
        unit['diagnostics'].append(diagnostic(source, 'single_evidence_over_budget', span=span))
    return unit


def text_unit(source, start, end, records, title, metadata, limit):
    raw = source['text'][start:end]
    start += len(raw) - len(raw.lstrip())
    end -= len(raw) - len(raw.rstrip())
    if start >= end:
        return None
    record = next(item for item in records if item['start'] <= start < item['physical_end'])
    headings = record['headings']
    contexts = ([context_item('document_title', title)] if title else [])
    contexts.extend(context_item('section_heading', item) for item in headings)
    return make_unit(source, 'text', start, end, headings, contexts, metadata, limit)


def adapt_cases(source, start, end, records, title, metadata, limit, seen_cases):
    selected = [r for r in records if start <= r['start'] < end]
    units, diagnostics, table_rows = [], [], set()
    header = None
    separator_ok = False
    for index, record in enumerate(selected):
        line = record['text']
        if record['fenced']:
            continue
        cells = table_cells(line)
        is_case = re.match(r'^\s*\|\s*TC-[A-Za-z0-9-]+\s*\|', line)
        if cells is None and not is_case:
            continue
        table_rows.add(index)
        span = source_span(source, record['start'], record['end'])
        if cells and cells[0] == '序号':
            header = record if len(cells) == 9 else None
            separator_ok = False
            if header is None:
                diagnostics.append(diagnostic(source, 'unsupported_structure', rule='header_columns', span=span))
            continue
        if cells and all(re.fullmatch(r':?-{3,}:?', cell.strip()) for cell in cells):
            separator_ok = header is not None and len(cells) == 9
            if not separator_ok:
                diagnostics.append(diagnostic(source, 'unsupported_structure', rule='separator', span=span))
            continue
        if not is_case or cells is None or len(cells) != 9 or not re.fullmatch(r'TC-[A-Za-z0-9-]+', cells[0]):
            diagnostics.append(diagnostic(source, 'unsupported_structure', rule='case_row', span=span))
            continue
        dimensions = [h for h in record['headings'] if h['level'] > 1]
        if title is None or not dimensions or header is None or not separator_ok:
            diagnostics.append(diagnostic(source, 'unsupported_structure', rule='missing_context', span=span))
            continue
        if cells[0] in seen_cases:
            diagnostics.append(diagnostic(source, 'unsupported_structure', rule='duplicate_case_id', span=span))
            continue
        seen_cases.add(cells[0])
        dimension = dimensions[-1]
        contexts = [context_item('document_title', title)]
        contexts.extend(context_item('section_heading', h) for h in dimensions[:-1])
        contexts.append(context_item('dimension', dimension))
        contexts.append({'context_kind': 'columns', 'text': header['text'],
                         'span': source_span(source, header['start'], header['end'])})
        for note in selected:
            if dimension['span']['end_char'] < note['start'] < header['start'] and note['text'].lstrip().startswith('>'):
                contexts.append({'context_kind': 'source_note', 'text': note['text'],
                                 'span': source_span(source, note['start'], note['end'])})
        units.append(make_unit(source, 'test_case', record['start'], record['end'],
                               record['headings'], contexts, metadata, limit, cells))
    # Prose is exported from known source ranges; no whole-table duplicate body.
    cursor = start
    for index in sorted(table_rows):
        record = selected[index]
        unit = text_unit(source, cursor, record['start'], records, title, metadata, limit)
        if unit:
            units.append(unit)
        cursor = min(record['physical_end'], end)
    unit = text_unit(source, cursor, end, records, title, metadata, limit)
    if unit:
        units.append(unit)
    units.sort(key=lambda unit: unit['body_span']['start_char'])
    return units, diagnostics


def build_units(source, max_evidence_chars):
    if type(max_evidence_chars) is not int or max_evidence_chars <= 0:
        raise ValueError('invalid_parameters: max_evidence_chars')
    if not source['text'].strip():
        return [], [diagnostic(source, 'empty_source', 'info')]
    records, title, diagnostics = scan_source(source)
    if any(d['severity'] == 'blocked' for d in diagnostics):
        return [], diagnostics
    try:
        native = split_candidate(source, 'C2', None, 0)
    except Exception as error:
        diagnostics.append(diagnostic(source, 'component_error', rule=type(error).__name__))
        return [], diagnostics
    if not native:
        diagnostics.append(diagnostic(source, 'nonempty_zero_nodes'))
        return [], diagnostics
    units, seen_cases = [], set()
    for chunk in native:
        mapping, spans = map_exact_source(source, chunk['chunk_text'])
        if mapping != 'exact':
            diagnostics.append(diagnostic(source, mapping))
            continue
        span, metadata = spans[0], chunk['native_metadata']
        if source['role'] == 'historical_test_cases':
            adapted, issues = adapt_cases(source, span['start_char'], span['end_char'], records,
                                          title, metadata, max_evidence_chars, seen_cases)
            units.extend(adapted)
            diagnostics.extend(issues)
        else:
            unit = text_unit(source, span['start_char'], span['end_char'], records,
                             title, metadata, max_evidence_chars)
            if unit:
                units.append(unit)
    units.sort(key=lambda unit: unit['body_span']['start_char'])
    for unit in units:
        diagnostics.extend(unit['diagnostics'])
    return units, diagnostics
