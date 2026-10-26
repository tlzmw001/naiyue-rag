import copy
import importlib

import pytest


@pytest.fixture
def mod():return importlib.import_module('experiments.rank_fusion')


def units():return {k:{'unit_id':k,'body':k,'body_span':{'start_char':0,'end_char':1}} for k in ['a','b','c']}


def rows(pool,ids,method):return [dict(pool[k],rank=i+1,score=.9-i*.1,retrieval_method=method) for i,k in enumerate(ids)]


def test_equal_weight_rank_contributions_and_single_route(mod):
    pool=units();dense=rows(pool,['b','a'],'vector');sparse=rows(pool,['a','c'],'sparse')
    out=mod.fuse(dense,sparse,pool,60,20)
    assert [r['unit_id'] for r in out['candidates']]==['a','b','c']
    a=out['candidates'][0]
    assert a['score']==1/62+1/61 and a['retrieval_method']=='hybrid' and a['score_kind']=='rrf'
    assert a['retrieval_info']['dense_rank']==2 and a['retrieval_info']['sparse_rank']==1
    assert out['candidates'][1]['retrieval_info']['sparse_rank'] is None
    assert mod.fuse([],[],pool,60,20)=={'candidates':[],'union_candidates':[]}
    assert [r['unit_id'] for r in mod.fuse(dense,[],pool,60,20)['candidates']]==['b','a']


def test_ties_and_union_limit(mod):
    pool={str(i):{'unit_id':str(i),'body':str(i)} for i in range(40)}
    a=rows(pool,list(pool)[:20],'vector');b=rows(pool,list(pool)[20:],'sparse')
    out=mod.fuse(a,b,pool,60,20)
    assert len(out['union_candidates'])==40 and len(out['candidates'])==20
    assert out['candidates'][0]['unit_id']=='0' and out['candidates'][1]['unit_id']=='20'


@pytest.mark.parametrize('fault',['duplicate','rank','body','span','score','id','method'])
def test_invalid_inputs_not_double_counted_or_silently_accepted(mod,fault):
    pool=units();dense=rows(pool,['a','b'],'vector')
    if fault=='duplicate':dense[1]=dict(dense[0],rank=2)
    if fault=='rank':dense[0]['rank']=2
    if fault=='body':dense[0]['body']='invented'
    if fault=='span':dense[0]['body_span']={'start_char':0,'end_char':99}
    if fault=='score':dense[0]['score']=float('nan')
    if fault=='id':dense[0]['unit_id']='absent'
    if fault=='method':dense[0]['retrieval_method']='other'
    with pytest.raises(mod.ProbeError,match='invalid_candidates'):mod.fuse(dense,[],pool,60,20)


def test_does_not_mutate_input(mod):
    pool=units();dense=rows(pool,['a'],'vector');old=copy.deepcopy(dense)
    mod.fuse(dense,[],pool,60,20)
    assert dense==old and 'retrieval_info' not in pool['a']
