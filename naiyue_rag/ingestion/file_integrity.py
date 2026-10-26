"""Pure current-source planning; the active catalog remains the only success authority."""
import copy
from dataclasses import dataclass
import re
from ..core.encoding_settings import validate_encoding_settings,digest
from ..core.ingestion_settings import validate_ingestion_settings
from ..core.chroma_settings import ChromaSettings
from ..core.bm25_settings import BM25Settings
from ..core.types import Document
from ..core.errors import IngestionJobError
from ..storage.version_types import ActiveVersion
from ..storage.artifact_bundle import IndexBundle
from ..storage.chroma_backend import SDK_VERSION as CHROMA_VERSION
from ..storage.bm25_backend import SDK_VERSION as BM25_VERSION
from .document_relations import _registry


@dataclass(frozen=True,repr=False)
class _IngestionPlan:
    merged_documents:list
    added_ids:list
    updated_ids:list
    unchanged_ids:list
    retained_ids:list
    reuse_active:bool


def plan_ingestion(active,base_bundle,incoming,*,knowledge_base_id,ingestion_settings,encoding_settings,
                   tokenizer_id,chroma_settings,bm25_settings,force):
    try:
        validate_ingestion_settings(ingestion_settings);validate_encoding_settings(encoding_settings)
        if type(force) is not bool or type(knowledge_base_id) is not str or not knowledge_base_id.strip():raise ValueError()
        if type(tokenizer_id) is not str or re.fullmatch('[0-9a-f]{64}',tokenizer_id) is None:raise ValueError()
        if type(chroma_settings) is not ChromaSettings or type(bm25_settings) is not BM25Settings:raise ValueError()
        chroma_settings.to_dict();bm25_settings.to_dict()
        if (active is None)!=(base_bundle is None):raise ValueError()
        if active is not None:
            if type(active) is not ActiveVersion or type(base_bundle) is not IndexBundle:raise ValueError()
            active.to_dict()
            if active.version.knowledge_base_id!=knowledge_base_id or base_bundle.knowledge_base_id!=knowledge_base_id:raise ValueError()
        def registry(documents):
            if type(documents) is not list or any(type(d) is not Document for d in documents):raise ValueError()
            copied=[Document.from_dict(copy.deepcopy(d).to_dict()) for d in documents]
            rows,_,kb=_registry(copied)
            if rows and kb!=knowledge_base_id:raise ValueError()
            for uid,doc in rows.items():
                if uid!='doc-'+digest([knowledge_base_id,doc.metadata['source_path']]):raise ValueError()
            return rows
        old=registry([] if base_bundle is None else base_bundle.documents);new=registry(incoming)
        added=sorted(set(new)-set(old));retained=sorted(set(old)-set(new))
        updated=[];unchanged=[]
        for uid in sorted(set(new)&set(old)):
            (unchanged if new[uid].metadata['source_sha256']==old[uid].metadata['source_sha256'] else updated).append(uid)
        merged=old|new
        reusable=False
        if active is not None and not force and not added and not updated:
            reusable=profiles_match(active,base_bundle,ingestion_settings,encoding_settings,tokenizer_id,
                                    chroma_settings,bm25_settings)
        return _IngestionPlan([merged[uid] for uid in sorted(merged)],added,updated,unchanged,retained,reusable)
    except Exception:raise IngestionJobError('plan','ingestion_plan_failed') from None


def profiles_match(active,base,ingestion_settings,encoding_settings,tokenizer_id,chroma_settings,bm25_settings):
    """Compare validated semantic identities, shared by ingest reuse and removal."""
    version=active.version;result=base.encoding_result
    return (ingestion_settings==base.ingestion_settings and
        encoding_settings.model_space_id==result.model_space_id and
        encoding_settings.representation_id==result.representation_id and tokenizer_id==result.tokenizer_id and
        chroma_settings.collection_name==version.chroma_collection_name and version.chroma_sdk_version==CHROMA_VERSION and
        bm25_settings.k1==version.bm25_k1 and bm25_settings.b==version.bm25_b and version.bm25_sdk_version==BM25_VERSION)
