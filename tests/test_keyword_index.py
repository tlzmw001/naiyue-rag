import copy
import importlib
import json
import math
import socket

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)


@pytest.fixture
def mod(): return importlib.import_module('experiments.keyword_index')


def settings():
    return {'bm25_k1': 1.5, 'bm25_b': .75, 'bm25_method': 'lucene',
            'tokenizer_policy': 'zh-search-ascii-ident-v1', 'backend': 'numpy'}


def corpus(texts):
    from experiments.vector_index import load_corpus
    from vector_fixtures import CORPUS
    base = load_corpus(CORPUS, 'examples/mock-v1')['units'][0]
    units = [dict(base, unit_id=f'u{i}', document_id=f'D{i}', body=text,
                  contexts=[], rendered_text=text, rendered_characters=len(text)) for i,text in enumerate(texts)]
    return {'units': units, 'sources': {u['document_id']: {} for u in units},
            'fingerprint': 'synthetic-small-corpus', 'excluded_ids': []}


def test_identifiers_chinese_search_and_query_dedup(mod, tmp_path):
    tok = mod.Tokenizer(tmp_path/'jieba')
    tokens = tok.tokenize('TC-02 pv_short_raw PV_SHORT_RAW 123 中文检索测试')
    assert tokens[:4] == ['tc-02', 'pv_short_raw', 'pv_short_raw', '123']
    assert any(any('\u4e00' <= c <= '\u9fff' for c in term) for term in tokens[4:])
    assert tok.tokenize('TC-02 tc-02', query=True) == ['tc-02']
    assert tok.tokenize(' | < > ! ') == []
    assert len(tok.identity['dictionary_sha256']) == 64
    assert (tmp_path/'jieba/jieba.cache').is_file()


def test_hand_calculation_and_repeated_query_word(mod, tmp_path):
    tok = mod.Tokenizer(tmp_path/'jieba'); data = corpus(['alpha alpha beta', 'beta gamma'])
    index = mod.build_index(data, None, [], tok, settings())
    result = mod.search(index, 'alpha alpha', tok, 20)
    expected = math.log(1+(2-1+.5)/(1+.5))*2/(2+1.5*(1-.75+.75*3/2.5))
    assert result['candidates'][0]['score'] == pytest.approx(expected, rel=1e-12)
    assert [r['unit_id'] for r in result['candidates']] == ['u0']
    assert result['query_tokens'] == ['alpha'] and index['avgdl'] == 2.5


def test_scope_changes_statistics_before_scoring(mod, tmp_path):
    tok=mod.Tokenizer(tmp_path/'jieba'); data=corpus(['alpha beta', 'alpha '*100])
    first=mod.build_index(data, ['D0'], [], tok, settings())
    changed=copy.deepcopy(data);changed['units'][1]['body']='gamma '*1000
    second=mod.build_index(changed, ['D0'], [], tok, settings())
    assert first['N']==second['N']==1 and first['avgdl']==second['avgdl']==2
    assert mod.search(first,'alpha',tok,20)==mod.search(second,'alpha',tok,20)
    assert first['unit_ids']==['u0']
    assert mod.search(mod.build_index(data,['D0'],['D0'],tok,settings()),'alpha',tok,20)['candidates']==[]
    for scope,exclude in [([],[]),(['absent'],[]),(None,['absent'])]:
        with pytest.raises(mod.ProbeError,match='invalid_scope'):
            mod.build_index(data,scope,exclude,tok,settings())


@pytest.mark.parametrize('query',['!!!','unseen_xyz'])
def test_empty_or_oov_does_not_invent_zero_score_hits(mod,tmp_path,query):
    tok=mod.Tokenizer(tmp_path/'jieba'); index=mod.build_index(corpus(['alpha']),None,[],tok,settings())
    def forbidden(*args,**kwargs): raise AssertionError('empty query called BM25')
    index['bm25'].get_scores=forbidden
    assert mod.search(index,query,tok,20)['candidates']==[]


def test_save_reload_exact_scores_and_mapping(mod,tmp_path):
    tok=mod.Tokenizer(tmp_path/'jieba'); data=corpus(['alpha beta','alpha gamma'])
    index=mod.build_index(data,None,[],tok,settings()); folder=tmp_path/'index'
    mod.write_index(folder,index)
    loaded=mod.load_index(folder,data,None,[],tok,settings())
    assert mod.search(index,'alpha beta',tok,20)==mod.search(loaded,'alpha beta',tok,20)
    assert loaded['unit_ids']==['u0','u1'] and loaded['N']==2
    with pytest.raises(mod.ProbeError,match='output_error'):mod.write_index(folder,index)


@pytest.mark.parametrize('fault',['hash','fingerprint','tokens','mapping','params','matrix','identity','partial'])
def test_corrupt_cache_rejected(mod,tmp_path,fault):
    import numpy as np
    from experiments.vector_index import digest
    tok=mod.Tokenizer(tmp_path/'jieba');data=corpus(['alpha beta','gamma'])
    folder=tmp_path/'index';mod.write_index(folder,mod.build_index(data,None,[],tok,settings()))
    manifest_path=folder/'manifest.json';header=json.loads(manifest_path.read_text())
    if fault=='hash':(folder/'vocab.index.json').write_text('{}')
    if fault=='fingerprint':data['fingerprint']='changed'
    if fault=='identity':header['identity']['dictionary_sha256']='wrong'
    if fault=='partial':header['status']='partial'
    filename=None
    if fault=='tokens':filename='tokens.jsonl';(folder/filename).write_text('{}\n')
    if fault=='mapping':filename='mapping.json';(folder/filename).write_text('["u1","u0"]')
    if fault=='params':
        filename='params.index.json';params=json.loads((folder/filename).read_text());params['k1']=9
        (folder/filename).write_text(json.dumps(params))
    if fault=='matrix':
        filename='data.csc.index.npy';np.save(folder/filename,np.array([float('nan')]))
    if filename:header['files'][filename]=digest((folder/filename).read_bytes())
    manifest_path.write_text(json.dumps(header))
    with pytest.raises(mod.ProbeError,match='keyword_cache_mismatch'):
        mod.load_index(folder,data,None,[],tok,settings())


def test_tokenless_document_and_dictionary_cache_io_failure(mod,tmp_path,monkeypatch):
    tok=mod.Tokenizer(tmp_path/'jieba')
    with pytest.raises(mod.ProbeError,match='tokenization_error'):
        mod.build_index(corpus(['!!!']),None,[],tok,settings())
    monkeypatch.setattr(mod.jieba.Tokenizer,'initialize',lambda self:None)
    with pytest.raises(mod.ProbeError,match='tokenizer_error'):mod.Tokenizer(tmp_path/'bad-cache')


@pytest.mark.parametrize('k',[0,21,True])
def test_invalid_limit(mod,tmp_path,k):
    tok=mod.Tokenizer(tmp_path/'jieba');index=mod.build_index(corpus(['alpha']),None,[],tok,settings())
    with pytest.raises(mod.ProbeError,match='invalid_candidate_k'):mod.search(index,'alpha',tok,k)


def test_score_all_preserves_old_top20_and_exposes_lower_matches(mod,tmp_path):
    tok=mod.Tokenizer(tmp_path/'jieba');index=mod.build_index(corpus(['alpha '+str(i) for i in range(30)]),None,[],tok,settings())
    full=mod.score_all(index,'alpha',tok);top=mod.search(index,'alpha',tok,20)
    assert len(full['candidates'])==30 and len(top['candidates'])==20
    assert dict(full,candidates=full['candidates'][:20])==top
    assert mod.score_all(index,'???',tok)['candidates']==[]
