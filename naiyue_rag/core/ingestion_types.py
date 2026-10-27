"""Closed, payload-free ingestion result, independent of execution and storage IO."""
from dataclasses import dataclass,field
from .encoding_report import EncodingReport
from .ingestion_encoding_summary import IngestionEncodingSummary
from .errors import IngestionJobError
from ..storage.version_types import ActiveVersion
from ..storage.document_views import DocumentInfo,_active,_bound,_valid_document_id


def _invalid():raise IngestionJobError('validate','ingestion_invalid_request') from None


def _summary(value,report,total):
    if value is None:return None
    if type(value) is not IngestionEncodingSummary:_invalid()
    result=IngestionEncodingSummary.from_dict(value.to_dict())
    observed=None if report is None else report.to_dict()
    expected=None if result.job_report is None else result.job_report.to_dict()
    if result.total_chunk_count!=total or observed!=expected:_invalid()
    return result


@dataclass(frozen=True,repr=False)
class IngestionReceipt:
    status:str
    active:ActiveVersion
    added_document_count:int
    updated_document_count:int
    unchanged_document_count:int
    retained_document_count:int
    encoding_report:EncodingReport|None
    encoding_summary:IngestionEncodingSummary|None=field(default=None,kw_only=True)

    def __post_init__(self):
        try:
            if type(self.status) is not str or self.status not in ('activated','unchanged') or type(self.active) is not ActiveVersion:
                raise ValueError()
            active=ActiveVersion.from_dict(self.active.to_dict())
            counts=[self.added_document_count,self.updated_document_count,self.unchanged_document_count,self.retained_document_count]
            if any(type(n) is not int or n<0 for n in counts) or sum(counts)!=active.version.document_count:raise ValueError()
            report=self.encoding_report
            if report is not None:
                if type(report) is not EncodingReport:raise ValueError()
                report=EncodingReport.from_dict(report.to_dict())
            summary=_summary(self.encoding_summary,report,active.version.chunk_count)
            if summary is None:
                if report is None:
                    if self.status!='unchanged' or self.added_document_count or self.updated_document_count:raise ValueError()
                elif report.status not in ('success','empty') or report.paired_input_count!=active.version.chunk_count:raise ValueError()
            elif self.status=='unchanged' and (self.added_document_count or self.updated_document_count):raise ValueError()
            object.__setattr__(self,'active',active);object.__setattr__(self,'encoding_report',report)
            object.__setattr__(self,'encoding_summary',summary)
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        result=dict(status=self.status,active=self.active.to_dict(),added_document_count=self.added_document_count,
            updated_document_count=self.updated_document_count,unchanged_document_count=self.unchanged_document_count,
            retained_document_count=self.retained_document_count,
            encoding_report=None if self.encoding_report is None else self.encoding_report.to_dict())
        if self.encoding_summary is not None:result['encoding_summary']=self.encoding_summary.to_dict()
        return result

    @classmethod
    def from_dict(cls,data):
        try:
            fields=set(cls.__dataclass_fields__)
            if type(data) is not dict or set(data) not in (fields,fields-{'encoding_summary'}):raise ValueError()
            raw=dict(data);raw['active']=ActiveVersion.from_dict(raw['active'])
            if raw['encoding_report'] is not None:raw['encoding_report']=EncodingReport.from_dict(raw['encoding_report'])
            if 'encoding_summary' in raw:raw['encoding_summary']=IngestionEncodingSummary.from_dict(raw['encoding_summary'])
            return cls(**raw)
        except Exception:_invalid()


@dataclass(frozen=True,repr=False)
class RemovalReceipt:
    status:str
    requested_document_id:str
    previous_active:ActiveVersion|None
    active:ActiveVersion|None
    removed_document:DocumentInfo|None
    encoding_report:EncodingReport|None
    encoding_summary:IngestionEncodingSummary|None=field(default=None,kw_only=True)

    def __post_init__(self):
        try:
            if type(self.status) is not str or self.status not in ('removed','not_found') or \
                    not _valid_document_id(self.requested_document_id):raise ValueError()
            previous=_active(self.previous_active);current=_active(self.active)
            info=self.removed_document;report=self.encoding_report;summary=None
            if self.status=='not_found':
                if previous!=current or info is not None or report is not None or self.encoding_summary is not None:raise ValueError()
            else:
                if previous is None or current is None or type(info) is not DocumentInfo:
                    raise ValueError()
                info=DocumentInfo.from_dict(info.to_dict())
                if report is not None:
                    if type(report) is not EncodingReport:raise ValueError()
                    report=EncodingReport.from_dict(report.to_dict())
                summary=_summary(self.encoding_summary,report,current.version.chunk_count)
                if summary is None and (report is None or report.status not in ('success','empty') or
                    report.paired_input_count!=current.version.chunk_count):raise ValueError()
                _bound(info,previous)
                if info.document_id!=self.requested_document_id or current.revision!=previous.revision+1 or \
                        current.version.knowledge_base_id!=previous.version.knowledge_base_id or \
                        current.version.document_count!=previous.version.document_count-1 or \
                        current.version.version_id==previous.version.version_id:
                    raise ValueError()
            object.__setattr__(self,'previous_active',previous);object.__setattr__(self,'active',current)
            object.__setattr__(self,'removed_document',info);object.__setattr__(self,'encoding_report',report)
            object.__setattr__(self,'encoding_summary',summary)
        except Exception:_invalid()

    def to_dict(self):
        self.__post_init__()
        result=dict(status=self.status,requested_document_id=self.requested_document_id,
            previous_active=None if self.previous_active is None else self.previous_active.to_dict(),
            active=None if self.active is None else self.active.to_dict(),
            removed_document=None if self.removed_document is None else self.removed_document.to_dict(),
            encoding_report=None if self.encoding_report is None else self.encoding_report.to_dict())
        if self.encoding_summary is not None:result['encoding_summary']=self.encoding_summary.to_dict()
        return result

    @classmethod
    def from_dict(cls,data):
        try:
            fields=set(cls.__dataclass_fields__)
            if type(data) is not dict or set(data) not in (fields,fields-{'encoding_summary'}):raise ValueError()
            raw=dict(data)
            for name in ('previous_active','active'):
                if raw[name] is not None:raw[name]=ActiveVersion.from_dict(raw[name])
            if raw['removed_document'] is not None:raw['removed_document']=DocumentInfo.from_dict(raw['removed_document'])
            if raw['encoding_report'] is not None:raw['encoding_report']=EncodingReport.from_dict(raw['encoding_report'])
            if 'encoding_summary' in raw:raw['encoding_summary']=IngestionEncodingSummary.from_dict(raw['encoding_summary'])
            return cls(**raw)
        except Exception:_invalid()
