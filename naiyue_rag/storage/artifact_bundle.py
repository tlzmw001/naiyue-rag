"""Lossless M1/M2/M3 bundle; recomputation verifies sources, not business truth."""
import copy
from dataclasses import dataclass
import hashlib
import json
from ..core.types import Document,Chunk
from ..core.encoded_types import EncodingResult
from ..core.encoding_settings import EncodingSettings
from ..core.ingestion_settings import IngestionSettings,validate_ingestion_settings
from ..core.errors import StorageError
from ..ingestion.document_relations import _registry
from ..ingestion import DocumentChunker,prepare_knowledge_base
from ..encoding.input_preparer import prepare_document_encoding_inputs


def _same(left,right):
    # Canonical JSON distinguishes bool from int, unlike Python container equality.
    return json.dumps(left,ensure_ascii=False,sort_keys=True,allow_nan=False)==json.dumps(right,ensure_ascii=False,sort_keys=True,allow_nan=False)


@dataclass(repr=False)
class IndexBundle:
    knowledge_base_id:str
    documents:list
    chunks:list
    relations:dict
    encoding_settings:EncodingSettings
    ingestion_settings:IngestionSettings
    encoding_result:EncodingResult
    preparation_diagnostics:list

    def __post_init__(self):
        try:
            kb=self.knowledge_base_id
            if type(kb) is not str or not kb.strip() or any(ord(c)<32 for c in kb):raise StorageError('bundle_scope_mismatch')
            kb.encode('utf-8')
            if type(self.documents) is not list or type(self.chunks) is not list:raise StorageError('invalid_index_bundle')
            if any(type(d) is not Document for d in self.documents) or any(type(c) is not Chunk for c in self.chunks):raise StorageError('invalid_index_bundle')
            if type(self.encoding_settings) is not EncodingSettings or type(self.ingestion_settings) is not IngestionSettings or type(self.encoding_result) is not EncodingResult:
                raise StorageError('invalid_index_bundle')
            cfg=EncodingSettings.from_dict(self.encoding_settings.to_dict());ingestion=copy.deepcopy(self.ingestion_settings)
            validate_ingestion_settings(ingestion)
            docs=[Document.from_dict(copy.deepcopy(d).to_dict()) for d in self.documents]
            chunks=[Chunk.from_dict(copy.deepcopy(c).to_dict()) for c in self.chunks]
            result=EncodingResult.from_dict(copy.deepcopy(self.encoding_result).to_dict())
            registry,_,library=_registry(docs)
            if docs and library!=kb or result.records and result.knowledge_base_id!=kb:raise StorageError('bundle_scope_mismatch')
            for doc in docs:
                identity=json.dumps([kb,doc.metadata['source_path']],ensure_ascii=False,separators=(',',':')).encode('utf-8')
                if doc.id!='doc-'+hashlib.sha256(identity).hexdigest():raise StorageError('bundle_source_mismatch')
            if result.model_space_id!=cfg.model_space_id or result.representation_id!=cfg.representation_id or result.dimensions!=cfg.embedding.expected_dimensions:
                raise StorageError('bundle_identity_mismatch')
            expected,relations,diagnostics=prepare_knowledge_base(list(registry.values()),DocumentChunker(ingestion),text_mode=cfg.representation.document_text_mode)
            by_id={c.id:c for c in chunks};expected_by_id={c.id:c for c in expected}
            ids=[r.input.item_id for r in result.records]
            if len(by_id)!=len(chunks) or set(by_id)!=set(expected_by_id) or set(ids)!=set(by_id):raise StorageError('bundle_source_mismatch')
            for uid,chunk in by_id.items():
                if not _same(chunk.to_dict(),expected_by_id[uid].to_dict()):raise StorageError('bundle_source_mismatch')
            if not _same(self.relations,relations) or not _same(self.preparation_diagnostics,diagnostics):raise StorageError('bundle_source_mismatch')
            chunks=[by_id[uid] for uid in ids]
            inputs=prepare_document_encoding_inputs(list(registry.values()),chunks,cfg)
            if not _same([i.to_dict() for i in inputs],[r.input.to_dict() for r in result.records]):raise StorageError('bundle_source_mismatch')
            # Existing result validation also binds sparse IDs/hashes, vector dimensions, tokenizer and report ranges.
            self.documents=list(registry.values());self.chunks=chunks;self.encoding_result=result
            self.encoding_settings=cfg;self.ingestion_settings=ingestion
            self.relations=copy.deepcopy(relations);self.preparation_diagnostics=copy.deepcopy(diagnostics)
        except StorageError:raise
        except Exception:raise StorageError('invalid_index_bundle') from None

    def to_dict(self):
        self.__post_init__()
        return dict(knowledge_base_id=self.knowledge_base_id,documents=[d.to_dict() for d in self.documents],
            chunks=[c.to_dict() for c in self.chunks],relations=copy.deepcopy(self.relations),
            encoding_settings=self.encoding_settings.to_dict(),ingestion_settings=self.ingestion_settings.to_dict(),
            encoding_result=self.encoding_result.to_dict(),preparation_diagnostics=copy.deepcopy(self.preparation_diagnostics))

    @classmethod
    def from_dict(cls,data):
        try:
            if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):raise ValueError()
            raw=copy.deepcopy(data)
            raw['documents']=[Document.from_dict(d) for d in raw['documents']]
            raw['chunks']=[Chunk.from_dict(c) for c in raw['chunks']]
            raw['encoding_settings']=EncodingSettings.from_dict(raw['encoding_settings'])
            raw['ingestion_settings']=IngestionSettings.from_dict(raw['ingestion_settings'])
            raw['encoding_result']=EncodingResult.from_dict(raw['encoding_result'])
            return cls(**raw)
        except StorageError:raise
        except Exception:raise StorageError('invalid_index_bundle') from None


def prepare_index_bundle(documents,chunks,relations,encoding_result,*,knowledge_base_id,encoding_settings,ingestion_settings):
    try:
        # Diagnostics are generated by the existing M2 mechanism, not fabricated by this storage layer.
        _,_,diagnostics=prepare_knowledge_base(copy.deepcopy(documents),DocumentChunker(ingestion_settings),
            text_mode=encoding_settings.representation.document_text_mode)
        return IndexBundle(knowledge_base_id,documents,chunks,relations,encoding_settings,ingestion_settings,encoding_result,diagnostics)
    except StorageError:raise
    except Exception:raise StorageError('invalid_index_bundle') from None
