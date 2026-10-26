"""Prepare one query against one audited version; no retrieval or active mutation."""
import copy
import logging
from ..core.encoding_settings import EncodingSettings
from ..core.storage_settings import StorageSettings
from ..core.encoding_types import text_sha
from ..core.encoding_report import EncodingReport,_hash,ERROR_CODES
from ..core.query_encoding_types import QueryEncodingResult
from ..core.query_preparation import PreparedQuery
from ..core.errors import QueryJobError,StorageError,EncodingJobError,TraceError
from ..core.trace_context import TraceContext,validate_trace_report
from ..encoding.query_encoder import QueryEncoder
from ..storage import DocumentManager,ActiveVersion,ChromaSettings,BM25Settings
from ..storage.bundle_store import _json_bytes
from .query_processor import QueryProcessor

LOGGER=logging.getLogger(__name__)


class QueryPipeline:
    def __init__(self,document_manager,query_encoder):
        try:
            if type(document_manager) is not DocumentManager or type(query_encoder) is not QueryEncoder:raise ValueError()
            self.manager=document_manager;self.query_encoder=query_encoder
            self.storage_settings=StorageSettings.from_dict(document_manager.settings.to_dict())
            self.encoding_settings=EncodingSettings.from_dict(query_encoder.settings.to_dict())
            self.tokenizer_id=query_encoder.tokenizer_id
            self._components=(document_manager,query_encoder,query_encoder.dense_encoder,query_encoder.sparse_encoder)
            self.processor=QueryProcessor(self.encoding_settings,max_scope_documents=self.storage_settings.max_documents)
            self._validate()
        except Exception:
            LOGGER.error('query_failed stage=request code=query_invalid_request')
            raise QueryJobError('request','query_invalid_request') from None

    def _validate(self):
        manager,encoder,dense,sparse=self._components;cfg=self.encoding_settings.to_dict()
        if self.manager is not manager or self.query_encoder is not encoder or encoder.dense_encoder is not dense or \
                encoder.sparse_encoder is not sparse or type(encoder) is not QueryEncoder or not _hash(self.tokenizer_id):raise ValueError()
        if manager.settings.to_dict()!=self.storage_settings.to_dict() or encoder.settings.to_dict()!=cfg or \
                dense.settings.to_dict()!=cfg or sparse.encoding_settings.to_dict()!=cfg or \
                encoder.tokenizer_id!=self.tokenizer_id or sparse.tokenizer_id!=self.tokenizer_id:raise ValueError()
        if type(self.processor) is not QueryProcessor or self.processor.settings.to_dict()!=cfg or \
                self.processor.max_scope_documents!=self.storage_settings.max_documents:raise ValueError()
        manager.chroma_settings.to_dict();manager.bm25_settings.to_dict()

    def _record(self,context,stage,data):
        try:context.record_stage(stage,data)
        except Exception:raise TraceError('query_trace_failed') from None

    def _finish(self,context,stage):
        try:
            context.finish('success');report=context.to_dict();validate_trace_report(report)
            return report
        except Exception:raise TraceError('query_trace_failed') from None

    def _fail(self,error,stage,context,active,report,finished_trace):
        code=f'query_{stage}_failed'
        if type(error) is QueryJobError:code=error.code
        elif type(error) is StorageError:code=error.code
        elif type(error) is TraceError:code='query_trace_failed'
        elif type(error) is EncodingJobError and error.code in ERROR_CODES:
            code=error.code
            try:report=EncodingReport.from_dict(error.report)
            except Exception:
                LOGGER.error('query_report_failed stage=embedding code=invalid_encoding_report')
                code='query_embedding_failed';report=None
        trace=None
        mapped='invalid_request' if stage=='request' else 'snapshot_load_failed' if stage=='resources' else \
            'retrieval_failed' if stage in ('dense','sparse','fusion') else 'embedding_failed'
        if code=='query_invalid_scope':mapped='invalid_scope'
        elif code=='query_identity_mismatch':mapped='invalid_resources'
        if context is not None:
            try:
                if finished_trace is not None:
                    trace=copy.deepcopy(finished_trace)
                    trace.update(status='error',error=dict(stage=stage,code=mapped))
                else:
                    context.finish('error',error_stage=stage,error_code=mapped);trace=context.to_dict()
                validate_trace_report(trace)
            except Exception:
                LOGGER.error('query_trace_failed stage=%s code=query_trace_failed',stage);trace=None
        LOGGER.error('query_failed stage=%s code=%s',stage,code)
        raise QueryJobError(stage,code,active=active,encoding_report=report,trace_report=trace) from None

    def _scope(self,processed,base):
        known=set() if base is None else {d.id for d in base.documents}
        scope=processed.scope_document_ids;exclude=set(processed.exclude_document_ids)
        if not exclude<=known or scope is not None and not set(scope)<=known:
            raise QueryJobError('resources','query_invalid_scope')
        docs=sorted((known if scope is None else set(scope))-exclude)
        chunks=[] if base is None else sorted(c.id for c in base.chunks if c.source_ref in set(docs))
        return docs,chunks

    def _identity(self,active):
        cfg=self.encoding_settings;version=active.version
        if (cfg.model_space_id,cfg.representation_id,self.tokenizer_id,cfg.embedding.expected_dimensions)!= \
                (version.model_space_id,version.representation_id,version.tokenizer_id,version.dimensions):
            raise QueryJobError('resources','query_identity_mismatch')
        audited=self.manager._audit(version.bundle_id,
            ChromaSettings(version.chroma_collection_name,self.manager.chroma_settings.batch_size),
            BM25Settings(version.bm25_k1,version.bm25_b))
        if audited!=version:raise StorageError('catalog_identity_mismatch')

    def prepare(self,query,*,scope_document_ids=None,exclude_document_ids=None,expected_revision=None):
        stage='request';context=None;active=None;report=None;trace=None
        try:
            try:context=TraceContext()
            except Exception:raise TraceError('query_trace_failed') from None
            self._validate()
            processed=self.processor.process(query,scope_document_ids=scope_document_ids,
                exclude_document_ids=exclude_document_ids,expected_revision=expected_revision)
            self._record(context,stage,dict(status='validated'))
            stage='resources';selected,base=self.manager._document_bundle(processed.expected_revision)
            if selected is not None:
                if type(selected) is not ActiveVersion:raise StorageError('catalog_identity_mismatch')
                active=ActiveVersion.from_dict(selected.to_dict())
            elif base is not None:raise StorageError('catalog_identity_mismatch')
            docs,chunks=self._scope(processed,base)
            encoding=None
            if active is None:status='unactivated'
            else:
                self._identity(active)
                self._record(context,stage,dict(status='verified',corpus_id=active.version.source_fingerprint,
                                                index_id=active.version.version_id))
                status='empty_index' if active.version.document_count==0 or docs and not chunks else \
                    'empty_scope' if not docs else 'ready'
            if status=='ready':
                stage='embedding';value=self.query_encoder.encode(processed.query)
                if type(value) is not QueryEncodingResult:raise ValueError()
                report=EncodingReport.from_dict(value.report.to_dict())
                encoding=QueryEncodingResult.from_dict(value.to_dict());version=active.version
                if encoding.input.retrieval_text!=processed.query or encoding.input.query_sha256!=text_sha(processed.query) or \
                        (encoding.input.model_space_id,encoding.input.representation_id,encoding.tokenizer_id,encoding.dimensions)!= \
                        (version.model_space_id,version.representation_id,version.tokenizer_id,version.dimensions):
                    raise QueryJobError(stage,'query_identity_mismatch',active=active)
                batch=report.batches[0]
                self._record(context,stage,dict(adapter_calls=report.requests['dense_calls_started'],
                                                source_kind=batch['source_kind'],usage=batch['usage']))
            trace=self._finish(context,stage)
            result=PreparedQuery(status,active,text_sha(processed.query),docs,chunks,encoding,trace)
            try:_json_bytes(result.to_dict(),self.storage_settings.max_bundle_bytes,newline=False)
            except StorageError as error:
                if error.code=='bundle_limit_exceeded':raise QueryJobError(stage,'query_result_limit',active=active) from None
                raise
            return result
        except Exception as error:self._fail(error,stage,context,active,report,trace)
