"""Self-contained encoded pairs with origin references, never a synthetic job."""
import copy
from dataclasses import dataclass
import re
from .encoded_types import EncodedRecord,EncodingResult
from .encoding_types import EncodingInput
from .sparse_types import SparseRecord
from .encoding_report import _hash
from .errors import StorageError


@dataclass(repr=False)
class StoredEncodedRecord:
    input:EncodingInput
    dense_vector:list
    sparse:SparseRecord

    def __post_init__(self):
        try:
            # Reuse pair validation; the temporary zero is not persisted attribution.
            checked=EncodedRecord(self.input,self.dense_vector,self.sparse,0)
            self.input=checked.input;self.dense_vector=checked.dense_vector;self.sparse=checked.sparse
        except Exception:raise StorageError('invalid_index_bundle') from None

    def to_dict(self):
        self.__post_init__()
        return dict(input=self.input.to_dict(),dense_vector=list(self.dense_vector),sparse=self.sparse.to_dict())

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            return cls(EncodingInput.from_dict(data['input']),copy.deepcopy(data['dense_vector']),SparseRecord.from_dict(data['sparse']))
        except Exception:raise StorageError('invalid_index_bundle') from None


@dataclass(repr=False)
class EncodingSnapshot:
    knowledge_base_id:str
    model_space_id:str
    representation_id:str
    tokenizer_id:str
    dimensions:int
    records:list
    origins:list

    def __post_init__(self):
        try:
            if type(self.knowledge_base_id) is not str or not self.knowledge_base_id.strip() or \
                    any(ord(c)<32 for c in self.knowledge_base_id):raise ValueError()
            self.knowledge_base_id.encode('utf-8')
            if any(not _hash(v) for v in (self.model_space_id,self.representation_id,self.tokenizer_id)) or \
                    type(self.dimensions) is not int or self.dimensions<=0:raise ValueError()
            if type(self.records) is not list or type(self.origins) is not list or len(self.records)!=len(self.origins):raise ValueError()
            records=[];origins=[];ids=set();versions={}
            fields={'item_id','kind','source_bundle_id','source_job_id','source_batch_index'}
            for record,origin in zip(self.records,self.origins,strict=True):
                if type(record) is not StoredEncodedRecord:raise ValueError()
                record=StoredEncodedRecord.from_dict(record.to_dict());item=record.input
                if item.item_id in ids or item.knowledge_base_id!=self.knowledge_base_id or \
                        item.model_space_id!=self.model_space_id or item.representation_id!=self.representation_id or \
                        record.sparse.tokenizer_id!=self.tokenizer_id or len(record.dense_vector)!=self.dimensions:raise ValueError()
                if versions.setdefault(item.source_document_id,item.source_sha256)!=item.source_sha256:raise ValueError()
                if type(origin) is not dict or set(origin)!=fields or origin['item_id']!=item.item_id or \
                        origin['kind'] not in ('encoded','reused'):raise ValueError()
                if type(origin['source_job_id']) is not str or re.fullmatch('[0-9a-f]{32}',origin['source_job_id']) is None or \
                        type(origin['source_batch_index']) is not int or origin['source_batch_index']<0:raise ValueError()
                if origin['kind']=='encoded' and origin['source_bundle_id'] is not None or \
                        origin['kind']=='reused' and not _hash(origin['source_bundle_id']):raise ValueError()
                ids.add(item.item_id);records.append(record);origins.append(copy.deepcopy(origin))
            self.records=records;self.origins=origins
        except Exception:raise StorageError('invalid_index_bundle') from None

    def to_dict(self):
        self.__post_init__()
        return dict(knowledge_base_id=self.knowledge_base_id,model_space_id=self.model_space_id,
            representation_id=self.representation_id,tokenizer_id=self.tokenizer_id,dimensions=self.dimensions,
            records=[r.to_dict() for r in self.records],origins=copy.deepcopy(self.origins))

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            raw=copy.deepcopy(data);raw['records']=[StoredEncodedRecord.from_dict(r) for r in raw['records']]
            return cls(**raw)
        except Exception:raise StorageError('invalid_index_bundle') from None

    @classmethod
    def from_result(cls,knowledge_base_id,result):
        if type(result) is not EncodingResult:raise StorageError('invalid_index_bundle')
        result=EncodingResult.from_dict(result.to_dict())
        records=[StoredEncodedRecord(r.input,r.dense_vector,r.sparse) for r in result.records]
        origins=[dict(item_id=r.input.item_id,kind='encoded',source_bundle_id=None,
            source_job_id=result.report.job_id,source_batch_index=r.batch_index) for r in result.records]
        return cls(knowledge_base_id,result.model_space_id,result.representation_id,result.tokenizer_id,
            result.dimensions,records,origins)
