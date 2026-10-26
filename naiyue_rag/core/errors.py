"""Stable error identity; messages contain codes, never source payloads."""


class RetrievalError(Exception):
    def __init__(self, stage, code):
        self.stage, self.code = stage, code
        super().__init__(f'{stage}: {code}')


class ContractError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class SettingsError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class TraceError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class LoadError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ChunkingError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class PreparationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class RelationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class EncodingError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class EmbeddingExecutionError(EncodingError):
    """A fixed error code plus observations; never retains provider exceptions."""
    def __init__(self, code, report):
        import copy
        super().__init__(code)
        self.report = copy.deepcopy(report)


class EncodingJobError(EncodingError):
    """Whole-job failure; only a validated report, never partial encoded records."""
    def __init__(self, code, report):
        from .encoding_report import EncodingReport,safe_code
        super().__init__(safe_code(code))
        self.report = EncodingReport.from_dict(report).to_dict()


class StorageError(ValueError):
    """Closed local storage error identities; no source payload or raw IO exception."""
    CODES=frozenset('''invalid_index_bundle bundle_scope_mismatch bundle_identity_mismatch
bundle_source_mismatch bundle_limit_exceeded invalid_bundle_id bundle_path_invalid bundle_not_found
bundle_incomplete bundle_integrity_failed bundle_read_failed bundle_write_failed
bundle_publish_failed bundle_publish_uncertain'''.split())

    CODES=CODES|frozenset('''chroma_runtime_mismatch chroma_environment_invalid chroma_open_failed
chroma_read_failed chroma_write_failed chroma_close_failed chroma_index_not_found chroma_index_incomplete
chroma_identity_mismatch chroma_integrity_failed chroma_invalid_request chroma_batch_limit
chroma_publish_failed chroma_publish_uncertain chroma_path_invalid'''.split())

    CODES=CODES|frozenset('''bm25_runtime_mismatch bm25_invalid_request bm25_index_not_found
bm25_index_incomplete bm25_identity_mismatch bm25_integrity_failed bm25_path_invalid bm25_limit_exceeded
bm25_read_failed bm25_write_failed bm25_publish_failed bm25_publish_uncertain bm25_query_failed'''.split())

    CODES=CODES|frozenset('''catalog_invalid_request catalog_path_invalid catalog_limit_exceeded
catalog_schema_unsupported catalog_integrity_failed catalog_identity_mismatch catalog_read_failed
catalog_write_failed catalog_busy catalog_revision_conflict catalog_commit_uncertain catalog_cleanup_failed'''.split())

    CODES=CODES|frozenset('''document_invalid_request document_integrity_failed document_limit_exceeded'''.split())

    def __init__(self,code):
        import logging
        self.code=code if type(code) is str and code in self.CODES else 'invalid_index_bundle'
        logging.getLogger(__name__).error('storage_failed code=%s',self.code)
        super().__init__(self.code)


class IngestionJobError(ValueError):
    """Whole-ingestion failure; observations never contain partial indexed records."""
    STAGES=frozenset('validate select load plan prepare encode bundle vector bm25 activate finalize'.split())
    OUTCOMES=frozenset('not_attempted not_committed activated unchanged unknown'.split())
    CODES=frozenset({'ingestion_invalid_request','ingestion_failed','ingestion_profile_mismatch'}|
                    {f'ingestion_{stage}_failed' for stage in STAGES})

    def __init__(self,stage,code,*,encoding_report=None,candidate_bundle_id=None,activation_status='not_attempted'):
        from .encoding_report import EncodingReport,ERROR_CODES,_hash
        try:
            if type(stage) is not str or stage not in self.STAGES or type(code) is not str or \
                    code not in self.CODES|StorageError.CODES|ERROR_CODES:raise ValueError()
            if type(activation_status) is not str or activation_status not in self.OUTCOMES:raise ValueError()
            if stage not in ('activate','finalize') and activation_status!='not_attempted' or \
                    stage=='activate' and activation_status not in ('not_committed','unknown') or \
                    stage=='finalize' and activation_status not in ('activated','unchanged'):raise ValueError()
            if candidate_bundle_id is not None and not _hash(candidate_bundle_id):raise ValueError()
            if encoding_report is not None:
                if type(encoding_report) is not EncodingReport:raise ValueError()
                encoding_report=EncodingReport.from_dict(encoding_report.to_dict())
        except Exception:raise ValueError('ingestion_invalid_request') from None
        self.stage=stage;self.code=code;self.encoding_report=encoding_report
        self.candidate_bundle_id=candidate_bundle_id;self.activation_status=activation_status
        super().__init__(code)

    def to_dict(self):
        self.__init__(self.stage,self.code,encoding_report=self.encoding_report,
            candidate_bundle_id=self.candidate_bundle_id,activation_status=self.activation_status)
        return dict(stage=self.stage,code=self.code,encoding_report=None if self.encoding_report is None else
                    self.encoding_report.to_dict(),candidate_bundle_id=self.candidate_bundle_id,
                    activation_status=self.activation_status)

    @classmethod
    def from_dict(cls,data):
        from .encoding_report import EncodingReport
        try:
            if type(data) is not dict or set(data)!={'stage','code','encoding_report','candidate_bundle_id','activation_status'}:
                raise ValueError()
            raw=dict(data)
            if raw['encoding_report'] is not None:raw['encoding_report']=EncodingReport.from_dict(raw['encoding_report'])
            return cls(**raw)
        except Exception:raise ValueError('ingestion_invalid_request') from None


class QueryJobError(ValueError):
    """Closed query-job failure with known version, usage and source-free trace."""
    STAGES=frozenset('request resources embedding dense sparse fusion'.split())
    CODES=frozenset('''query_invalid_request query_invalid_scope query_identity_mismatch query_result_limit
query_prepare_failed query_request_failed query_resources_failed query_embedding_failed query_trace_failed query_dense_failed query_sparse_failed query_fusion_failed'''.split())

    def __init__(self,stage,code,*,active=None,encoding_report=None,trace_report=None):
        import copy
        from .encoding_report import EncodingReport,ERROR_CODES
        from .trace_context import validate_trace_report
        from ..storage.version_types import ActiveVersion
        try:
            if type(stage) is not str or stage not in self.STAGES or type(code) is not str or \
                    code not in self.CODES|StorageError.CODES|ERROR_CODES:raise ValueError()
            if active is not None:
                if type(active) is not ActiveVersion:raise ValueError()
                active=ActiveVersion.from_dict(active.to_dict())
            if encoding_report is not None:
                if type(encoding_report) is not EncodingReport:raise ValueError()
                encoding_report=EncodingReport.from_dict(encoding_report.to_dict())
            if stage=='request' and (active is not None or encoding_report is not None) or \
                    stage=='resources' and encoding_report is not None or stage=='embedding' and active is None:
                raise ValueError()
            if trace_report is not None:
                validate_trace_report(trace_report)
                if trace_report['status']!='error' or trace_report['error']['stage']!=stage:raise ValueError()
                trace_report=copy.deepcopy(trace_report)
        except Exception:raise ValueError('query_invalid_request') from None
        self.stage=stage;self.code=code;self.active=active
        self.encoding_report=encoding_report;self.trace_report=trace_report
        super().__init__(code)

    def to_dict(self):
        import copy
        self.__init__(self.stage,self.code,active=self.active,encoding_report=self.encoding_report,trace_report=self.trace_report)
        return dict(stage=self.stage,code=self.code,active=None if self.active is None else self.active.to_dict(),
            encoding_report=None if self.encoding_report is None else self.encoding_report.to_dict(),trace_report=copy.deepcopy(self.trace_report))

    @classmethod
    def from_dict(cls,data):
        from .encoding_report import EncodingReport
        from ..storage.version_types import ActiveVersion
        try:
            if type(data) is not dict or set(data)!={'stage','code','active','encoding_report','trace_report'}:raise ValueError()
            raw=dict(data)
            if raw['active'] is not None:raw['active']=ActiveVersion.from_dict(raw['active'])
            if raw['encoding_report'] is not None:raw['encoding_report']=EncodingReport.from_dict(raw['encoding_report'])
            return cls(**raw)
        except Exception:raise ValueError('query_invalid_request') from None
