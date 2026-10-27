"""Fixed real HybridResult candidates, strict rank mapping and baseline branches."""
import copy
import json
from dataclasses import replace
import pytest
from test_query_preparation import job
from test_document_manager import prepared,second
from test_dense_retrieval import native_query
from test_hybrid_search import searcher
from test_query_encoding import QUERY


def config(**changes):
    from naiyue_rag.core.rerank_settings import RerankSettings
    return RerankSettings.from_dict(dict(enabled=True,top_k=2,max_candidates=20,max_input_characters=100000)|changes)


class Backend:
    provider='llm';model='synthetic-reranker'
    def __init__(self):self.calls=[];self.output=None
    def score(self,query,candidates):
        from naiyue_rag.reranking.report import new_report
        self.calls.append((query,copy.deepcopy(candidates)))
        report=new_report();report['status']='success'
        return self.output if self.output is not None else [dict(passage_id=c['passage_id'],score=i) for i,c in enumerate(candidates)],report


@pytest.mark.parametrize('changes',[dict(enabled=1),dict(top_k=True),dict(max_candidates=0),dict(max_input_characters=-1),dict(extra=1)])
def test_invalid_settings(changes):
    from naiyue_rag.core.errors import SettingsError
    with pytest.raises(SettingsError):config(**changes)


def test_actual_hybrid_rerank_mapping_roundtrip_and_copy(job,native_query):
    from naiyue_rag import CoreReranker,RerankResult
    pipeline,_,_,dense,sparse=job;hybrid=searcher(pipeline).search(QUERY);before=hybrid.to_dict();backend=Backend()
    result=CoreReranker(config(),backend).rerank(hybrid)
    assert [h['chunk_id'] for h in result.hits]==[h.chunk.id for h in reversed(hybrid.hits)][:2]
    assert [h['rank'] for h in result.hits]==[1,2] and result.report['status']=='success'
    assert len(dense.calls)==len(sparse.calls)==1 and backend.calls[0][0]==QUERY.strip()
    assert {c['passage_id'] for c in backend.calls[0][1]}=={h.chunk.id for h in hybrid.hits}
    for hit,candidate in zip(hybrid.hits,backend.calls[0][1],strict=True):
        assert hit.chunk.metadata['retrieval_view']['text'] in candidate['text']
        assert all(c['text'] in candidate['text'] for c in hit.chunk.metadata['contexts'])
    assert hybrid.to_dict()==before and result.hybrid is not hybrid
    assert RerankResult.from_dict(json.loads(json.dumps(result.to_dict()))).to_dict()==result.to_dict()
    result.hybrid.hits[0].chunk.metadata['marker']='mutated'
    assert hybrid.to_dict()==before


@pytest.mark.parametrize('enabled',[True,False])
def test_empty_does_not_call_backend(job,native_query,enabled):
    from naiyue_rag import CoreReranker
    hybrid=searcher(job[0]).search(QUERY,scope_document_ids=[]);backend=Backend()
    result=CoreReranker(config(enabled=enabled),backend if enabled else None).rerank(hybrid)
    assert result.hits==[] and backend.calls==[] and result.report['attempted_requests']==0
    assert result.report['status']==('empty' if enabled else 'disabled')


def test_disabled_and_equal_scores_keep_original_order(job,native_query):
    from naiyue_rag import CoreReranker
    hybrid=searcher(job[0]).search(QUERY);backend=Backend()
    disabled=CoreReranker(config(enabled=False)).rerank(hybrid)
    assert [h['chunk_id'] for h in disabled.hits]==[h.chunk.id for h in hybrid.hits][:2]
    assert disabled.provider=='none' and disabled.model is None and disabled.scores==[]
    backend.output=[dict(passage_id=h.chunk.id,score=.5) for h in reversed(hybrid.hits)]
    ranked=CoreReranker(config(),backend).rerank(hybrid)
    assert ranked.hits==[dict(rank=i,chunk_id=h.chunk.id,score=.5) for i,h in enumerate(hybrid.hits[:2],1)]


@pytest.mark.parametrize('fault',['missing','unknown','duplicate','bool','nan','extra','raise'])
def test_whole_failure_never_falls_back_or_leaks(job,native_query,fault,caplog):
    from naiyue_rag import CoreReranker,RerankError
    hybrid=searcher(job[0]).search(QUERY);backend=Backend()
    output=[dict(passage_id=h.chunk.id,score=.5) for h in hybrid.hits]
    if fault=='missing':output.pop()
    elif fault=='unknown':output[0]['passage_id']='SYNTHETIC_PRIVATE'
    elif fault=='duplicate':output[-1]=output[0].copy()
    elif fault=='bool':output[0]['score']=True
    elif fault=='nan':output[0]['score']=float('nan')
    elif fault=='extra':output[0]['text']='SYNTHETIC_PRIVATE'
    else:
        def fail(*args):raise OSError('SYNTHETIC_PRIVATE')
        backend.score=fail
    backend.output=output
    with pytest.raises(RerankError) as caught:CoreReranker(config(),backend).rerank(hybrid)
    error=caught.value
    assert not hasattr(error,'hits') and error.report['status']=='error'
    assert error.encoding_report.to_dict()==hybrid.prepared.encoding.report.to_dict()
    assert 'SYNTHETIC_PRIVATE' not in str(error)+caplog.text+json.dumps(error.to_dict())


@pytest.mark.parametrize('change',[dict(max_candidates=1),dict(max_input_characters=1)])
def test_limit_is_preflight_before_model(job,native_query,change):
    from naiyue_rag import CoreReranker,RerankError
    backend=Backend();hybrid=searcher(job[0]).search(QUERY)
    with pytest.raises(RerankError,match='rerank_input_limit'):CoreReranker(config(**change),backend).rerank(hybrid)
    assert backend.calls==[]


@pytest.mark.parametrize('fault',['unknown','rank','score','provider','missing','usage','extra'])
def test_result_rejects_tampering(job,native_query,fault):
    from naiyue_rag import CoreReranker,RerankResult
    raw=CoreReranker(config(),Backend()).rerank(searcher(job[0]).search(QUERY)).to_dict()
    if fault=='unknown':raw['hits'][0]['chunk_id']='unknown'
    elif fault=='rank':raw['hits'][0]['rank']=True
    elif fault=='score':raw['hits'][0]['score']=-100
    elif fault=='provider':raw['provider']='unknown'
    elif fault=='missing':raw['scores'].pop()
    elif fault=='usage':raw['report']['usage']={'prompt_tokens':True,'completion_tokens':0,'total_tokens':1}
    else:raw['extra']='invalid'
    with pytest.raises(ValueError):RerankResult.from_dict(raw)
