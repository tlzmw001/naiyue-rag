"""Dataclass contracts, inspired by Modular's shapes, with legacy dict bridges.

Raw source, original spans and retrieval scales remain distinct. No IO happens
here; the loader checks the span against its source and the caller checks scope.
"""
import copy
from dataclasses import dataclass, field
import json
import math
import re

from .errors import ContractError, RetrievalError

SPAN_FIELDS = ('start_char','end_char','line_start','line_end','source_sha256')
UNIT_FIELDS = ('schema_version','unit_id','document_id','source_path','source_sha256','role',
               'semantic_level','directory_level','kind','heading_path','body','body_span','contexts',
               'case_id','case_fields','component_metadata','eligible','diagnostics',
               'rendered_text','rendered_characters')
REQUEST_FIELDS = {'query','scope_document_ids','exclude_document_ids','candidate_k','max_context_chars'}


def _fields(data, names, code, exact=True):
    if type(data) is not dict or (set(data) != set(names) if exact else not set(names) <= set(data)):
        raise ContractError(code)


def _string(value, code, empty=False):
    if type(value) is not str or (not empty and not value):
        raise ContractError(code)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ContractError(code) from None


def _json_tree(value):
    if type(value) is dict:
        if any(type(k) is not str for k in value): raise TypeError()
        for child in value.values(): _json_tree(child)
    elif type(value) is list:
        for child in value: _json_tree(child)
    elif value is not None and type(value) not in (str,int,float,bool):
        raise TypeError()


def _copy_json(value, code):
    try:
        # JSON also rejects circular containers and non-finite numbers.
        json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
        _json_tree(value)
        return copy.deepcopy(value)
    except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):
        raise ContractError(code) from None


def _hash(value, code):
    if type(value) is not str or not re.fullmatch(r'[0-9a-f]{64}',value):
        raise ContractError(code)


def _metadata(value, code):
    if type(value) is not dict: raise ContractError(code)
    result = _copy_json(value,code)
    _string(result.get('source_path'),code)
    _hash(result.get('source_sha256'),code)
    return result


def _ordered(values, order):
    # Preserve legacy key order when known; also retain extension fields.
    return {k:values[k] for k in order if k in values} | {k:v for k,v in values.items() if k not in order}


@dataclass(repr=False)
class SourceSpan:
    start_char: int
    end_char: int
    line_start: int
    line_end: int
    source_sha256: str

    def __post_init__(self):
        values=(self.start_char,self.end_char,self.line_start,self.line_end)
        if any(type(v) is not int for v in values) or not 0 <= self.start_char < self.end_char or \
                not 1 <= self.line_start <= self.line_end:
            raise ContractError('invalid_span')
        _hash(self.source_sha256,'invalid_span')

    @classmethod
    def from_dict(cls,data):
        _fields(data,SPAN_FIELDS,'invalid_span')
        return cls(**data)

    def to_dict(self):
        self.__post_init__()
        return {k:getattr(self,k) for k in SPAN_FIELDS}


@dataclass(repr=False)
class Document:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        _string(self.id,'invalid_document')
        _string(self.text,'invalid_document',empty=True)
        self.metadata=_metadata(self.metadata,'invalid_document')

    @classmethod
    def from_dict(cls,data):
        _fields(data,('id','text','metadata'),'invalid_document')
        return cls(**data)

    @classmethod
    def from_source_record(cls,source):
        _fields(source,('document_id','relative_path','source_sha256','text'),'invalid_document',exact=False)
        metadata={k:v for k,v in source.items() if k not in ('document_id','relative_path','text')}
        metadata['source_path']=source['relative_path']
        return cls(source['document_id'],source['text'],metadata)

    def to_dict(self):
        self.__post_init__()
        return {'id':self.id,'text':self.text,'metadata':copy.deepcopy(self.metadata)}


@dataclass(repr=False)
class Chunk:
    id: str
    text: str
    metadata: dict
    start_offset: int
    end_offset: int
    source_ref: str
    _legacy_order: tuple = field(default=(),init=False,compare=False)

    def __post_init__(self):
        _string(self.id,'invalid_chunk');_string(self.text,'invalid_chunk');_string(self.source_ref,'invalid_chunk')
        self.metadata=_metadata(self.metadata,'invalid_chunk')
        if {'unit_id','body','document_id'} & set(self.metadata):
            raise ContractError('invalid_chunk')
        try:
            span=SourceSpan.from_dict(self.metadata.get('body_span'))
            if type(self.start_offset) is not int or type(self.end_offset) is not int or \
                    self.start_offset != span.start_char or self.end_offset != span.end_char or \
                    span.source_sha256 != self.metadata['source_sha256'] or \
                    self.end_offset-self.start_offset != len(self.text):
                raise ContractError('invalid_chunk')
        except ContractError:
            raise ContractError('invalid_chunk') from None

    @classmethod
    def from_dict(cls,data):
        _fields(data,('id','text','metadata','start_offset','end_offset','source_ref'),'invalid_chunk')
        return cls(**data)

    @classmethod
    def from_legacy_unit(cls,unit):
        _fields(unit,UNIT_FIELDS,'invalid_chunk',exact=False)
        span=SourceSpan.from_dict(unit['body_span'])
        metadata={k:v for k,v in unit.items() if k not in ('unit_id','body','document_id')}
        result=cls(unit['unit_id'],unit['body'],metadata,span.start_char,span.end_char,unit['document_id'])
        result._legacy_order=tuple(unit)
        return result

    def to_dict(self):
        self.__post_init__()
        return {'id':self.id,'text':self.text,'metadata':copy.deepcopy(self.metadata),
                'start_offset':self.start_offset,'end_offset':self.end_offset,'source_ref':self.source_ref}

    def to_legacy_unit(self):
        self.__post_init__()
        values=copy.deepcopy(self.metadata)|{'unit_id':self.id,'body':self.text,'document_id':self.source_ref}
        _fields(values,UNIT_FIELDS,'invalid_chunk',exact=False)
        return _ordered(values,self._legacy_order or UNIT_FIELDS)


@dataclass(repr=False)
class QueryRequest:
    query: str
    scope_document_ids: list | None
    exclude_document_ids: list
    candidate_k: int
    max_context_chars: int

    def __post_init__(self):
        try:
            if type(self.query) is not str or not self.query.strip() or len(self.query.encode('utf-8')) > 3072:
                raise ValueError()
        except (ValueError,UnicodeError):
            raise RetrievalError('request','invalid_query') from None
        for name in ['scope_document_ids','exclude_document_ids']:
            values=getattr(self,name)
            if name=='scope_document_ids' and values is None:continue
            if type(values) is not list or any(type(i) is not str or not i for i in values) or \
                    len(set(values)) != len(values) or (name=='scope_document_ids' and not values):
                raise RetrievalError('request','invalid_scope')
        if type(self.candidate_k) is not int or not 0 < self.candidate_k <= 20:
            raise RetrievalError('request','invalid_candidate_k')
        if type(self.max_context_chars) is not int or not 0 < self.max_context_chars <= 8000:
            raise RetrievalError('request','invalid_context_budget')
        self.scope_document_ids=copy.deepcopy(self.scope_document_ids)
        self.exclude_document_ids=copy.deepcopy(self.exclude_document_ids)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data) != REQUEST_FIELDS:
            raise RetrievalError('request','invalid_request')
        return cls(**data)

    def to_dict(self):
        self.__post_init__()
        return {k:copy.deepcopy(getattr(self,k)) for k in
                ['query','scope_document_ids','exclude_document_ids','candidate_k','max_context_chars']}


@dataclass(repr=False)
class RetrievalResult:
    chunk_id: str
    score: float
    text: str
    metadata: dict
    _candidate_order: tuple = field(default=(),init=False,compare=False)

    def __post_init__(self):
        _string(self.chunk_id,'invalid_result');_string(self.text,'invalid_result')
        try:
            if type(self.score) not in (int,float) or not math.isfinite(self.score):
                raise ValueError()
        except (ValueError,OverflowError):
            raise ContractError('invalid_result') from None
        self.metadata=_metadata(self.metadata,'invalid_result')
        if {'unit_id','body','score'} & set(self.metadata):
            raise ContractError('invalid_result')

    @classmethod
    def from_dict(cls,data):
        _fields(data,('chunk_id','score','text','metadata'),'invalid_result')
        return cls(**data)

    @classmethod
    def from_candidate(cls,row):
        _fields(row,('unit_id','body','score','rank','retrieval_method'),'invalid_result',exact=False)
        if type(row['rank']) is not int or row['rank'] <= 0:
            raise ContractError('invalid_result')
        _string(row['retrieval_method'],'invalid_result')
        metadata={k:v for k,v in row.items() if k not in ('unit_id','score','body')}
        result=cls(row['unit_id'],row['score'],row['body'],metadata)
        result._candidate_order=tuple(row)
        return result

    def to_dict(self):
        self.__post_init__()
        return {'chunk_id':self.chunk_id,'score':self.score,'text':self.text,'metadata':copy.deepcopy(self.metadata)}

    def to_candidate(self):
        self.__post_init__()
        values=copy.deepcopy(self.metadata)|{'unit_id':self.chunk_id,'score':self.score,'body':self.text}
        _fields(values,UNIT_FIELDS+('score','rank','retrieval_method'),'invalid_result',exact=False)
        if type(values['rank']) is not int or values['rank'] <= 0:
            raise ContractError('invalid_result')
        _string(values['retrieval_method'],'invalid_result')
        return _ordered(values,self._candidate_order or UNIT_FIELDS)
