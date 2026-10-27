"""Full current dataset plus one build's actual work, with strict source replay."""
import copy
from dataclasses import dataclass
from ..core.types import Document,Chunk
from ..core.encoding_settings import EncodingSettings,digest
from ..core.ingestion_settings import IngestionSettings
from ..core.encoding_snapshot import EncodingSnapshot
from ..core.ingestion_encoding_summary import IngestionEncodingSummary
from ..core.errors import StorageError
from ..ingestion.document_relations import _registry
from ..ingestion import DocumentChunker,prepare_knowledge_base
from ..encoding.input_preparer import _prepare_document_encoding_inputs,plan_encoding_batches
from .artifact_bundle import _same


@dataclass(repr=False)
class IndexBundleV2:
    knowledge_base_id:str
    documents:list
    chunks:list
    relations:dict
    encoding_settings:EncodingSettings
    ingestion_settings:IngestionSettings
    encoding_snapshot:EncodingSnapshot
    encoding_summary:IngestionEncodingSummary
    preparation_diagnostics:list

    def __post_init__(self):
        try:
            if type(self.documents) is not list or type(self.chunks) is not list or \
                    any(type(d) is not Document for d in self.documents) or any(type(c) is not Chunk for c in self.chunks):raise ValueError()
            if type(self.encoding_settings) is not EncodingSettings or type(self.ingestion_settings) is not IngestionSettings or \
                    type(self.encoding_snapshot) is not EncodingSnapshot or type(self.encoding_summary) is not IngestionEncodingSummary:raise ValueError()
            cfg=EncodingSettings.from_dict(self.encoding_settings.to_dict())
            ingestion=IngestionSettings.from_dict(self.ingestion_settings.to_dict())
            snapshot=EncodingSnapshot.from_dict(self.encoding_snapshot.to_dict())
            summary=IngestionEncodingSummary.from_dict(self.encoding_summary.to_dict());summary.validate_snapshot(snapshot)
            kb=self.knowledge_base_id
            if kb!=snapshot.knowledge_base_id:raise StorageError('bundle_scope_mismatch')
            docs=[Document.from_dict(copy.deepcopy(d).to_dict()) for d in self.documents]
            chunks=[Chunk.from_dict(copy.deepcopy(c).to_dict()) for c in self.chunks]
            registry,_,library=_registry(docs)
            if docs and library!=kb:raise StorageError('bundle_scope_mismatch')
            if any(d.id!='doc-'+digest([kb,d.metadata['source_path']]) for d in docs):raise StorageError('bundle_source_mismatch')
            if (snapshot.model_space_id,snapshot.representation_id,snapshot.dimensions)!= \
                    (cfg.model_space_id,cfg.representation_id,cfg.embedding.expected_dimensions):raise StorageError('bundle_identity_mismatch')
            expected,relations,diagnostics=prepare_knowledge_base(list(registry.values()),DocumentChunker(ingestion),
                text_mode=cfg.representation.document_text_mode)
            by_id={c.id:c for c in chunks};wanted={c.id:c for c in expected};ids=[r.input.item_id for r in snapshot.records]
            if len(by_id)!=len(chunks) or set(by_id)!=set(wanted) or set(ids)!=set(by_id):raise StorageError('bundle_source_mismatch')
            if any(not _same(c.to_dict(),wanted[uid].to_dict()) for uid,c in by_id.items()) or \
                    not _same(self.relations,relations) or not _same(self.preparation_diagnostics,diagnostics):
                raise StorageError('bundle_source_mismatch')
            chunks=[by_id[uid] for uid in ids]
            inputs=_prepare_document_encoding_inputs(list(registry.values()),chunks,cfg,job_limits=False)
            if not _same([i.to_dict() for i in inputs],[r.input.to_dict() for r in snapshot.records]):
                raise StorageError('bundle_source_mismatch')
            encoded=[r.input for r,o in zip(snapshot.records,snapshot.origins,strict=True) if o['kind']=='encoded']
            batches=plan_encoding_batches(encoded,cfg)
            if summary.job_report is not None and [len(b) for b in batches]!=[b['input_count'] for b in summary.job_report.batches]:
                raise StorageError('bundle_identity_mismatch')
            self.documents=list(registry.values());self.chunks=chunks;self.relations=copy.deepcopy(relations)
            self.encoding_settings=cfg;self.ingestion_settings=ingestion
            self.encoding_snapshot=snapshot;self.encoding_summary=summary;self.preparation_diagnostics=copy.deepcopy(diagnostics)
        except StorageError:raise
        except Exception:raise StorageError('invalid_index_bundle') from None

    def to_dict(self):
        self.__post_init__()
        return dict(knowledge_base_id=self.knowledge_base_id,documents=[d.to_dict() for d in self.documents],
            chunks=[c.to_dict() for c in self.chunks],relations=copy.deepcopy(self.relations),
            encoding_settings=self.encoding_settings.to_dict(),ingestion_settings=self.ingestion_settings.to_dict(),
            encoding_snapshot=self.encoding_snapshot.to_dict(),encoding_summary=self.encoding_summary.to_dict(),
            preparation_diagnostics=copy.deepcopy(self.preparation_diagnostics))

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            raw=copy.deepcopy(data)
            raw['documents']=[Document.from_dict(d) for d in raw['documents']]
            raw['chunks']=[Chunk.from_dict(c) for c in raw['chunks']]
            raw['encoding_settings']=EncodingSettings.from_dict(raw['encoding_settings'])
            raw['ingestion_settings']=IngestionSettings.from_dict(raw['ingestion_settings'])
            raw['encoding_snapshot']=EncodingSnapshot.from_dict(raw['encoding_snapshot'])
            raw['encoding_summary']=IngestionEncodingSummary.from_dict(raw['encoding_summary'])
            return cls(**raw)
        except StorageError:raise
        except Exception:raise StorageError('invalid_index_bundle') from None


def prepare_index_bundle_v2(documents,chunks,relations,encoding_snapshot,encoding_summary,*,
                            knowledge_base_id,encoding_settings,ingestion_settings):
    try:
        _,_,diagnostics=prepare_knowledge_base(copy.deepcopy(documents),DocumentChunker(ingestion_settings),
            text_mode=encoding_settings.representation.document_text_mode)
        return IndexBundleV2(knowledge_base_id,documents,chunks,relations,encoding_settings,ingestion_settings,
            encoding_snapshot,encoding_summary,diagnostics)
    except StorageError:raise
    except Exception:raise StorageError('invalid_index_bundle') from None
