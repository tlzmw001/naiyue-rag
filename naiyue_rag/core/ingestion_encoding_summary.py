"""Current ingestion work and request observations, independent of snapshot size."""
from dataclasses import dataclass
from .encoding_report import EncodingReport,_integer
from .encoded_types import EncodedRecord,EncodingResult
from .encoding_snapshot import EncodingSnapshot
from .errors import StorageError


@dataclass(frozen=True,repr=False)
class IngestionEncodingSummary:
    total_chunk_count:int
    encoded_chunk_count:int
    reused_chunk_count:int
    job_report:EncodingReport|None

    def __post_init__(self):
        try:
            if any(not _integer(n) for n in (self.total_chunk_count,self.encoded_chunk_count,self.reused_chunk_count)) or \
                    self.total_chunk_count!=self.encoded_chunk_count+self.reused_chunk_count:raise ValueError()
            report=self.job_report
            if self.encoded_chunk_count==0:
                if report is not None:raise ValueError()
            else:
                if type(report) is not EncodingReport:raise ValueError()
                report=EncodingReport.from_dict(report.to_dict())
                if report.status!='success' or report.paired_input_count!=self.encoded_chunk_count:raise ValueError()
            object.__setattr__(self,'job_report',report)
        except Exception:raise StorageError('invalid_index_bundle') from None

    def validate_snapshot(self,snapshot):
        self.__post_init__()
        try:
            if type(snapshot) is not EncodingSnapshot:raise ValueError()
            snapshot=EncodingSnapshot.from_dict(snapshot.to_dict());records=[]
            if len(snapshot.records)!=self.total_chunk_count:raise ValueError()
            for record,origin in zip(snapshot.records,snapshot.origins,strict=True):
                if origin['kind']=='encoded':
                    if self.job_report is None or origin['source_job_id']!=self.job_report.job_id:raise ValueError()
                    records.append(EncodedRecord(record.input,record.dense_vector,record.sparse,origin['source_batch_index']))
            if len(records)!=self.encoded_chunk_count:raise ValueError()
            if records:
                EncodingResult(snapshot.knowledge_base_id,snapshot.model_space_id,snapshot.representation_id,
                    snapshot.tokenizer_id,snapshot.dimensions,records,self.job_report)
        except Exception:raise StorageError('invalid_index_bundle') from None

    def to_dict(self):
        self.__post_init__()
        return dict(total_chunk_count=self.total_chunk_count,encoded_chunk_count=self.encoded_chunk_count,
            reused_chunk_count=self.reused_chunk_count,job_report=None if self.job_report is None else self.job_report.to_dict())

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            raw=dict(data)
            if raw['job_report'] is not None:raw['job_report']=EncodingReport.from_dict(raw['job_report'])
            return cls(**raw)
        except Exception:raise StorageError('invalid_index_bundle') from None
