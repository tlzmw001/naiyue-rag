import copy
import importlib
import json
import shutil
import socket
from pathlib import Path

import pytest

from vector_fixtures import CORPUS, config, vector


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)


@pytest.fixture
def mod(): return importlib.import_module('experiments.vector_index')


def test_actual_corpus_and_semantic_input(mod):
    corpus = mod.load_corpus(CORPUS, 'examples/mock-v1')
    assert len(corpus['units']) == 52 and len(corpus['registry']) == 11
    unit = next(u for u in corpus['units'] if u['case_id'] == 'TC-01')
    text = mod.make_index_text(unit)
    assert unit['body'] in text
    assert all(c['text'] in text for c in unit['contexts'])
    assert unit['unit_id'] not in text and unit['source_sha256'] not in text
    assert unit['source_path'] not in text


@pytest.mark.parametrize('fault', ['body', 'context', 'span', 'id', 'role', 'eligible', 'render', 'duplicate', 'count'])
def test_corrupt_corpus_rejected_before_indexing(mod, tmp_path, fault):
    copied = tmp_path / 'corpus'; shutil.copytree(CORPUS, copied)
    rows = [json.loads(s) for s in (copied / 'units.jsonl').read_text().splitlines()]
    if fault == 'body': rows[0]['body'] += ' invented'
    if fault == 'context': rows[0]['contexts'][0]['text'] += ' invented'
    if fault == 'span': rows[0]['body_span']['start_char'] = -1
    if fault == 'id': rows[0]['unit_id'] = 'wrong'
    if fault == 'role': rows[0]['role'] = 'other'
    if fault == 'eligible': rows[0]['eligible'] = False
    if fault == 'render': rows[0]['rendered_characters'] += 1
    if fault == 'duplicate': rows.append(rows[0])
    if fault == 'count':
        summary = json.loads((copied / 'summary.json').read_text()); summary['source_count'] = 1
        (copied / 'summary.json').write_text(json.dumps(summary))
    (copied / 'units.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows)+'\n')
    with pytest.raises(mod.ProbeError): mod.load_corpus(copied, 'examples/mock-v1')


def test_scope_is_applied_before_cosine_and_ties_are_stable(mod, monkeypatch):
    corpus = mod.load_corpus(CORPUS, 'examples/mock-v1')
    base = corpus['units'][0]
    units = {k: dict(base, unit_id=k, document_id=doc) for k, doc in [('a','D1'),('b','D1'),('c','D2')]}
    index = {'units': units, 'vectors': {'a':[1,0], 'b':[0,1], 'c':[2,0]},
             'dimensions': 2, 'model': 'embedding-3', 'source_ids':['D1','D2'], 'excluded_ids':['D0']}
    calls=[]; original=mod.cosine
    def cosine(q,v): calls.append(v); return original(q,v)
    monkeypatch.setattr(mod,'cosine',cosine)
    result = mod.search(index,[1,0],['D1'],[],20)
    assert result['compared_count']==2 and calls==[[1,0],[0,1]]
    assert [r['unit_id'] for r in result['candidates']]==['a','b']
    calls.clear()
    result = mod.search(index,[1,0],None,[],20)
    assert [r['unit_id'] for r in result['candidates']]==['a','c','b']
    assert [r['score'] for r in result['candidates']]==[1,1,0]
    for scope,exclude in [([],[]),(['missing'],[]),(None,['missing'])]:
        with pytest.raises(mod.ProbeError): mod.search(index,[1,0],scope,exclude,20)
    assert mod.search(index,[1,0],['D1'],['D1'],20)['candidates']==[]


def test_budget_skips_complete_long_case_and_continues(mod):
    corpus=mod.load_corpus(CORPUS,'examples/mock-v1')
    long=max(corpus['units'],key=lambda u:u['rendered_characters'])
    short=min(corpus['units'],key=lambda u:u['rendered_characters'])
    rows=[dict(u,rank=i+1,score=0.5,retrieval_method='vector') for i,u in enumerate([long,short,short])]
    result=mod.pack_evidence(rows,short['rendered_characters']+36)
    assert result['selected'][0]['unit_id']==short['unit_id'] and len(result['selected'])==1
    assert result['budget_excluded'][0]['body']==long['body']
    assert result['context_characters']==len(result['context_text'])==short['rendered_characters']+36
    assert '[vector rank=02 cosine=+0.50000000]\n' in result['context_text']
    assert result['answerability']=='unknown' and result['status']=='retrieved'
    assert mod.pack_evidence(rows,1)['status']=='no_evidence_fits'
    assert mod.pack_evidence([],8000)['status']=='empty'


def test_persist_reload_and_tampering(mod,tmp_path):
    from experiments.vector_eval import load_queries
    cfg=config(tmp_path); corpus=mod.load_corpus(CORPUS,cfg['dataset']); queries=load_queries(cfg['tasks'],corpus)
    mod.write_index(tmp_path,corpus,queries,[vector(i) for i in range(52)],[vector(i) for i in range(4)],cfg)
    index=mod.load_index(tmp_path,corpus['fingerprint'],cfg)
    assert len(index['vectors'])==52 and len(index['query_vectors'])==4
    result=mod.search(index,vector(),['MOCK-CASE-001'],[],20)
    assert result['compared_count']==10
    assert all(r['document_id']=='MOCK-CASE-001' for r in result['candidates'])
    path=tmp_path/'index_vectors.jsonl'; path.write_text(path.read_text()+'\n')
    with pytest.raises(mod.ProbeError,match='cache_mismatch'): mod.load_index(tmp_path,corpus['fingerprint'],cfg)


@pytest.mark.parametrize('fault',['model','dimension','fingerprint'])
def test_incompatible_cache_rejected(mod,tmp_path,fault):
    from experiments.vector_eval import load_queries
    cfg=config(tmp_path); corpus=mod.load_corpus(CORPUS,cfg['dataset']); queries=load_queries(cfg['tasks'],corpus)
    mod.write_index(tmp_path,corpus,queries,[vector() for _ in range(52)],[vector() for _ in queries],cfg)
    fp=corpus['fingerprint']; cfg=copy.deepcopy(cfg)
    if fault=='model': cfg['model']='different'
    if fault=='dimension': cfg['dimensions']=1024
    if fault=='fingerprint': fp='different'
    with pytest.raises(mod.ProbeError,match='cache_mismatch'): mod.load_index(tmp_path,fp,cfg)


@pytest.mark.parametrize('method,kind,label',[('hybrid','rrf','rrf='),('sparse','bm25','bm25=')])
def test_new_score_prefix_preserves_equal_budget_overhead(mod,method,kind,label):
    unit=mod.load_corpus(CORPUS,'examples/mock-v1')['units'][0]
    row=dict(unit,retrieval_method=method,score_kind=kind,score=.0123456789,rank=1)
    result=mod.pack_evidence([row],8000)
    prefix=result['context_text'][:36]
    assert len(prefix)==36 and prefix.endswith('\n') and label in prefix and 'cosine=' not in prefix
    assert result['context_text'][36:]==unit['rendered_text']


@pytest.mark.parametrize('method,kind',[('other','rrf'),('hybrid','cosine'),('sparse','rrf')])
def test_unknown_score_kind_rejected(mod,method,kind):
    unit=mod.load_corpus(CORPUS,'examples/mock-v1')['units'][0]
    with pytest.raises(mod.ProbeError,match='invalid_score_kind'):
        mod.pack_evidence([dict(unit,retrieval_method=method,score_kind=kind,rank=1,score=.5)],8000)
