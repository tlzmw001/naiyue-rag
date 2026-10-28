"""Local CLI composition; core modules remain usable without this entry point."""
import argparse
from contextlib import ExitStack
import json
import logging
from pathlib import Path
import sys
from .core.errors import SettingsError,QueryJobError,IngestionJobError,StorageError,EncodingError
from .core.yaml_config import read_yaml_mapping
from .core.storage_settings import load_storage_settings
from .core.chroma_settings import load_chroma_settings
from .core.bm25_settings import load_bm25_settings
from .core.credentials import resolve_api_key
from .core.encoding_settings import load_encoding_settings
from .core.sparse_encoding_settings import load_sparse_encoding_settings
from .core.hybrid_settings import load_hybrid_settings
from .core.rerank_settings import load_rerank_settings
from .core.evidence_settings import load_evidence_settings
from .core.ingestion_settings import IngestionSettings,validate_ingestion_settings
from .encoding import OpenAICompatibleEmbedding,DenseEncoder,SparseEncoder,QueryEncoder,BatchProcessor
from .ingestion.pipeline import IngestionPipeline
from .storage import DocumentManager
from .query.hybrid_search import HybridSearch
from .query.knowledge_reader import KnowledgeReader
from .query.retrieval_pipeline import RetrievalPipeline
from .reranking.core import CoreReranker
from .reranking.bootstrap import load_llm_reranker
from .reranking.report import RerankError
from .response.builder import ResponseBuilder,EvidenceError


PATHS=('storage','encoding','sparse','chroma','bm25','hybrid','rerank','evidence')


def load_app_settings(path):
    source,raw=read_yaml_mapping(path)
    fields=set(PATHS)|{'project_root','knowledge_base_root','key_env','chunk_size','chunk_overlap','rerank_backend','model_settings'}
    try:
        if type(raw) is not dict or set(raw)!=fields:raise ValueError()
        cfg=dict(raw)
        for key in PATHS+('project_root','knowledge_base_root'):
            value=cfg[key]
            if type(value) is not str or not value.strip() or any(ord(c)<32 for c in value):raise ValueError()
            target=Path(value)
            if '..' in target.parts:raise ValueError()
            cfg[key]=str(target if target.is_absolute() else source.parent/target)
        if type(cfg['key_env']) is not str or not cfg['key_env'].isidentifier():raise ValueError()
        if type(cfg['rerank_backend']) is not str or cfg['rerank_backend'] not in ('none','llm','cross_encoder'):raise ValueError()
        model=cfg['model_settings']
        if cfg['rerank_backend']=='none':
            if model is not None:raise ValueError()
        else:
            if type(model) is not str or not model.strip() or '..' in Path(model).parts:raise ValueError()
            cfg['model_settings']=str(Path(model) if Path(model).is_absolute() else source.parent/model)
        validate_ingestion_settings(IngestionSettings(cfg['chunk_size'],cfg['chunk_overlap']))
        return cfg
    except Exception:raise SettingsError('invalid_app_settings') from None


def _manager(cfg):
    return DocumentManager(load_storage_settings(cfg['storage']),load_chroma_settings(cfg['chroma']),
        load_bm25_settings(cfg['bm25']),project_root=cfg['project_root'])


def execute(cfg,args):
    manager=_manager(cfg)
    if args.action=='documents':return manager.list_documents(expected_revision=args.expected_revision).to_dict()
    with ExitStack() as owned:
        encoding=load_encoding_settings(cfg['encoding']);sparse_cfg=load_sparse_encoding_settings(cfg['sparse'])
        key=resolve_api_key(cfg['project_root'],cfg['key_env'])
        provider=owned.enter_context(OpenAICompatibleEmbedding(encoding,api_key=key))
        dense=DenseEncoder(encoding,provider);sparse=SparseEncoder(encoding,sparse_cfg)
        if args.action=='ingest':
            pipeline=IngestionPipeline(manager.settings,IngestionSettings(cfg['chunk_size'],cfg['chunk_overlap']),
                BatchProcessor(encoding,dense,sparse),manager.chroma_settings,manager.bm25_settings,
                knowledge_base_root=cfg['knowledge_base_root'],project_root=cfg['project_root'])
            return pipeline.run(expected_revision=args.expected_revision).to_dict()
        rerank=load_rerank_settings(cfg['rerank']);backend=None
        if rerank.enabled!=(cfg['rerank_backend']!='none'):raise SettingsError('invalid_app_settings')
        if cfg['rerank_backend']=='llm':
            backend=owned.enter_context(load_llm_reranker(cfg['model_settings'],project_root=cfg['project_root'],key_env=cfg['key_env']))
        elif cfg['rerank_backend']=='cross_encoder':
            from .reranking.cross_encoder import load_cross_encoder
            backend=load_cross_encoder(cfg['model_settings'])
        pipeline=RetrievalPipeline(HybridSearch(manager,QueryEncoder(encoding,dense,sparse),load_hybrid_settings(cfg['hybrid'])),
            CoreReranker(rerank,backend),ResponseBuilder(KnowledgeReader(manager.settings),load_evidence_settings(cfg['evidence'])))
        query=args.query
        if query is None:
            query=sys.stdin.read(manager.settings.max_file_bytes+1)
            if len(query)>manager.settings.max_file_bytes:raise SettingsError('invalid_app_input')
        return pipeline.query(query,scope_document_ids=args.scope,exclude_document_ids=args.exclude,
            expected_revision=args.expected_revision)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Standalone Markdown RAG: ingest, query and inspect documents.')
    parser.add_argument('--config',required=True)
    commands=parser.add_subparsers(dest='action',required=True)
    for name in ('ingest','query','documents'):
        sub=commands.add_parser(name);sub.add_argument('--expected-revision',type=int,required=name=='ingest')
        if name=='query':
            sub.add_argument('--query');sub.add_argument('--scope',nargs='*');sub.add_argument('--exclude',nargs='*')
    args=parser.parse_args(argv)
    try:
        result=execute(load_app_settings(args.config),args)
        print(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False));return 0
    except (QueryJobError,IngestionJobError,RerankError,EvidenceError) as error:
        print(json.dumps(dict(error=error.to_dict()),ensure_ascii=False,separators=(',',':'),allow_nan=False));return 2
    except (SettingsError,StorageError,EncodingError) as error:
        logging.getLogger(__name__).error('app_failed code=%s',error.code)
        print(json.dumps(dict(error=dict(code=error.code))));return 2
    except Exception:
        logging.getLogger(__name__).error('app_failed code=app_failed')
        print(json.dumps(dict(error=dict(code='app_failed'))));return 2


if __name__=='__main__':raise SystemExit(main())
