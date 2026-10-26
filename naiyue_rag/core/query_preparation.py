"""A pinned internal execution result, not a final evidence/tool response."""
import copy
from dataclasses import dataclass
import re
from .encoding_report import _hash
from .query_encoding_types import QueryEncodingResult
from .errors import QueryJobError
from .trace_context import validate_trace_report
from ..storage.version_types import ActiveVersion


def _invalid():raise QueryJobError('request','query_invalid_request') from None


def _ids(values,prefix):
    if type(values) is not list or any(type(v) is not str or re.fullmatch(prefix+'-[0-9a-f]{64}',v) is None for v in values) or \
            values!=sorted(set(values)):_invalid()
    return list(values)


@dataclass(frozen=True,repr=False)
class PreparedQuery:
    status:str
    active:ActiveVersion|None
    query_sha256:str
    document_ids:list
    chunk_ids:list
    encoding:QueryEncodingResult|None
    trace_report:dict

    def __post_init__(self):
        try:
            if type(self.status) is not str or self.status not in ('ready','unactivated','empty_scope','empty_index') or \
                    not _hash(self.query_sha256):raise ValueError()
            active=self.active
            if active is not None:
                if type(active) is not ActiveVersion:raise ValueError()
                active=ActiveVersion.from_dict(active.to_dict())
            docs=_ids(self.document_ids,'doc');chunks=_ids(self.chunk_ids,'unit');encoding=self.encoding
            if self.status=='unactivated':
                if active is not None or docs or chunks or encoding is not None:raise ValueError()
            else:
                if active is None:raise ValueError()
                version=active.version
                if len(docs)>version.document_count or len(chunks)>version.chunk_count:raise ValueError()
                if self.status=='ready':
                    if not docs or not chunks or type(encoding) is not QueryEncodingResult:raise ValueError()
                    encoding=QueryEncodingResult.from_dict(encoding.to_dict())
                    if encoding.input.query_sha256!=self.query_sha256 or \
                            (encoding.input.model_space_id,encoding.input.representation_id,encoding.tokenizer_id,encoding.dimensions)!= \
                            (version.model_space_id,version.representation_id,version.tokenizer_id,version.dimensions):raise ValueError()
                else:
                    if chunks or encoding is not None:raise ValueError()
                    if self.status=='empty_scope' and (version.document_count==0 or docs):raise ValueError()
                    if self.status=='empty_index' and ((version.document_count==0 and docs) or
                                                       (version.document_count>0 and not docs)):raise ValueError()
            trace=copy.deepcopy(self.trace_report);validate_trace_report(trace)
            if trace['status']!='success':raise ValueError()
            expected=['request']+([] if active is None else ['resources'])+(['embedding'] if self.status=='ready' else [])
            if [s['stage'] for s in trace['stages']]!=expected:raise ValueError()
            if active is not None and trace['stages'][1]['data']!=dict(status='verified',
                corpus_id=active.version.source_fingerprint,index_id=active.version.version_id):raise ValueError()
            if encoding is not None:
                batch=encoding.report.batches[0]
                if trace['stages'][2]['data']!=dict(adapter_calls=encoding.report.requests['dense_calls_started'],
                    source_kind=batch['source_kind'],usage=batch['usage']):raise ValueError()
            object.__setattr__(self,'active',active);object.__setattr__(self,'document_ids',docs)
            object.__setattr__(self,'chunk_ids',chunks);object.__setattr__(self,'encoding',encoding)
            object.__setattr__(self,'trace_report',trace)
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        return dict(status=self.status,active=None if self.active is None else self.active.to_dict(),
            query_sha256=self.query_sha256,document_ids=list(self.document_ids),chunk_ids=list(self.chunk_ids),
            encoding=None if self.encoding is None else self.encoding.to_dict(),trace_report=copy.deepcopy(self.trace_report))

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            raw=copy.deepcopy(data)
            if raw['active'] is not None:raw['active']=ActiveVersion.from_dict(raw['active'])
            if raw['encoding'] is not None:raw['encoding']=QueryEncodingResult.from_dict(raw['encoding'])
            return cls(**raw)
        except Exception:_invalid()
