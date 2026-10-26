"""Source-bound document relations over an explicit loaded registry, without IO."""
import hashlib
from bisect import bisect_right
import json
import logging
from pathlib import PurePosixPath
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.rules_inline import html_inline, image, link
from markdown_it.rules_inline.backticks import backtick

from ..core.errors import RelationError
from ..core.types import Document
from .markdown_structure import _label, source_span, validate_document

LOGGER = logging.getLogger(__name__)
POLICY = 'markdown-document-relations-v1'
DIRECT = re.compile(r'\[([^\[\]\n\\]+)\]\(([^()\s]+)\)')
FIELD = re.compile(r'^\s*>\s*(?P<label>[^\[\]`():：]+?)\s*[:：]')


def _fail(code):
    LOGGER.error('relations_failed stage=relations code=%s', code)
    raise RelationError(code) from None


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _registry(documents):
    try:
        if type(documents) is not list:
            raise ValueError()
        sources = {};paths = {};kb = None
        for value in documents:
            if not isinstance(value, Document):
                raise ValueError()
            doc = Document(value.id, value.text, value.metadata)
            validate_document(doc)
            meta = doc.metadata;path = PurePosixPath(meta['source_path'])
            library = meta.get('knowledge_base_id')
            if type(library) is not str or not library.strip() or '\x00' in library or \
                    path.is_absolute() or '..' in path.parts or '\\' in str(path) or \
                    '\x00' in str(path) or re.match(r'^[A-Za-z]:', str(path)) or \
                    path.as_posix() != meta['source_path'] or path.suffix.lower() != '.md' or \
                    doc.id in sources or str(path) in paths or (kb is not None and kb != library):
                raise ValueError()
            kb = library;sources[doc.id] = doc;paths[str(path)] = doc.id
        return dict(sorted(sources.items())), paths, kb
    except Exception:
        _fail('invalid_relation_documents')


def _parser():
    parser = MarkdownIt('commonmark').enable('table')
    def capture(kind, original):
        def rule(state, silent):
            start = state.pos
            root = not silent and state.linkLevel == 0 and \
                state.src == state.env.get('_relation_line')
            matched = original(state, silent)
            if matched and root:
                state.env['_relation_ranges'].append((kind, start, state.pos))
            if matched and not silent and state.linkLevel == 0 and \
                    kind != 'link' and '\n' in state.src[start:state.pos] and \
                    '_relation_full_ranges' in state.env:
                state.env['_relation_full_ranges'].append((state.src, start, state.pos))
            return matched
        return rule
    for name, original in [('link', link), ('image', image),
                           ('backticks', backtick), ('html_inline', html_inline)]:
        parser.inline.ruler.at(name, capture(name, original))
    return parser


def _multiline_ranges(doc, tokens, captures):
    starts = doc.metadata['line_starts'];ranges = set();diagnostics = []
    for token in tokens:
        if token.type != 'inline' or not token.map:
            continue
        low,high = token.map;begin = starts[low]
        end = starts[high] if high < len(starts) else len(doc.text)
        window = doc.text[begin:end]
        for content,a,b in captures:
            if content != token.content:
                continue
            quote = content[a:b]
            if window.count(quote) == 1:
                offset = begin + window.index(quote)
                ranges.add((bisect_right(starts, offset)-1,
                            bisect_right(starts, offset+len(quote)-1)))
            else:
                ranges.add((low, high))
                diagnostics.append({'document_id': doc.id, 'category': 'unsupported_reference',
                                    'source_span': source_span(doc, begin, end)})
    return sorted(ranges), diagnostics


def _resolve(raw, source_path, paths):
    try:
        if re.search(r'%(?![0-9a-fA-F]{2})', raw):
            return None, 'blocked_target', None, None
        parsed = urlsplit(raw)
        if parsed.scheme:
            category = 'external_reference' if parsed.scheme in ('http', 'https') else 'blocked_target'
            return None, category, None, None
        if parsed.netloc or raw.startswith('//'):
            return None, 'blocked_target', None, None
        path = unquote(parsed.path, encoding='utf-8', errors='strict')
        if '%' in path or '\\' in path or '\x00' in path or path.startswith('/') or parsed.query or \
                re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', path):
            return None, 'blocked_target', None, None
        if not path:
            return None, 'local_anchor', None, parsed.fragment or None
        parts = list(PurePosixPath(source_path).parent.parts)
        for part in path.split('/'):
            if part in ('', '.'):
                continue
            if part == '..':
                if not parts:
                    return None, 'blocked_target', None, None
                parts.pop()
            else:
                parts.append(part)
        relative = '/'.join(parts)
        target = paths.get(relative)
        issue = 'target_not_loaded' if target is None else 'fragment_unresolved' if parsed.fragment else None
        return target, issue, relative, parsed.fragment or None
    except (ValueError, UnicodeError):
        return None, 'blocked_target', None, None


def _edge(kind, src, dst, *, quote=None, span=None, raw=None, canonical=None,
          fragment=None, declaration=None, derivation=None):
    record = {'kind': kind, 'from_document_id': src.id, 'to_document_id': dst.id,
              'from_source_sha256': src.metadata['source_sha256'],
              'to_source_sha256': dst.metadata['source_sha256'],
              'quote': quote, 'source_span': span, 'raw_target': raw,
              'canonical_target': canonical, 'fragment': fragment,
              'declaration': declaration, 'derivation': derivation}
    return {'edge_id': 'edge-' + _digest({'policy': POLICY, 'record': record}), **record}


def _scan(doc, sources, paths):
    parser = _parser();full_env = {'_relation_full_ranges': []}
    tokens = parser.parse(doc.text, full_env)
    protected = [t.map for t in tokens if t.type in ('fence', 'code_block', 'html_block') and t.map]
    inline_protected,diagnostics = _multiline_ranges(doc, tokens, full_env['_relation_full_ranges'])
    body_line = min((t.map[0] for t in tokens if t.type == 'heading_open' and
                     t.map and int(t.tag[1:]) >= 2), default=len(doc.metadata['line_starts']))
    title = next((tokens[i+1].content for i,t in enumerate(tokens)
                  if t.type == 'heading_open' and t.level == 0 and t.tag == 'h1'), '')
    stem = PurePosixPath(doc.metadata['source_path']).stem
    is_case = stem.endswith('_测试用例') or '用例' in title
    edges = [];corresponding = []
    def issue(category, start, end):
        diagnostics.append({'document_id': doc.id, 'category': category,
                            'source_span': source_span(doc, start, end)})
    starts = doc.metadata['line_starts']
    for number,start in enumerate(starts):
        if any(low <= number < high for low,high in protected):
            continue
        end = starts[number+1] if number+1 < len(starts) else len(doc.text)
        line = doc.text[start:end].rstrip('\r\n')
        if not line:
            continue
        if any(low <= number < high for low,high in inline_protected):
            field = FIELD.match(line) if number < body_line else None
            if field and _label(parser, field.group('label')) in ('对应需求', '对应模块'):
                corresponding.append(None)
                issue('unsupported_reference', start, start+len(line))
            continue
        env = {'_relation_line': line, '_relation_ranges': []}
        parser.parseInline(line, env)
        ranges = sorted(env['_relation_ranges'], key=lambda item: (item[1], item[2]))
        visible = list(line);declaration = None;header_pair = False
        field = FIELD.match(line) if number < body_line else None
        if field:
            low,high = field.span('label');raw_label = line[low:high]
            declaration = {'label': _label(parser, raw_label), 'quote': raw_label,
                           'source_span': source_span(doc, start+low, start+high)}
            header_pair = declaration['label'] in ('对应需求', '对应模块')
        resolved = [];unsupported = False
        for kind,low,high in ranges:
            visible[low:high] = ' ' * (high-low)
            if kind != 'link':
                continue
            quote = line[low:high];match = DIRECT.fullmatch(quote)
            if not match or '<' in match.group(2) or '>' in match.group(2) or \
                    re.search(r'&(?:#\w+|\w+);', match.group(2)):
                issue('unsupported_reference', start+low, start+high);unsupported = True
                continue
            raw = match.group(2)
            target,category,canonical,fragment = _resolve(raw, doc.metadata['source_path'], paths)
            if category:
                issue(category, start+low, start+high)
            resolved.append(target)
            if target is not None:
                span = source_span(doc, start+low, start+high)
                edges.append(_edge('markdown_link', doc, sources[target], quote=quote, span=span,
                                   raw=raw, canonical=canonical, fragment=fragment, declaration=declaration))
        leftover = ''.join(visible)
        # The native validator rejects some URI schemes before a link token exists.
        # Diagnose those inputs without upgrading a regex match into a document edge.
        for match in DIRECT.finditer(leftover):
            if match.start() and leftover[match.start()-1] in ('!', '\\'):
                continue
            _,category,_,_ = _resolve(match.group(2), doc.metadata['source_path'], paths)
            issue('blocked_target' if category == 'blocked_target' else 'unsupported_reference',
                  start+match.start(), start+match.end())
            unsupported = True
            visible[match.start():match.end()] = ' ' * (match.end()-match.start())
        leftover = ''.join(visible)
        if '](' in leftover or re.search(r'\]\[[^\]]*\]|(?<!\\)\[[^\]\n]+\]:', leftover):
            issue('unsupported_reference', start, start+len(line));unsupported = True
        if header_pair:
            corresponding.extend(resolved if resolved else [None])
            if unsupported:
                corresponding.append(None)
    return edges, diagnostics, corresponding, is_case


def build_document_relations(documents):
    """Describe references and exact filename pairs; no traversal, storage or IO."""
    sources,paths,kb = _registry(documents)
    nodes = [{'document_id': d.id, 'source_path': d.metadata['source_path'],
              'source_sha256': d.metadata['source_sha256']} for d in sources.values()]
    edges = [];diagnostics = [];corresponding = {};case_docs = set()
    try:
        for doc in sources.values():
            found,observed,claims,is_case = _scan(doc, sources, paths)
            edges.extend(found);diagnostics.extend(observed);corresponding[doc.id] = claims
            if is_case:
                case_docs.add(doc.id)
        for did in sorted(case_docs):
            doc = sources[did];stem = unicodedata.normalize('NFC', PurePosixPath(doc.metadata['source_path']).stem)
            category = None
            if not stem.endswith('_测试用例'):
                category = 'unsupported_naming';matches = []
            else:
                wanted = stem.removesuffix('_测试用例')
                matches = [d for d in sources.values() if d.id not in case_docs and
                           unicodedata.normalize('NFC', PurePosixPath(d.metadata['source_path']).stem) == wanted]
                category = 'missing_pair' if not matches else 'ambiguous_pair' if len(matches)>1 else None
            if category is None and any(target != matches[0].id for target in corresponding[did]):
                category = 'pair_conflict'
            if category:
                diagnostics.append({'document_id': did, 'category': category, 'source_span': None})
                continue
            dst = matches[0]
            edges.append(_edge('filename_pair', doc, dst, derivation={
                'rule': 'filename-suffix-v1', 'stem': wanted,
                'case_path': doc.metadata['source_path'], 'origin_path': dst.metadata['source_path']}))
        return {'schema_version': 1, 'policy_id': POLICY, 'knowledge_base_id': kb,
                'source_fingerprint': _digest({'policy': POLICY, 'knowledge_base_id': kb, 'nodes': nodes}),
                'nodes': nodes, 'edges': sorted(edges, key=lambda e:e['edge_id']),
                'diagnostics': sorted(diagnostics, key=lambda d:json.dumps(d, sort_keys=True, ensure_ascii=False))}
    except RelationError:
        raise
    except Exception:
        _fail('relation_parse_failed')
