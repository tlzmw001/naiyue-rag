"""Conservative retrieval views; raw evidence and source declarations stay separate."""
import copy
import hashlib
import json
import logging
from pathlib import PurePosixPath
import re

from markdown_it import MarkdownIt

from ..core.errors import ChunkingError, PreparationError
from ..core.types import Chunk
from .markdown_structure import ALIASES, _cells, _label, source_span, validate_document

LOGGER = logging.getLogger(__name__)
POLICY_ID = 'markdown-retrieval-view-v1'


def _fail(code):
    LOGGER.error('preparation_failed stage=preparation code=%s', code)
    raise PreparationError(code) from None


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _fingerprint(value):
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def _validate_chunks(document, chunks):
    """Validate both evidence and the derived cells used by the rule stages."""
    try:
        validate_document(document)
        if type(chunks) is not list:
            raise ValueError()
        output = []
        identities = set()
        parser = MarkdownIt('commonmark')
        for chunk in chunks:
            if not isinstance(chunk, Chunk):
                raise ValueError()
            item = Chunk(chunk.id, chunk.text, chunk.metadata,
                         chunk.start_offset, chunk.end_offset, chunk.source_ref)
            meta = item.metadata
            if item.id in identities or item.source_ref != document.id or \
                    any(meta.get(key) != document.metadata[key] for key in
                        ['knowledge_base_id', 'source_path', 'source_sha256', 'size_bytes']) or \
                    item.text != document.text[item.start_offset:item.end_offset] or \
                    meta['body_span'] != source_span(document, item.start_offset, item.end_offset):
                raise ValueError()
            identities.add(item.id)
            if type(meta.get('contexts')) is not list or \
                    meta.get('kind') not in ('text', 'code', 'table', 'test_case'):
                raise ValueError()
            for ctx in meta['contexts']:
                if type(ctx) is not dict or set(ctx) != {'context_kind', 'text', 'span'} or \
                        type(ctx['context_kind']) is not str:
                    raise ValueError()
                span = ctx['span']
                if span != source_span(document, span['start_char'], span['end_char']) or \
                        ctx['text'] != document.text[span['start_char']:span['end_char']]:
                    raise ValueError()
            if meta['kind'] == 'test_case':
                columns = meta.get('case_columns')
                fields = meta.get('case_fields')
                headers = [c for c in meta['contexts'] if c['context_kind'] == 'columns']
                if type(columns) is not list or type(fields) is not list or \
                        not columns or len(columns) != len(fields) or len(headers) != 1 or \
                        columns != _cells(headers[0]['text']) or fields != _cells(item.text) or \
                        meta.get('document_classification', {}).get('kind') != 'test_cases':
                    raise ValueError()
                labels = [_label(parser, c) for c in columns]
                if any(sum(label in ALIASES[key] for label in labels) != 1
                       for key in ['name', 'preconditions', 'steps', 'expected']):
                    raise ValueError()
            output.append(item)
        return output
    except Exception:
        _fail('invalid_preparation_input')


def _case_cell(value):
    # A cell may contain inline code without character offsets from the parser.
    # Preserve such cells rather than guessing which HTML belongs to code.
    if '`' in value:
        return value
    def replace(match):
        slashes = len(match.group(1))
        return match.group(0) if slashes % 2 else match.group(1) + '\n'
    return re.sub(r'(\\*)<br\s*/?>', replace, value, flags=re.IGNORECASE)


class ChunkRefiner:
    def transform(self, document, chunks, *, text_mode):
        if type(text_mode) is not str or text_mode not in ('raw', 'labeled_case'):
            _fail('invalid_text_mode')
        output = _validate_chunks(document, chunks)
        try:
            for chunk in output:
                meta = chunk.metadata
                text = chunk.text
                rules = []
                if text_mode == 'labeled_case' and meta['kind'] == 'test_case':
                    text = '\n'.join(f'{column}：{_case_cell(value)}' for column, value in
                                     zip(meta['case_columns'], meta['case_fields']))
                    rules = ['all_columns_labeled', 'br_in_cells_without_backticks']
                meta['retrieval_view'] = {
                    'text': text, 'text_mode': text_mode, 'policy_id': POLICY_ID,
                    'input_sha256': _fingerprint({
                        'source_sha256': meta['source_sha256'], 'chunk_id': chunk.id,
                        'text': chunk.text, 'case_columns': meta.get('case_columns', []),
                        'case_fields': meta.get('case_fields', []),
                    }),
                    'text_sha256': _sha(text), 'rules': rules,
                }
            return output
        except Exception:
            _fail('refinement_failed')


class MetadataEnricher:
    def transform(self, document, chunks):
        output = _validate_chunks(document, chunks)
        try:
            path = PurePosixPath(document.metadata['source_path'])
            parser = MarkdownIt('commonmark')
            for chunk in output:
                titles = [c for c in chunk.metadata['contexts']
                          if c['context_kind'] == 'document_title']
                if len(titles) > 1:
                    raise ValueError()
                title = {'value': path.stem, 'basis': 'filename', 'span': None}
                if titles:
                    tokens = parser.parse(titles[0]['text'].lstrip('\ufeff'))
                    if len(tokens) != 3 or tokens[0].type != 'heading_open':
                        raise ValueError()
                    title = {'value': tokens[1].content, 'basis': 'document_heading',
                             'span': copy.deepcopy(titles[0]['span'])}
                directories = sorted(set(p for p in path.parts[:-1] if p in ('L0', 'L1', 'L2')))
                candidates = []
                declarations = [('filename', path.stem)]
                if titles:
                    declarations.append(('document_heading', title['value']))
                for basis, value in declarations:
                    match = re.match(r'^L[012](?=$|[:： _-])', value)
                    if match:
                        candidates.append({'value': match.group(0), 'basis': basis})
                levels = {c['value'] for c in candidates}
                status = 'unknown' if not levels else 'consistent' if len(levels) == 1 else 'conflict'
                chunk.metadata['document_info'] = {
                    'title': title,
                    'directory_level': directories[0] if len(directories) == 1 else None,
                    'declared_level': {'value': next(iter(levels)) if len(levels) == 1 else None,
                                       'status': status, 'candidates': candidates},
                }
            return output
        except Exception:
            _fail('enrichment_failed')


def prepare_document(document, chunker, *, text_mode):
    """Actual M2 rule pipeline; returns prepared chunks and original diagnostics."""
    if type(text_mode) is not str or text_mode not in ('raw', 'labeled_case'):
        _fail('invalid_text_mode')
    try:
        chunks, diagnostics = chunker.split_document(document)
    except (ChunkingError, PreparationError):
        raise
    except Exception:
        _fail('preparation_chunking_failed')
    try:
        chunks = ChunkRefiner().transform(document, chunks, text_mode=text_mode)
    except PreparationError:
        raise
    except Exception:
        _fail('refinement_failed')
    try:
        chunks = MetadataEnricher().transform(document, chunks)
    except PreparationError:
        raise
    except Exception:
        _fail('enrichment_failed')
    return chunks, diagnostics
