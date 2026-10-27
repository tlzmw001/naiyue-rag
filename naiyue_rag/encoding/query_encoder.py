"""Single-query orchestration; no retrieval, scope policy, rewriting or client ownership."""
import logging
import time
from ..core.encoding_settings import validate_encoding_settings
from ..core.encoding_types import fail_encoding,text_sha
from ..core.query_encoding_types import QueryEncodingResult
from ..core.encoding_report import safe_code
from ..core.errors import EncodingError,EmbeddingExecutionError,EncodingJobError
from ..core.sparse_types import SparseRecord
from .validation import ProviderBatchResult
from .input_preparer import prepare_query_encoding_input,plan_encoding_batches
from .batch_report import BatchReport

LOGGER=logging.getLogger(__name__)


class QueryEncoder:
    def __init__(self,settings,dense_encoder,sparse_encoder):
        validate_encoding_settings(settings)
        if dense_encoder.settings.to_dict()!=settings.to_dict() or sparse_encoder.encoding_settings.to_dict()!=settings.to_dict():
            fail_encoding('encoding_settings_mismatch')
        self.settings=settings;self.dense_encoder=dense_encoder;self.sparse_encoder=sparse_encoder
        self.tokenizer_id=sparse_encoder.tokenizer_id

    def _remaining(self,start):
        remaining=self.settings.runtime.deadline_seconds-(time.monotonic()-start)
        if remaining<=0:fail_encoding('encoding_deadline_exceeded')
        return remaining

    def _pair(self,item,dense,sparse):
        if dense.input_ids!=[item.item_id] or dense.input_hashes!=[item.embedding_text_sha256] or \
                dense.model_space_id!=self.settings.model_space_id or len(dense.vectors[0])!=self.settings.embedding.expected_dimensions:
            fail_encoding('encoding_pairing_failed')
        if type(sparse) is not list or len(sparse)!=1 or type(sparse[0]) is not SparseRecord:fail_encoding('encoding_pairing_failed')
        row=SparseRecord.from_dict(sparse[0].to_dict())
        if row.item_id!=item.item_id or row.kind!='query' or row.retrieval_text_sha256!=item.retrieval_text_sha256 or row.tokenizer_id!=self.tokenizer_id:
            fail_encoding('encoding_pairing_failed')
        return list(dense.vectors[0]),row

    def encode(self,query):
        start=time.monotonic();observations=BatchReport([query],start);stage='preflight'
        try:
            self._remaining(start)
            item=prepare_query_encoding_input(query,self.settings)
            batch=[item];batches=plan_encoding_batches(batch,self.settings)
            observations.planned(batch,batches);self._remaining(start)
            stage='dense';observations.enter(batch,0);remaining=self._remaining(start)
            observations.started+=1
            try:
                value=self.dense_encoder.encode_batch(batch,remaining_seconds=remaining)
            except EmbeddingExecutionError as error:
                observations.request(error.report)
                raise
            if type(value) is not tuple or len(value)!=2:fail_encoding('invalid_provider_batch_result')
            dense,request=value;observations.request(request)
            if request['attempted_requests']>self.settings.runtime.max_requests:fail_encoding('encoding_request_limit')
            if type(dense) is not ProviderBatchResult:fail_encoding('invalid_provider_batch_result')
            dense=ProviderBatchResult.from_dict(dense.to_dict())
            if dense.returned_model not in self.settings.embedding.allowed_response_models:fail_encoding('invalid_provider_batch_result')
            if request['attempted_requests']!=1 or request['error_code'] is not None:fail_encoding('invalid_encoding_report')
            observations.response(dense.to_dict());self._remaining(start)
            stage='sparse';observations.stage(stage);self._remaining(start)
            sparse=self.sparse_encoder.encode_batch(batch);self._remaining(start)
            stage='pairing';observations.stage(stage);self._remaining(start)
            vector,row=self._pair(item,dense,sparse);self._remaining(start)
            terms=list(dict.fromkeys(row.tokens));observations.complete()
            stage='finalize';self._remaining(start)
            result=QueryEncodingResult(item,vector,row,terms,self.tokenizer_id,
                self.settings.embedding.expected_dimensions,observations.snapshot(status='success'),raw_query_sha256=text_sha(query))
            self._remaining(start)
            result.report=observations.snapshot(status='success');self._remaining(start)
            return result
        except Exception as error:
            code=safe_code(error.code if isinstance(error,EncodingError) else None)
            report=observations.snapshot(status='failed',stage=stage,code=code).to_dict()
            LOGGER.error('query_encoding_failed stage=%s code=%s',stage,code)
            raise EncodingJobError(code,report) from None
