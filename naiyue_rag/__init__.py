"""Formal Markdown preparation and encoding contracts; no experimental startup."""
from .ingestion import MarkdownLoader, DocumentChunker, prepare_document, prepare_knowledge_base
from .core.encoding_settings import EncodingSettings, load_encoding_settings
from .core.ingestion_settings import IngestionSettings
from .encoding import prepare_document_encoding_inputs, prepare_query_encoding_input, plan_encoding_batches, normalize_embedding_response
from .encoding import OpenAICompatibleEmbedding, DenseEncoder
from .encoding import SparseEncoder, SparseRecord
from .encoding import BatchProcessor, EncodedRecord, EncodingResult, EncodingReport, EncodingJobError
from .encoding import QueryEncoder, QueryEncodingResult
from .encoding.bootstrap import load_embedding_provider
from .core.sparse_encoding_settings import SparseEncodingSettings, load_sparse_encoding_settings

__all__ = ['MarkdownLoader','DocumentChunker','prepare_document','prepare_knowledge_base',
           'IngestionSettings','EncodingSettings','load_encoding_settings',
           'prepare_document_encoding_inputs','prepare_query_encoding_input',
           'plan_encoding_batches','normalize_embedding_response','OpenAICompatibleEmbedding','DenseEncoder',
           'SparseEncoder','SparseRecord','SparseEncodingSettings','load_sparse_encoding_settings',
           'BatchProcessor','EncodedRecord','EncodingResult','EncodingReport','EncodingJobError','QueryEncoder','QueryEncodingResult','load_embedding_provider']

from .core.ingestion_types import IngestionReceipt,RemovalReceipt
from .ingestion.pipeline import IngestionPipeline
__all__+=['IngestionReceipt','RemovalReceipt','IngestionPipeline']

from .core.query_preparation import PreparedQuery
from .query import QueryPipeline
__all__+=['PreparedQuery','QueryPipeline']

from .query.dense_retriever import DenseRetriever
from .core.dense_results import DenseHit,DenseResult
__all__+=['DenseRetriever','DenseHit','DenseResult']

from .query.sparse_retriever import SparseRetriever
from .core.sparse_query_settings import SparseQuerySettings,load_sparse_query_settings
from .core.sparse_results import SparseHit,SparseResult
__all__+=['SparseRetriever','SparseQuerySettings','load_sparse_query_settings','SparseHit','SparseResult']

from .query.hybrid_search import HybridSearch
from .query.fusion import RRFFusion
from .core.hybrid_settings import HybridSettings,load_hybrid_settings
from .core.hybrid_results import FusedHit,HybridResult
__all__+=['HybridSearch','RRFFusion','HybridSettings','load_hybrid_settings','FusedHit','HybridResult']

from .query.knowledge_reader import KnowledgeReader
__all__+=['KnowledgeReader']

from .core.rerank_settings import RerankSettings,LLMRerankSettings,load_rerank_settings,load_llm_rerank_settings
from .core.rerank_results import RerankResult
from .reranking.core import CoreReranker
from .reranking.report import RerankError
__all__+=['RerankSettings','LLMRerankSettings','load_rerank_settings','load_llm_rerank_settings','RerankResult','CoreReranker','RerankError']
from .reranking.llm import LLMReranker
from .reranking.bootstrap import load_llm_reranker
__all__+=['LLMReranker','load_llm_reranker']
from .core.evidence_settings import EvidenceSettings,load_evidence_settings
from .response.builder import ResponseBuilder,EvidenceError
from .query.retrieval_pipeline import RetrievalPipeline
__all__+=['EvidenceSettings','load_evidence_settings','ResponseBuilder','EvidenceError','RetrievalPipeline']

from .core.encoding_snapshot import StoredEncodedRecord,EncodingSnapshot
from .core.ingestion_encoding_summary import IngestionEncodingSummary
from .storage.artifact_bundle_v2 import IndexBundleV2,prepare_index_bundle_v2
__all__+=['StoredEncodedRecord','EncodingSnapshot','IngestionEncodingSummary','IndexBundleV2','prepare_index_bundle_v2']

from .core.application_settings import ApplicationSettings,load_application_settings
__all__+=['ApplicationSettings','load_application_settings']

from .core.model_registry import ModelRegistry,load_model_registry
from .runtime import ApplicationRuntime
__all__+=['ModelRegistry','load_model_registry','ApplicationRuntime']
