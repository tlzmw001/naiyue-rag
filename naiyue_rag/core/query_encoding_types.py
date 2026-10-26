"""Complete, source-free query representation for future Dense/BM25 consumers."""
import copy
from dataclasses import dataclass
import math
import re
from .encoding_types import EncodingInput,fail_encoding
from .sparse_types import SparseRecord
from .encoding_report import EncodingReport,input_fingerprint


@dataclass(repr=False)
class QueryEncodingResult:
    input:EncodingInput
    dense_vector:list
    sparse:SparseRecord
    query_terms:list
    tokenizer_id:str
    dimensions:int
    report:EncodingReport

    def __post_init__(self):
        try:
            if type(self.input) is not EncodingInput or type(self.sparse) is not SparseRecord or type(self.report) is not EncodingReport:raise ValueError()
            self.input=EncodingInput.from_dict(self.input.to_dict())
            self.sparse=SparseRecord.from_dict(self.sparse.to_dict())
            self.report=EncodingReport.from_dict(self.report.to_dict())
            if self.input.kind!='query' or self.input.item_id!='query-'+self.input.query_sha256:raise ValueError()
            if self.sparse.kind!='query' or self.sparse.item_id!=self.input.item_id or \
                    self.sparse.retrieval_text_sha256!=self.input.retrieval_text_sha256:raise ValueError()
            if type(self.tokenizer_id) is not str or re.fullmatch('[0-9a-f]{64}',self.tokenizer_id) is None or \
                    self.sparse.tokenizer_id!=self.tokenizer_id:raise ValueError()
            if type(self.dimensions) is not int or self.dimensions<=0 or type(self.dense_vector) is not list or \
                    len(self.dense_vector)!=self.dimensions or any(type(v) not in (int,float) or not math.isfinite(v) for v in self.dense_vector):raise ValueError()
            norm=math.hypot(*self.dense_vector)
            if not math.isfinite(norm) or norm==0:raise ValueError()
            if type(self.query_terms) is not list or self.query_terms!=list(dict.fromkeys(self.sparse.tokens)):raise ValueError()
            report=self.report
            if report.status!='success' or report.input_count!=1 or report.planned_batch_count!=1 or \
                    report.completed_batch_count!=1 or report.paired_input_count!=1 or len(report.batches)!=1:raise ValueError()
            batch=report.batches[0];fingerprint=input_fingerprint([self.input])
            if report.input_fingerprint!=fingerprint or batch['input_fingerprint']!=fingerprint or \
                    batch['input_start']!=0 or batch['input_end']!=1 or batch['stage']!='complete':raise ValueError()
            self.dense_vector=list(self.dense_vector);self.query_terms=list(self.query_terms)
        except Exception:fail_encoding('invalid_query_encoding_result')

    def to_dict(self):
        self.__post_init__()
        return dict(input=self.input.to_dict(),dense_vector=list(self.dense_vector),sparse=self.sparse.to_dict(),
            query_terms=list(self.query_terms),tokenizer_id=self.tokenizer_id,dimensions=self.dimensions,report=self.report.to_dict())

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            values=copy.deepcopy(data)
            values['input']=EncodingInput.from_dict(values['input'])
            values['sparse']=SparseRecord.from_dict(values['sparse'])
            values['report']=EncodingReport.from_dict(values['report'])
            return cls(**values)
        except Exception:fail_encoding('invalid_query_encoding_result')
