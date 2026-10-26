"""Actual public consumers and cached baseline parity; no model/network calls."""
import copy
import json
from pathlib import Path

import pytest

from naiyue_rag.a2_snapshot import load_snapshot
from naiyue_rag.retrieval import retrieve_once, RetrievalError
from naiyue_rag.core import types
from naiyue_rag.core.errors import RetrievalError as CoreRetrievalError
from test_a2_snapshot import settings, allowed, VECTOR_RUN, HYBRID_RUN
from test_retrieval_once import request, provider


def observe(monkeypatch):
    calls={name:0 for name in ['Document','Chunk','QueryRequest','RetrievalResult']}
    for name,method in [('Document','from_source_record'),('Chunk','from_legacy_unit'),
                        ('QueryRequest','from_dict'),('RetrievalResult','from_candidate')]:
        cls=getattr(types,name);original=getattr(cls,method)
        def wrapper(*args,_original=original,_name=name,**kwargs):
            calls[_name]+=1;return _original(*args,**kwargs)
        monkeypatch.setattr(cls,method,wrapper)
    return calls


def test_public_error_identity():
    from naiyue_rag.retrieval import RetrievalError as LegacyRetrievalError
    assert RetrievalError is CoreRetrievalError is LegacyRetrievalError


def test_real_consumers_not_only_declared(tmp_path,monkeypatch):
    cfg=settings(tmp_path);calls=observe(monkeypatch)
    resource=load_snapshot(cfg,allowed(cfg),tmp_path/'tokenizer')
    assert calls['Document']==11 and calls['Chunk']>=52
    assert all(isinstance(v,types.Document) for v in resource._documents.values())
    assert all(isinstance(v,types.Chunk) for v in resource._chunks.values())
    result=retrieve_once(request(),resource,provider([]))
    assert calls['QueryRequest']==1 and calls['RetrievalResult']>0
    assert result['selected'] and result['answerability']=='unknown'
    for route in ['dense','sparse','hybrid']:
        for group in ['candidates','selected','budget_excluded']:
            for row in result[route][group]:
                assert types.RetrievalResult.from_candidate(row).to_candidate()==row
    for row in result['union_candidates']:
        assert types.RetrievalResult.from_candidate(row).to_candidate()==row


def test_invalid_and_unauthorized_request_precedes_embedding(tmp_path,monkeypatch):
    cfg=settings(tmp_path);calls=observe(monkeypatch)
    resource=load_snapshot(cfg,['MOCK-CASE-001'],tmp_path/'tokenizer')
    requests=[]
    for req in [request(candidate_k=True),request(scope_document_ids=['MOCK-L0-001'])]:
        with pytest.raises(RetrievalError):retrieve_once(req,resource,provider(requests))
    assert requests==[] and calls['QueryRequest']==2 and calls['RetrievalResult']==0


def test_typed_canonical_units_and_outputs_do_not_pollute_snapshot(tmp_path):
    cfg=settings(tmp_path);resource=load_snapshot(cfg,allowed(cfg),tmp_path/'tokenizer')
    expected=copy.deepcopy(resource.canonical_units())
    exposed=resource.canonical_units();exposed[next(iter(exposed))]['contexts'].clear()
    assert resource.canonical_units()==expected
    result=retrieve_once(request(),resource,provider([]))
    result['selected'][0]['contexts'].clear()
    assert resource.canonical_units()==expected


def test_original_four_queries_still_match_a2_with_core_types(tmp_path,monkeypatch):
    import hashlib
    cfg=settings(tmp_path);calls=observe(monkeypatch)
    resource=load_snapshot(cfg,allowed(cfg),tmp_path/'tokenizer')
    by_hash={r['query_sha256']:r['vector'] for r in json.loads((VECTOR_RUN/'query_vectors.json').read_text())}
    def cached(query,identity):
        h=hashlib.sha256(query.encode()).hexdigest()
        return {'query_sha256':h,'embedding_identity':identity,'vector':by_hash[h],
                'source_kind':'cached','usage':None}
    rows=[json.loads(line) for line in (HYBRID_RUN/'results.jsonl').read_text().splitlines()]
    for old in rows:
        new=retrieve_once(request(query=old['query'],scope_document_ids=old['scope_ids'],
                                 exclude_document_ids=old['exclude_ids']),resource,cached)
        for route in ['dense','sparse','hybrid']:
            for key in ['candidates','selected','budget_excluded','context_text','context_characters',
                        'max_context_chars','status','answerability']:
                assert new[route][key]==old[route][key],(old['task_id'],route,key)
        assert new['union_candidates']==old['union_candidates']
    assert calls['QueryRequest']==4 and calls['RetrievalResult']>0
