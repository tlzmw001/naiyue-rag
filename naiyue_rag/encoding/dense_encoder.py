"""Bind a single planned batch to validated vectors, without a second batching loop."""
import time
from ..core.encoding_settings import validate_encoding_settings
from ..core.errors import EncodingError,EmbeddingExecutionError
from .execution_report import new_report,raise_execution_error,valid_seconds
from .input_preparer import plan_encoding_batches
from .validation import normalize_embedding_response


class DenseEncoder:
    def __init__(self,settings,provider):
        validate_encoding_settings(settings)
        if provider.settings.to_dict()!=settings.to_dict():
            raise_execution_error('embedding_provider_settings_mismatch',new_report())
        self.settings=settings;self.provider=provider

    def encode_batch(self,inputs,*,remaining_seconds):
        start=time.monotonic();report=new_report()
        try:
            if not valid_seconds(remaining_seconds):raise_execution_error('embedding_invalid_timeout',report)
            deadline=start+min(remaining_seconds,self.settings.runtime.deadline_seconds)
            batches=plan_encoding_batches(inputs,self.settings)
            if len(batches)!=1:raise_execution_error('embedding_invalid_batch',report)
            remaining=deadline-time.monotonic()
            if remaining<=0:raise_execution_error('embedding_deadline_exceeded',report)
            payload,report=self.provider.embed([i.embedding_text for i in inputs],timeout_seconds=remaining)
            result=normalize_embedding_response(payload,inputs,self.settings,source_kind='service')
            if time.monotonic()>=deadline:raise_execution_error('embedding_deadline_exceeded',report)
            report['elapsed_seconds']=max(0.,time.monotonic()-start)
            return result,report
        except EmbeddingExecutionError as error:
            error.report['elapsed_seconds']=max(0.,time.monotonic()-start)
            raise
        except EncodingError as error:
            report['elapsed_seconds']=max(0.,time.monotonic()-start)
            raise_execution_error(error.code,report)
        except Exception:
            report['elapsed_seconds']=max(0.,time.monotonic()-start)
            raise_execution_error('embedding_encoding_failed',report)
