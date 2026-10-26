"""Source-aware contracts; no dependency on experiments, providers or UI."""
from .errors import ContractError, RetrievalError, SettingsError, TraceError
from .types import SourceSpan, Document, Chunk, QueryRequest, RetrievalResult
from .encoding_settings import EncodingSettings, load_encoding_settings
from .ingestion_settings import IngestionSettings
from .trace_context import TraceContext
from .trace_collector import TraceCollector

__all__ = ['ContractError','RetrievalError','SourceSpan','Document','Chunk',
           'QueryRequest','RetrievalResult','SettingsError','EncodingSettings','load_encoding_settings','IngestionSettings',
           'TraceError','TraceContext','TraceCollector']
