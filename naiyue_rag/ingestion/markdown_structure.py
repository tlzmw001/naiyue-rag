"""Markdown syntax maps converted to untouched source regions, never cleaned text."""
from bisect import bisect_right
import copy
import hashlib
import logging
from pathlib import PurePosixPath
import re

from markdown_it import MarkdownIt

from ..core.errors import ChunkingError, ContractError
from ..core.types import Document, SourceSpan

LOGGER=logging.getLogger(__name__)
ALIASES={'name':{'用例名称','用例标题'}, 'preconditions':{'前提条件','前置条件'},
         'steps':{'测试步骤'}, 'expected':{'预期结果'}, 'id':{'序号','编号','用例编号','用例ID','ID'}}


def fail_chunking(code):
    LOGGER.error('chunking_failed stage=chunking code=%s',code)
    raise ChunkingError(code) from None


def validate_document(document):
    try:
        if not isinstance(document,Document): raise ValueError()
        document.to_dict()
        text=document.text; raw=text.encode('utf-8'); meta=document.metadata
        starts=[0] if text else []
        starts.extend(m.end() for m in re.finditer(r'\r\n|\r|\n',text) if m.end()<len(text))
        if meta.get('source_sha256')!=hashlib.sha256(raw).hexdigest() or \
                type(meta.get('size_bytes')) is not int or meta['size_bytes']!=len(raw) or \
                type(meta.get('line_starts')) is not list or meta['line_starts']!=starts or \
                any(type(i) is not int for i in meta['line_starts']): raise ValueError()
    except (ContractError,ValueError,TypeError,KeyError,UnicodeError):
        fail_chunking('invalid_chunking_document')


def source_span(document,start,end):
    try:
        starts=document.metadata['line_starts']
        if not 0<=start<end<=len(document.text): raise ValueError()
        return SourceSpan(start,end,bisect_right(starts,start),bisect_right(starts,end-1),
                          document.metadata['source_sha256']).to_dict()
    except (ContractError,ValueError,TypeError,KeyError):
        fail_chunking('invalid_chunking_document')


def _interval(document,line_map):
    starts=document.metadata['line_starts']; text=document.text
    if type(line_map) is not list or len(line_map)!=2 or \
            any(type(i) is not int for i in line_map) or not 0<=line_map[0]<line_map[1]<=len(starts):
        fail_chunking('structure_failed')
    start=starts[line_map[0]]
    end=starts[line_map[1]] if line_map[1]<len(starts) else len(text)
    while end>start and text[end-1] in '\r\n':end-=1
    return start,end


def _context(document,kind,start,end):
    return {'context_kind':kind,'text':document.text[start:end],'span':source_span(document,start,end)}


def _cells(line):
    text=line.strip(); cells=['']; escaped=False
    for char in text:
        if char=='|' and not escaped: cells.append('')
        else: cells[-1]+=char
        escaped=char=='\\' and not escaped
    if text.startswith('|'):cells=cells[1:]
    if cells and cells[-1]=='' and text.endswith('|'):cells=cells[:-1]
    return [c.strip() for c in cells]


def _label(parser,value):
    children=parser.parseInline(value)[0].children or []
    return ''.join(t.content for t in children if t.type in ('text','code_inline')).strip()


def _headings_at(headings,start):
    stack=[]
    for heading in headings:
        if heading['start']>start:break
        while stack and stack[-1]['level']>=heading['level']:stack.pop()
        stack.append(heading)
    return stack


def _block(document,kind,start,end,headings,title,classification):
    chain=_headings_at(headings,start)
    contexts=[]
    if title:contexts.append(_context(document,'document_title',title['start'],title['end']))
    for heading in chain:
        if title and heading['start']==title['start']:continue
        contexts.append(_context(document,'section_heading',heading['start'],heading['end']))
    return {'kind':kind,'start':start,'end':end,'headings':copy.deepcopy(chain),'contexts':contexts,
            'case_id':None,'case_fields':[],'case_columns':[],'classification':dict(classification)}


def _table_blocks(document,tokens,table,headings,title,notes,classification,parser):
    start,end=_interval(document,table.map); text=document.text
    rows=[t for t in tokens if t.type=='tr_open' and t.map and table.map[0]<=t.map[0]<table.map[1]]
    if not rows:fail_chunking('invalid_table')
    row_ranges=[_interval(document,t.map) for t in rows]
    raw_cells=[_cells(text[a:b]) for a,b in row_ranges]
    count=len(raw_cells[0])
    if not count or any(len(c)!=count for c in raw_cells):fail_chunking('invalid_table')
    if len(row_ranges)==1:
        return [_block(document,'table',start,end,headings,title,classification)],[]
    labels=[_label(parser,c) for c in raw_cells[0]]
    matched={key:[i for i,c in enumerate(labels) if c in aliases] for key,aliases in ALIASES.items()}
    recognizable=all(len(matched[k])==1 for k in ['name','preconditions','steps','expected'])
    if classification['kind']!='test_cases' or not recognizable:
        issues=[]
        if classification['kind']=='test_cases':
            issues=[{'category':'unclassified_case_table','severity':'warning','document_id':document.id,
                     'span':source_span(document,start,end)}]
        return [_block(document,'table',start,end,headings,title,classification)],issues
    if any(len(v)>1 for v in matched.values()):fail_chunking('invalid_table')
    hs,he=row_ranges[0]; columns=_context(document,'columns',hs,he)
    separator=_interval(document,[table.map[0]+1,table.map[0]+2])
    output=[]
    for (a,b),values in zip(row_ranges[1:],raw_cells[1:]):
        block=_block(document,'test_case',a,b,headings,title,classification)
        if block['headings']:
            dimension=block['headings'][-1]
            if dimension['level']>1:
                block['contexts']=[c for c in block['contexts'] if c['span']['start_char']!=dimension['start']]
                block['contexts'].append(_context(document,'dimension',dimension['start'],dimension['end']))
        block['contexts'].extend([columns,_context(document,'column_separator',*separator)])
        lower=block['headings'][-1]['end'] if block['headings'] else 0
        block['contexts'].extend(_context(document,'source_note',ns,ne) for ns,ne in notes if lower<=ns<start)
        block['case_columns']=raw_cells[0][:];block['case_fields']=values[:]
        if matched['id']:block['case_id']=values[matched['id'][0]] or None
        output.append(block)
    return output,[]


def scan_document(document):
    """Return source blocks and structural diagnostics for a validated Document."""
    validate_document(document)
    if not document.text.strip():
        return [],[{'category':'empty_source','severity':'info','document_id':document.id}]
    try:
        parser=MarkdownIt('commonmark').enable('table')
        tokens=parser.parse(document.text)
        headings=[];protected=[];notes=[]
        for index,token in enumerate(tokens):
            if token.type=='heading_open' and token.level==0:
                a,b=_interval(document,token.map)
                headings.append({'start':a,'end':b,'level':int(token.tag[1:]),
                                 'text':document.text[a:b],'label':tokens[index+1].content})
            elif token.type in ('fence','code_block','table_open'):
                a,b=_interval(document,token.map)
                protected.append((a,b,token))
            elif token.type=='blockquote_open' and token.level==0:
                notes.append(_interval(document,token.map))
        title=next((h for h in headings if h['level']==1),None)
        stem=PurePosixPath(document.metadata['source_path']).stem
        classification={'kind':'text','basis':'ordinary_document'}
        if stem.endswith('_测试用例'):classification={'kind':'test_cases','basis':'filename_suffix'}
        elif title and '用例' in title['label']:classification={'kind':'test_cases','basis':'title_marker'}
        # Keep outer protected blocks if syntax maps overlap.
        protected.sort(key=lambda p:(p[0],-p[1]));outer=[]
        for item in protected:
            if not any(a<=item[0] and item[1]<=b for a,b,_ in outer):outer.append(item)
        if classification['kind']=='test_cases':
            starts=document.metadata['line_starts']
            for number,offset in enumerate(starts):
                end=starts[number+1] if number+1<len(starts) else len(document.text)
                line=document.text[offset:end].rstrip('\r\n')
                if re.fullmatch(r'\s*\|.*\|\s*',line) and len(_cells(line))>1 and \
                        not any(a<=offset<b for a,b,_ in outer):
                    fail_chunking('invalid_table')
        notes=[(a,b) for a,b in notes if not any(a<pe and ps<b for ps,pe,_ in outer)]
        boundaries=sorted({0,len(document.text)}|{h['start'] for h in headings}|
                          {x for a,b,_ in outer for x in (a,b)})
        blocks=[];issues=[]
        for a,b in zip(boundaries,boundaries[1:]):
            if any(ps<=a<pe for ps,pe,_ in outer):continue
            while b>a and document.text[b-1] in '\r\n':b-=1
            if document.text[a:b].strip():blocks.append(_block(document,'text',a,b,headings,title,classification))
        for a,b,token in outer:
            if token.type=='table_open':
                adapted,observed=_table_blocks(document,tokens,token,headings,title,notes,classification,parser)
                blocks.extend(adapted);issues.extend(observed)
            else:blocks.append(_block(document,'code',a,b,headings,title,classification))
        starts=document.metadata['line_starts']
        for m in re.finditer(r'(?<![\w-])L(\d+)-L?(\d+)(?![\w-])',document.text):
            if any(a<=m.start()<b and t.type in ('fence','code_block') for a,b,t in outer):continue
            low,high=map(int,m.groups())
            if low<1 or high<low or high>len(starts):
                issues.append({'category':'stale_header_line_range','severity':'warning',
                               'document_id':document.id,'span':source_span(document,m.start(),m.end())})
        blocks.sort(key=lambda b:(b['start'],b['end']))
        if not blocks:fail_chunking('structure_failed')
        return blocks,issues
    except ChunkingError:
        raise
    except Exception:
        fail_chunking('structure_failed')
