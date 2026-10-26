import copy
import importlib

import pytest


@pytest.fixture
def mod():return importlib.import_module('experiments.relation_retrieval')


def units():return {k:{'unit_id':k,'document_id':k,'body':k,'body_span':{'start_char':0,'end_char':1}} for k in ['a','b','c']}


def rows(pool,ids):return [dict(pool[k],rank=i+1,score=.03-i*.001,retrieval_method='hybrid',score_kind='rrf') for i,k in enumerate(ids)]


def test_two_routes_contributions_and_empty_preserves_a2(mod):
    pool=units();base=rows(pool,['b','a']);related=rows(pool,['a','c'])
    out=mod.combine_routes(base,related,pool,60,20)
    assert [r['unit_id'] for r in out['candidates']]==['a','b','c']
    assert out['candidates'][0]['score']==1/62+1/61
    assert out['candidates'][0]['retrieval_info']['a2_rank']==2
    assert out['candidates'][1]['retrieval_info']['relation_rank'] is None
    assert mod.combine_routes(base,[],pool,60,20)['candidates']==base
    assert 'retrieval_stage' not in base[0]


@pytest.mark.parametrize('fault',['duplicate','rank','body','score','id'])
def test_corrupt_candidate_rejected(mod,fault):
    pool=units();base=rows(pool,['a','b'])
    if fault=='duplicate':base[1]=dict(base[0],rank=2)
    if fault=='rank':base[0]['rank']=9
    if fault=='body':base[0]['body']='fake'
    if fault=='score':base[0]['score']=float('nan')
    if fault=='id':base[0]['unit_id']='absent'
    with pytest.raises(mod.ProbeError,match='invalid_candidates'):mod.combine_routes(base,[],pool,60,20)


def test_per_document_retrieval_can_include_low_global_rank_without_new_statistics(mod,tmp_path):
    from test_keyword_index import corpus,settings
    from experiments.keyword_index import Tokenizer,build_index,search,score_all
    from experiments.vector_index import search as vector_search
    data=corpus(['alpha '+str(i) for i in range(30)]);tok=Tokenizer(tmp_path/'jieba')
    keyword=build_index(data,None,[],tok,settings());all_scores=score_all(keyword,'alpha',tok)
    target=all_scores['candidates'][-1]['document_id']
    assert target not in {u['document_id'] for u in search(keyword,'alpha',tok,20)['candidates']}
    vector={'units':{u['unit_id']:u for u in data['units']},'vectors':{u['unit_id']:[1,0] for u in data['units']},
            'dimensions':2,'model':'embedding-3','source_ids':list(data['sources']),'excluded_ids':[]}
    query={'query':'alpha','scope_ids':None,'exclude_ids':[]}
    path={'seed_document_id':'D0','hops':[],'hop_count':1}
    config={'per_document_k':4,'relation_k':20,'rrf_k':60}
    out=mod.build_route(vector,keyword,[1,0],query,[{'document_id':target,'best_path':path}],tok,config)
    assert len(out['candidates'])==1 and out['candidates'][0]['document_id']==target
    assert out['N']==keyword['N']==30 and out['avgdl']==keyword['avgdl']
    assert out['candidates'][0]['score']==2/61
    assert out['documents'][0]['sparse_candidates'][0]['score']==all_scores['candidates'][-1]['score']
    with pytest.raises(mod.ProbeError,match='invalid_related_scope'):
        mod.build_route(vector,keyword,[1,0],dict(query,scope_ids=['D0']),[{'document_id':target,'best_path':path}],tok,config)
