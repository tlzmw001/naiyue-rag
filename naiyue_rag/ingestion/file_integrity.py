"""Pure current-source planning; the active catalog remains the only success authority."""
from ..storage.bundle_encoding import bundle_encoding
import copy
from dataclasses import dataclass
import re
from ..core.encoding_settings import validate_encoding_settings,digest
from ..core.ingestion_settings import validate_ingestion_settings
from ..core.chunking_policy import chunking_profile
from ..core.chroma_settings import ChromaSettings
from ..core.bm25_settings import BM25Settings
from ..core.types import Document
from ..core.errors import IngestionJobError
from ..storage.version_types import ActiveVersion
from ..storage.artifact_bundle import IndexBundle
from ..storage.artifact_bundle_v2 import IndexBundleV2
from ..storage.chroma_backend import SDK_VERSION as CHROMA_VERSION
from ..storage.bm25_backend import SDK_VERSION as BM25_VERSION
from .document_relations import _registry
from .chunk_preparation import POLICY_ID


@dataclass(frozen=True,repr=False)
class _IngestionPlan:
    merged_documents:list
    added_ids:list
    updated_ids:list
    unchanged_ids:list
    retained_ids:list
    reuse_active:bool
    encode_document_ids:list
    reuse_document_ids:list
    encoding_profile_matches:bool
    index_profile_matches:bool


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
            if type(active) is not ActiveVersion or type(base_bundle) not in (IndexBundle,IndexBundleV2):raise ValueError()
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
        encoding_same=active is not None and encoding_profiles_match(base_bundle,ingestion_settings,encoding_settings,tokenizer_id)
        index_same=active is not None and index_profiles_match(active,chroma_settings,bm25_settings)
        encode=sorted(merged) if force or not encoding_same else sorted(added+updated)
        reuse=sorted(set(merged)-set(encode))
        reusable=not force and not added and not updated and encoding_same and index_same
        return _IngestionPlan([merged[uid] for uid in sorted(merged)],added,updated,unchanged,retained,reusable,
            encode,reuse,encoding_same,index_same)
    except Exception:raise IngestionJobError('plan','ingestion_plan_failed') from None


def encoding_profiles_match(base,ingestion_settings,encoding_settings,tokenizer_id):
    result=bundle_encoding(base)
    profile=chunking_profile(ingestion_settings)
    return (ingestion_settings==base.ingestion_settings and
        profile==chunking_profile(base.ingestion_settings) and
        all(digest(chunk.metadata.get('component_metadata'))==digest(profile) for chunk in base.chunks) and
        all(chunk.metadata.get('retrieval_view',{}).get('policy_id')==POLICY_ID for chunk in base.chunks) and
        encoding_settings.model_space_id==result.model_space_id and
        encoding_settings.representation_id==result.representation_id and tokenizer_id==result.tokenizer_id)


def index_profiles_match(active,chroma_settings,bm25_settings):
    version=active.version
    return (chroma_settings.collection_name==version.chroma_collection_name and version.chroma_sdk_version==CHROMA_VERSION and
        bm25_settings.k1==version.bm25_k1 and bm25_settings.b==version.bm25_b and version.bm25_sdk_version==BM25_VERSION)


def profiles_match(active,base,ingestion_settings,encoding_settings,tokenizer_id,chroma_settings,bm25_settings):
    """Removal and whole-version reuse require both independent identities."""
    return (encoding_profiles_match(base,ingestion_settings,encoding_settings,tokenizer_id) and
        index_profiles_match(active,chroma_settings,bm25_settings))
