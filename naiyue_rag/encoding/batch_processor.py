"""One batch plan, identity pairing, whole-job failure and retained usage observations."""
import logging
import time
from ..core.encoding_settings import validate_encoding_settings
from ..core.encoding_types import EncodingInput,fail_encoding
from ..core.encoded_types import EncodedRecord,EncodingResult
from ..core.encoding_report import safe_code
from ..core.errors import EncodingError,EmbeddingExecutionError,EncodingJobError
from ..core.sparse_types import SparseRecord
from .validation import ProviderBatchResult
from .input_preparer import plan_encoding_batches
from .batch_report import BatchReport

LOGGER=logging.getLogger(__name__)


class BatchProcessor:
    def __init__(self,settings,dense_encoder,sparse_encoder):
        validate_encoding_settings(settings)
        if dense_encoder.settings.to_dict()!=settings.to_dict() or sparse_encoder.encoding_settings.to_dict()!=settings.to_dict():
            fail_encoding('encoding_settings_mismatch')
        # Initialization/closing stays with the caller. The task stores no shared mutable report.
        self.settings=settings;self.dense_encoder=dense_encoder;self.sparse_encoder=sparse_encoder
        self.tokenizer_id=sparse_encoder.tokenizer_id

    def _remaining(self,start):
        remaining=self.settings.runtime.deadline_seconds-(time.monotonic()-start)
        if remaining<=0:fail_encoding('encoding_deadline_exceeded')
        return remaining

    def _preflight(self,inputs):
        if type(inputs) is not list:fail_encoding('invalid_encoding_input')
        if len(inputs)>self.settings.runtime.max_inputs:fail_encoding('encoding_input_limit')
        private=[];versions={};kb=None
        for item in inputs:
            if type(item) is not EncodingInput:fail_encoding('invalid_encoding_input')
            item=EncodingInput.from_dict(item.to_dict())
            if item.kind!='document':fail_encoding('invalid_encoding_input')
            if kb is None:kb=item.knowledge_base_id
            if kb!=item.knowledge_base_id or versions.setdefault(item.source_document_id,item.source_sha256)!=item.source_sha256:
                fail_encoding('encoding_document_scope_mismatch')
            private.append(item)
        batches=plan_encoding_batches(private,self.settings)
        return private,batches,kb

    def _pair(self,batch,dense,sparse,index):
        if type(sparse) is not list:fail_encoding('encoding_pairing_failed')
        dense=ProviderBatchResult.from_dict(dense.to_dict());by_dense={};by_sparse={}
        for uid,sha,vector in zip(dense.input_ids,dense.input_hashes,dense.vectors):by_dense[uid]=(sha,vector)
        for row in sparse:
            if type(row) is not SparseRecord:fail_encoding('encoding_pairing_failed')
            row=SparseRecord.from_dict(row.to_dict())
            if row.item_id in by_sparse:fail_encoding('encoding_pairing_failed')
            by_sparse[row.item_id]=row
        wanted={i.item_id for i in batch}
        if set(by_dense)!=wanted or set(by_sparse)!=wanted or dense.model_space_id!=self.settings.model_space_id:
            fail_encoding('encoding_pairing_failed')
        records=[]
        for item in batch:
            sha,vector=by_dense[item.item_id];row=by_sparse[item.item_id]
            if sha!=item.embedding_text_sha256 or row.retrieval_text_sha256!=item.retrieval_text_sha256 or \
                    row.kind!=item.kind or row.tokenizer_id!=self.tokenizer_id or len(vector)!=self.settings.embedding.expected_dimensions:
                fail_encoding('encoding_pairing_failed')
            records.append(EncodedRecord(item,vector,row,index))
        return records

    def process(self,document_inputs):
        start=time.monotonic();observations=BatchReport(document_inputs,start);stage='preflight'
        try:
            self._remaining(start)
            inputs,batches,kb=self._preflight(document_inputs)
            observations.planned(inputs,batches);self._remaining(start)
            records=[]
            for index,batch in enumerate(batches):
                stage='dense';observations.enter(batch,index)
                remaining=self._remaining(start)
                used=sum(b['request_report']['attempted_requests'] for b in observations.data['batches'] if b['request_report'] is not None)
                if used>=self.settings.runtime.max_requests:fail_encoding('encoding_request_limit')
                observations.started+=1
                try:
                    value=self.dense_encoder.encode_batch(batch,remaining_seconds=remaining)
                except EmbeddingExecutionError as error:
                    observations.request(error.report)
                    raise
                if type(value) is not tuple or len(value)!=2:fail_encoding('invalid_provider_batch_result')
                dense,request=value
                observations.request(request)
                if sum(b['request_report']['attempted_requests'] for b in observations.data['batches'] if b['request_report'] is not None)>self.settings.runtime.max_requests:
                    fail_encoding('encoding_request_limit')
                if type(dense) is not ProviderBatchResult:fail_encoding('invalid_provider_batch_result')
                dense=ProviderBatchResult.from_dict(dense.to_dict())
                if dense.returned_model not in self.settings.embedding.allowed_response_models:fail_encoding('invalid_provider_batch_result')
                if request['attempted_requests']!=1 or request['error_code'] is not None:fail_encoding('invalid_encoding_report')
                observations.response(dense.to_dict())
                self._remaining(start)
                stage='sparse';observations.stage(stage);self._remaining(start)
                sparse=self.sparse_encoder.encode_batch(batch);self._remaining(start)
                stage='pairing';observations.stage(stage);self._remaining(start)
                paired=self._pair(batch,dense,sparse,index);self._remaining(start)
                records.extend(paired);observations.complete()
            stage='finalize';self._remaining(start)
            result=EncodingResult(kb,self.settings.model_space_id,self.settings.representation_id,self.tokenizer_id,
                self.settings.embedding.expected_dimensions,records,
                observations.snapshot(status='success' if inputs else 'empty'))
            self._remaining(start)
            result.report=observations.snapshot(status='success' if inputs else 'empty')
            self._remaining(start)
            return result
        except Exception as error:
            code=safe_code(error.code if isinstance(error,EncodingError) else None)
            report=observations.snapshot(status='failed',stage=stage,code=code).to_dict()
            LOGGER.error('encoding_job_failed stage=%s code=%s',stage,code)
            raise EncodingJobError(code,report) from None
