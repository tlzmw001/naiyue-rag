"""Independent formal regression selection; retained experiment tests run locally."""
from pathlib import Path
import subprocess
import sys

# Explicit formal consumer suite; historical snapshot/experiment suites remain local.
FORMAL="""
test_application_runtime.py
test_application_settings.py
test_batch_processor.py
test_batch_wiring.py
test_bm25_integrity.py
test_bm25_native.py
test_bm25_store.py
test_chinese_chunking.py
test_chroma_index.py
test_chroma_native.py
test_chunk_preparation.py
test_chunking_policy.py
test_chunking_wiring.py
test_configuration_bootstrap.py
test_core_app.py
test_credentials.py
test_cross_encoder_app.py
test_cross_encoder_reranker.py
test_dense_encoder.py
test_dense_retrieval.py
test_dense_retrieval_wiring.py
test_distribution.py
test_release_workflow.py
test_document_chunker.py
test_document_management.py
test_document_management_wiring.py
test_document_manager.py
test_document_manager_wiring.py
test_document_relations.py
test_document_removal.py
test_document_removal_wiring.py
test_document_reuse_plan.py
test_document_views.py
test_embedding_bootstrap.py
test_encoded_types.py
test_encoding_check.py
test_encoding_check_wiring.py
test_encoding_inputs.py
test_encoding_report.py
test_encoding_settings.py
test_encoding_snapshot.py
test_encoding_validation.py
test_evidence_response.py
test_file_integrity.py
test_hybrid_search.py
test_hybrid_search_wiring.py
test_incremental_acceptance.py
test_incremental_ingestion.py
test_index_versions.py
test_ingestion_pipeline.py
test_ingestion_pipeline_wiring.py
test_ingestion_types.py
test_knowledge_preparation_wiring.py
test_knowledge_reader.py
test_knowledge_reader_wiring.py
test_llm_reranker.py
test_local_embedding_audit.py
test_local_service.py
test_markdown_loader.py
test_markdown_loader_wiring.py
test_markdown_structure.py
test_model_registry.py
test_nyr_cli.py
test_openai_embedding.py
test_preparation_wiring.py
test_prepare_local_model.py
test_query_encoding.py
test_query_encoding_wiring.py
test_query_normalization.py
test_query_preparation.py
test_query_preparation_wiring.py
test_query_processor.py
test_reranking.py
test_retrieval_smoke.py
test_sparse_encoder.py
test_sparse_encoding_settings.py
test_sparse_retrieval.py
test_sparse_retrieval_wiring.py
test_sparse_wiring.py
test_storage_bundle.py
test_storage_bundle_v2.py
test_storage_bundle_wiring.py
""".split()


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    assert len(FORMAL)==len(set(FORMAL)) and all((root/'tests'/name).is_file() for name in FORMAL)
    selected=['tests/'+name for name in FORMAL]
    raise SystemExit(subprocess.call([sys.executable,'-m','pytest','-q','--tb=short',*selected],cwd=root))
