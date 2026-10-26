"""Whole source-bound evidence, independent context/JSON budgets and thin query wiring."""
import json
import pytest
from test_query_preparation import job
from test_document_manager import prepared,second
from test_dense_retrieval import native_query
from test_hybrid_search import searcher
from test_reranking import Backend,config
from test_query_encoding import QUERY


def build(job,**changes):
    from naiyue_rag import CoreReranker,KnowledgeReader,ResponseBuilder,EvidenceSettings
    hybrid=searcher(job[0]).search(QUERY)
    ranked=CoreReranker(config(top_k=20),Backend()).rerank(hybrid)
    cfg=EvidenceSettings.from_dict(dict(max_context_characters=100000,max_response_bytes=1000000)|changes)
    return ResponseBuilder(KnowledgeReader(job[0].manager.settings),cfg),ranked


def test_all_sources_citations_and_actual_spans(job,native_query):
    builder,ranked=build(job);raw=builder.build(ranked)
    assert raw['status']=='retrieved' and raw['answerability']=='unknown'
    assert raw['active']==ranked.hybrid.prepared.active.to_dict() and raw['context_text']
    assert len(raw['evidence'])==len(ranked.hits) and not raw['omitted']
    chunks={h.chunk.id:h.chunk for h in ranked.hybrid.hits}
    bundle=job[0].manager.bundles.load(ranked.hybrid.prepared.active.version.bundle_id)
    docs={d.id:d for d in bundle.documents}
    for i,e in enumerate(raw['evidence'],1):
        chunk=chunks[e['chunk_id']];span=e['body_span'];doc=docs[e['document_id']]
        assert e['citation_id']==f'E{i}' and f'[E{i}]' in raw['context_text']
        assert e['body']==chunk.text==doc.text[span['start_char']:span['end_char']]
        assert e['source_sha256']==doc.metadata['source_sha256']==span['source_sha256']
        assert all(c['text'] in raw['context_text'] for c in e['contexts'])
        assert e['retrieval']['rrf_score']==next(h.score for h in ranked.hybrid.hits if h.chunk.id==chunk.id)
    encoded=json.dumps(raw);assert 'dense_vector' not in encoded and 'embedding_text' not in encoded and 'query_terms' not in encoded
    assert raw['observations']['embedding']==ranked.hybrid.prepared.encoding.report.to_dict()


def test_context_budget_counts_rendering_and_does_not_cut_rows(job,native_query):
    from dataclasses import replace
    builder,ranked=build(job);full=builder.build(ranked)
    builder.settings=replace(builder.settings,max_context_characters=len(full['context_text']))
    assert builder.build(ranked)['evidence']==full['evidence']
    builder.settings=replace(builder.settings,max_context_characters=1)
    none=builder.build(ranked)
    assert none['status']=='no_evidence_fits' and none['evidence']==[] and none['context_text']==''
    assert len(none['omitted'])==len(ranked.hits) and {o['reason'] for o in none['omitted']}=={'context_budget'}
    # A large first item may be omitted while a later complete small item fits.
    units=full['context_text'].split('\n\n[E')
    small=min(len(s) for s in units)+20
    builder.settings=replace(builder.settings,max_context_characters=small)
    packed=builder.build(ranked)
    assert len(packed['context_text'])<=small
    for evidence in packed['evidence']:
        assert evidence['body']==next(h.chunk.text for h in ranked.hybrid.hits if h.chunk.id==evidence['chunk_id'])


def test_whole_json_limit_is_not_context_limit(job,native_query):
    from naiyue_rag import EvidenceError
    builder,ranked=build(job,max_response_bytes=10)
    with pytest.raises(EvidenceError,match='evidence_response_limit') as caught:builder.build(ranked)
    assert caught.value.observations['rerank']==ranked.report and not hasattr(caught.value,'evidence')


def test_empty_states_do_not_invent_answerability(job,native_query):
    from naiyue_rag import CoreReranker
    builder,_=build(job)
    empty=searcher(job[0]).search(QUERY,scope_document_ids=[])
    result=builder.build(CoreReranker(config(enabled=False)).rerank(empty))
    assert result['status']=='empty' and result['evidence']==[] and result['answerability']=='unknown'
    assert result['observations']['embedding'] is None


def test_stored_source_audit_rejects_valid_but_changed_chunk(job,native_query):
    from naiyue_rag import EvidenceError
    builder,ranked=build(job)
    # Metadata additions pass the structural DTO but are not the stored original.
    ranked.hybrid.hits[0].chunk.metadata['marker']='SYNTHETIC_PRIVATE'
    # The same candidate also appears in one/both underlying retrieval lists.
    uid=ranked.hybrid.hits[0].chunk.id
    for hit in ranked.hybrid.dense_hits+ranked.hybrid.sparse_hits:
        if hit.chunk.id==uid:hit.chunk.metadata['marker']='SYNTHETIC_PRIVATE'
    with pytest.raises(EvidenceError,match='evidence_source_mismatch') as caught:builder.build(ranked)
    assert 'SYNTHETIC_PRIVATE' not in str(caught.value)+json.dumps(caught.value.to_dict())


def test_pipeline_is_real_consumer_and_encodes_once(job,native_query):
    from naiyue_rag import RetrievalPipeline,CoreReranker
    builder,_=build(job);job[3].calls.clear();job[4].calls.clear()
    backend=Backend();pipeline=RetrievalPipeline(searcher(job[0]),CoreReranker(config(),backend),builder)
    result=pipeline.query(QUERY,expected_revision=1)
    assert result['evidence'] and len(job[3].calls)==len(job[4].calls)==len(backend.calls)==1


@pytest.mark.parametrize('change',[dict(max_context_characters=True),dict(max_response_bytes=0),dict(extra=1)])
def test_evidence_settings_strict(change):
    from naiyue_rag import EvidenceSettings
    from naiyue_rag.core.errors import SettingsError
    with pytest.raises(SettingsError):EvidenceSettings.from_dict(dict(max_context_characters=100,max_response_bytes=1000)|change)


def test_activation_during_rerank_keeps_original_evidence_snapshot(job,native_query,prepared,tmp_path):
    from naiyue_rag import CoreReranker
    builder,original=build(job);old=original.hybrid.prepared.active
    newer,uid=second(prepared,tmp_path);backend=Backend();score=backend.score
    def activate(query,candidates):
        newer.activate(uid,expected_revision=old.revision)
        return score(query,candidates)
    backend.score=activate
    ranked=CoreReranker(config(),backend).rerank(original.hybrid)
    response=builder.build(ranked)
    assert newer.open_active().revision==old.revision+1
    assert response['active']==old.to_dict() and response['evidence']
    assert {e['chunk_id'] for e in response['evidence']}<={h.chunk.id for h in original.hybrid.hits}


def test_final_response_explains_provider_model_and_score_domains(job,native_query):
    builder,ranked=build(job);result=builder.build(ranked)
    assert result['observations']['rerank_configuration']==dict(enabled=True,provider='llm',model='synthetic-reranker',top_k=20)
    assert result['observations']['retrieval_configuration']==ranked.hybrid.settings.to_dict()
    for evidence in result['evidence']:
        retrieval=evidence['retrieval']
        assert retrieval['dense_score_kind']=='chroma_cosine_affine_v1'
        assert retrieval['sparse_score_kind']=='bm25s_lucene_global_v1'
        assert retrieval['rrf_k']==60 and type(retrieval['rrf_rank']) is int
