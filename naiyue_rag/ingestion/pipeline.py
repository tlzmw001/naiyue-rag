"""Whole-library ingestion with pre-encoding reuse and guarded final activation."""
import copy
import logging
from ..core.storage_settings import StorageSettings,validate_storage_settings
from ..core.ingestion_settings import validate_ingestion_settings
from ..core.encoding_settings import EncodingSettings
from ..core.encoding_report import EncodingReport,ERROR_CODES,_hash
from ..core.encoded_types import EncodingResult
from ..core.ingestion_types import IngestionReceipt,RemovalReceipt
from ..core.ingestion_encoding_summary import IngestionEncodingSummary
from ..core.errors import IngestionJobError,StorageError,EncodingJobError
from ..encoding.batch_processor import BatchProcessor
from ..encoding.input_preparer import _prepare_document_encoding_inputs
from ..storage import (DocumentManager,VectorUpserter,BM25Indexer,
                       ChromaSettings,BM25Settings,ActivationReceipt)
from ..storage.artifact_bundle_v2 import prepare_index_bundle_v2
from ..storage.version_types import MAX_REVISION
from .markdown_loader import MarkdownLoader
from .document_chunker import DocumentChunker
from .knowledge_preparation import prepare_knowledge_base
from .file_integrity import plan_ingestion,profiles_match
from .document_relations import build_document_relations
from .encoding_reuse import compose_encoding_snapshot
from ..storage.document_views import _valid_document_id,project_detail

LOGGER=logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(self,storage_settings,ingestion_settings,batch_processor,chroma_settings,bm25_settings,*,
                 knowledge_base_root,project_root):
        try:
            if type(storage_settings) is not StorageSettings or type(batch_processor) is not BatchProcessor:raise ValueError()
            self.settings=StorageSettings.from_dict(storage_settings.to_dict())
            self.ingestion_settings=copy.deepcopy(ingestion_settings);self.batch_processor=batch_processor
            self.encoding_settings=EncodingSettings.from_dict(batch_processor.settings.to_dict())
            self.tokenizer_id=batch_processor.tokenizer_id
            if type(chroma_settings) is not ChromaSettings or type(bm25_settings) is not BM25Settings:raise ValueError()
            self.chroma_settings=ChromaSettings.from_dict(chroma_settings.to_dict())
            self.bm25_settings=BM25Settings.from_dict(bm25_settings.to_dict());self._validate()
            self._knowledge_base_root=knowledge_base_root;self._loader=None
            self.manager=DocumentManager(self.settings,self.chroma_settings,self.bm25_settings,project_root=project_root)
            self.chunker=DocumentChunker(self.ingestion_settings)
        except Exception:
            LOGGER.error('ingestion_failed stage=validate code=ingestion_invalid_request activation_status=not_attempted')
            raise IngestionJobError('validate','ingestion_invalid_request') from None

    @property
    def loader(self):
        # Removal consumes the saved bundle and must work while original sources are offline.
        if self._loader is None:
            self._loader=MarkdownLoader(self._knowledge_base_root,self.settings.knowledge_base_id,self.settings.max_file_bytes)
        return self._loader

    @loader.setter
    def loader(self,value):
        self._loader=value

    def _validate(self):
        validate_storage_settings(self.settings);validate_ingestion_settings(self.ingestion_settings)
        cfg=self.encoding_settings.to_dict();processor=self.batch_processor
        if type(processor) is not BatchProcessor or not _hash(self.tokenizer_id):raise ValueError()
        if processor.settings.to_dict()!=cfg or processor.dense_encoder.settings.to_dict()!=cfg or \
                processor.sparse_encoder.encoding_settings.to_dict()!=cfg or processor.tokenizer_id!=self.tokenizer_id or \
                processor.sparse_encoder.tokenizer_id!=self.tokenizer_id:raise ValueError()
        self.chroma_settings.to_dict();self.bm25_settings.to_dict()

    def _source_limits(self,documents):
        if len(documents)>self.settings.max_documents or any(d.metadata['size_bytes']>self.settings.max_file_bytes for d in documents):
            raise StorageError('bundle_limit_exceeded')

    def _inputs(self,documents,chunks,*,job_limits=True):
        if len(chunks)>self.settings.max_chunks:raise StorageError('bundle_limit_exceeded')
        return _prepare_document_encoding_inputs(documents,chunks,self.encoding_settings,job_limits=job_limits)

    def _fail(self,error,stage,*,report=None,candidate=None,outcome='not_attempted'):
        """Normalize only this boundary; shared callers let this exception propagate."""
        code=f'ingestion_{stage}_failed'
        if type(error) is StorageError:
            code=error.code
            if stage=='activate':outcome='unknown' if code=='catalog_commit_uncertain' else 'not_committed'
        elif type(error) is EncodingJobError and error.code in ERROR_CODES:
            code=error.code
            try:report=EncodingReport.from_dict(error.report)
            except Exception:
                LOGGER.error('ingestion_report_failed stage=encode code=invalid_encoding_report')
                report=None;code='ingestion_encode_failed'
        elif type(error) is IngestionJobError:code=error.code
        elif stage=='validate':code='ingestion_invalid_request'
        LOGGER.error('ingestion_failed stage=%s code=%s activation_status=%s',stage,code,outcome)
        raise IngestionJobError(stage,code,encoding_report=report,candidate_bundle_id=candidate,
            activation_status=outcome) from None

    def _audit_base(self,active):
        version=active.version
        audited=self.manager._audit(version.bundle_id,
            ChromaSettings(version.chroma_collection_name,self.chroma_settings.batch_size),
            BM25Settings(version.bm25_k1,version.bm25_b))
        if audited!=version:raise StorageError('catalog_identity_mismatch')

    def _activate_existing(self,target,*,expected_revision,report=None,candidate=None):
        try:
            activated=self.manager.activate(target,expected_revision=expected_revision)
            if type(activated) is not ActivationReceipt:raise ValueError()
            activated.to_dict()
            return activated
        except Exception as error:
            self._fail(error,'activate',report=report,candidate=candidate,outcome='unknown')

    def _build_and_activate(self,documents,*,expected_revision,base=None,base_bundle_id=None,encode_document_ids=None):
        stage='prepare';report=None;candidate=None
        try:
            encode={d.id for d in documents} if encode_document_ids is None else set(encode_document_ids)
            reuse={d.id for d in documents}-encode
            changed=[d for d in documents if d.id in encode]
            chunks,_,_=prepare_knowledge_base(changed,self.chunker,
                text_mode=self.encoding_settings.representation.document_text_mode)
            inputs=self._inputs(changed,chunks)
            if reuse:
                if base is None:raise ValueError()
                chunks.extend(copy.deepcopy(c) for c in base.chunks if c.source_ref in reuse)
            chunks.sort(key=lambda c:(c.source_ref,c.metadata['chunk_index']))
            if len(chunks)>self.settings.max_chunks:raise StorageError('bundle_limit_exceeded')
            _prepare_document_encoding_inputs(documents,chunks,self.encoding_settings,job_limits=False)
            relations=build_document_relations(documents)
            stage='encode';result=None
            if inputs:
                result=self.batch_processor.process(inputs)
                if type(result) is not EncodingResult:raise ValueError()
                report=EncodingReport.from_dict(result.report.to_dict())
                if report.status!='success' or report.paired_input_count!=len(inputs):raise ValueError()
            stage='bundle';snapshot,summary=compose_encoding_snapshot(documents,chunks,result,base=base,
                base_bundle_id=base_bundle_id,reuse_document_ids=reuse,knowledge_base_id=self.settings.knowledge_base_id,
                encoding_settings=self.encoding_settings,tokenizer_id=self.tokenizer_id)
            bundle=prepare_index_bundle_v2(documents,chunks,relations,snapshot,summary,
                knowledge_base_id=self.settings.knowledge_base_id,encoding_settings=self.encoding_settings,
                ingestion_settings=self.ingestion_settings)
            saved=self.manager.bundles.save(bundle)
            if not _hash(saved.bundle_id):raise ValueError()
            candidate=saved.bundle_id
            stage='vector';VectorUpserter(self.settings,self.chroma_settings,project_root=self.manager.project_root).build(candidate)
            stage='bm25';BM25Indexer(self.settings,self.bm25_settings).build(candidate)
        except Exception as error:self._fail(error,stage,report=report,candidate=candidate)
        activated=self._activate_existing(candidate,expected_revision=expected_revision,report=report,candidate=candidate)
        return activated,report,candidate,summary

    def run(self,*,expected_revision,force=False):
        stage='validate'
        try:
            if type(force) is not bool or type(expected_revision) is not int or not 0<=expected_revision<=MAX_REVISION:
                raise IngestionJobError(stage,'ingestion_invalid_request')
            self._validate()
            stage='select';active,base=self.manager._document_bundle(expected_revision)
            stage='load';incoming=self.loader.load_all()
            stage='plan';plan=plan_ingestion(active,base,incoming,knowledge_base_id=self.settings.knowledge_base_id,
                ingestion_settings=self.ingestion_settings,encoding_settings=self.encoding_settings,tokenizer_id=self.tokenizer_id,
                chroma_settings=self.chroma_settings,bm25_settings=self.bm25_settings,force=force)
            documents=plan.merged_documents;self._source_limits(documents)
            counts=[len(plan.added_ids),len(plan.updated_ids),len(plan.unchanged_ids),len(plan.retained_ids)]
            if sum(counts)!=len(documents):raise IngestionJobError(stage,'ingestion_plan_failed')
            encode=plan.encode_document_ids;reuse=plan.reuse_document_ids
            if type(encode) is not list or type(reuse) is not list or \
                    encode!=sorted(set(encode)) or reuse!=sorted(set(reuse)) or set(encode)&set(reuse) or \
                    set(encode+reuse)!={d.id for d in documents}:
                raise IngestionJobError(stage,'ingestion_plan_failed')
            if plan.reuse_active:
                stage='prepare';self._inputs(documents,base.chunks,job_limits=False)
            elif active is not None:
                stage='select';self._audit_base(active)
        except Exception as error:self._fail(error,stage)
        # These methods own their error stage/report; do not wrap them as select/plan.
        report=None;candidate=None;summary=None
        if plan.reuse_active:
            activated=self._activate_existing(active.version.bundle_id,expected_revision=expected_revision)
            summary=IngestionEncodingSummary(active.version.chunk_count,0,active.version.chunk_count,None)
        else:
            activated,report,candidate,summary=self._build_and_activate(documents,expected_revision=expected_revision,
                base=base,base_bundle_id=None if active is None else active.version.bundle_id,encode_document_ids=plan.encode_document_ids)
        try:return IngestionReceipt(activated.status,activated.active,*counts,report,encoding_summary=summary)
        except Exception as error:
            self._fail(error,'finalize',report=report,candidate=candidate,outcome=activated.status)

    def remove_document(self,document_id,*,expected_revision):
        stage='validate'
        try:
            if not _valid_document_id(document_id) or type(expected_revision) is not int or not 0<=expected_revision<=MAX_REVISION:
                raise IngestionJobError(stage,'ingestion_invalid_request')
            self._validate()
            stage='select';active,base=self.manager._document_bundle(expected_revision)
            stage='plan'
            if active is None:return RemovalReceipt('not_found',document_id,None,None,None,None)
            if not profiles_match(active,base,self.ingestion_settings,self.encoding_settings,self.tokenizer_id,
                                  self.chroma_settings,self.bm25_settings):
                raise IngestionJobError(stage,'ingestion_profile_mismatch')
            info=project_detail(active,base,document_id).document
            documents=[d for d in base.documents if d.id!=document_id]
            self._source_limits(documents)
            if info is None:
                stage='prepare';self._inputs(documents,base.chunks,job_limits=False)
            else:
                stage='select';self._audit_base(active)
        except Exception as error:self._fail(error,stage)
        report=None;candidate=None;summary=None
        if info is None:
            activated=self._activate_existing(active.version.bundle_id,expected_revision=expected_revision)
        else:
            activated,report,candidate,summary=self._build_and_activate(documents,expected_revision=expected_revision,
                base=base,base_bundle_id=active.version.bundle_id,encode_document_ids=[])
        try:
            if info is not None and activated.status!='activated':raise ValueError()
            return RemovalReceipt('not_found' if info is None else 'removed',document_id,
                                  active,activated.active,info,report,encoding_summary=summary)
        except Exception as error:
            self._fail(error,'finalize',report=report,candidate=candidate,outcome=activated.status)
