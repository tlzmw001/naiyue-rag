"""An indivisible source-bound Dense/Sparse pair and a complete job result."""
import copy
from dataclasses import dataclass
import math
import re
from .encoding_types import EncodingInput,fail_encoding
from .sparse_types import SparseRecord
from .encoding_report import EncodingReport,input_fingerprint


@dataclass(repr=False)
class EncodedRecord:
    input:EncodingInput
    dense_vector:list
    sparse:SparseRecord
    batch_index:int

    def __post_init__(self):
        try:
            if type(self.input) is not EncodingInput or type(self.sparse) is not SparseRecord:raise ValueError()
            self.input=EncodingInput.from_dict(self.input.to_dict())
            self.sparse=SparseRecord.from_dict(self.sparse.to_dict())
            if self.input.kind!='document' or self.sparse.kind!=self.input.kind or \
                    self.sparse.item_id!=self.input.item_id or self.sparse.retrieval_text_sha256!=self.input.retrieval_text_sha256:raise ValueError()
            if type(self.batch_index) is not int or self.batch_index<0:raise ValueError()
            if type(self.dense_vector) is not list or not self.dense_vector or \
                    any(type(v) not in (int,float) or not math.isfinite(v) for v in self.dense_vector):raise ValueError()
            norm=math.hypot(*self.dense_vector)
            if not math.isfinite(norm) or norm==0:raise ValueError()
            self.dense_vector=list(self.dense_vector)
        except Exception:fail_encoding('invalid_encoded_record')

    def to_dict(self):
        self.__post_init__()
        return dict(input=self.input.to_dict(),dense_vector=list(self.dense_vector),
                    sparse=self.sparse.to_dict(),batch_index=self.batch_index)

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            return cls(EncodingInput.from_dict(data['input']),copy.deepcopy(data['dense_vector']),
                       SparseRecord.from_dict(data['sparse']),data['batch_index'])
        except Exception:fail_encoding('invalid_encoded_record')


@dataclass(repr=False)
class EncodingResult:
    knowledge_base_id:str|None
    model_space_id:str
    representation_id:str
    tokenizer_id:str
    dimensions:int
    records:list
    report:EncodingReport

    def __post_init__(self):
        try:
            if any(type(v) is not str or re.fullmatch('[0-9a-f]{64}',v) is None for v in
                    [self.model_space_id,self.representation_id,self.tokenizer_id]):raise ValueError()
            if type(self.dimensions) is not int or self.dimensions<=0 or type(self.records) is not list:raise ValueError()
            if type(self.report) is not EncodingReport:raise ValueError()
            self.report=EncodingReport.from_dict(self.report.to_dict())
            if self.report.status not in ('success','empty') or len(self.records)!=self.report.input_count:raise ValueError()
            if not self.records:
                if self.knowledge_base_id is not None or self.report.status!='empty':raise ValueError()
            elif type(self.knowledge_base_id) is not str or not self.knowledge_base_id or self.report.status!='success':raise ValueError()
            records=[];ids=set();versions={}
            for record in self.records:
                if type(record) is not EncodedRecord:raise ValueError()
                record=EncodedRecord.from_dict(record.to_dict());item=record.input
                if item.item_id in ids or item.knowledge_base_id!=self.knowledge_base_id or \
                        item.model_space_id!=self.model_space_id or item.representation_id!=self.representation_id or \
                        record.sparse.tokenizer_id!=self.tokenizer_id or len(record.dense_vector)!=self.dimensions:raise ValueError()
                ids.add(item.item_id)
                if versions.setdefault(item.source_document_id,item.source_sha256)!=item.source_sha256:raise ValueError()
                records.append(record)
            if input_fingerprint([r.input for r in records])!=self.report.input_fingerprint:raise ValueError()
            for batch in self.report.batches:
                group=records[batch['input_start']:batch['input_end']]
                if len(group)!=batch['input_count'] or any(r.batch_index!=batch['index'] for r in group) or \
                        input_fingerprint([r.input for r in group])!=batch['input_fingerprint']:raise ValueError()
            self.records=records
        except Exception:fail_encoding('invalid_encoding_result')

    def to_dict(self):
        self.__post_init__()
        return dict(knowledge_base_id=self.knowledge_base_id,model_space_id=self.model_space_id,
            representation_id=self.representation_id,tokenizer_id=self.tokenizer_id,dimensions=self.dimensions,
            records=[r.to_dict() for r in self.records],report=self.report.to_dict())

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            values=copy.deepcopy(data)
            values['records']=[EncodedRecord.from_dict(r) for r in values['records']]
            values['report']=EncodingReport.from_dict(values['report'])
            return cls(**values)
        except Exception:fail_encoding('invalid_encoding_result')
