import importlib
import json
import socket
from pathlib import Path

import pytest
from vector_fixtures import CORPUS


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*a,**k): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbid)
    monkeypatch.setattr(socket.socket,'connect_ex',forbid)


@pytest.fixture
def setup():
    m=importlib.import_module('experiments.vector_eval')
    from experiments.vector_index import load_corpus
    c=load_corpus(CORPUS,'examples/mock-v1')
    return m,c,m.load_labels('examples/mock-v1/tasks.json',c)


def test_queries_do_not_include_labels(setup,tmp_path):
    m,c,gold=setup
    before=m.load_queries('examples/mock-v1/tasks.json',c)
    assert len(before)==4 and set(before[0])=={'task_id','query','scope_ids','exclude_ids'}
    data=json.loads(Path('examples/mock-v1/tasks.json').read_text())
    data['tasks'][0]['candidate_required_evidence']=['E11']
    data['tasks'][0]['expected_status']='fake'
    p=tmp_path/'tasks.json';p.write_text(json.dumps(data))
    assert before==m.load_queries(p,c)


def rows_for(gold,c,eids):
    rows=[]
    for eid in eids:
        label=gold['evidence'][eid]
        unit=next(u for u in c['units'] if u['document_id']==label['document_id'] and
                  u['body_span']['start_char']<=label['start'] and u['body_span']['end_char']>=label['last_nonwhite']+1)
        rows.append(dict(unit,rank=len(rows)+1,score=0.5,retrieval_method='vector'))
    return rows


def test_recall_coverage_and_failure_causes(setup):
    m,c,gold=setup
    required=gold['tasks']['Q01']['required']
    candidates=rows_for(gold,c,required[:-1]); selected=candidates[:-1]
    result={'task_id':'Q01','candidates':candidates,'selected':selected,'max_context_chars':8000,'answerability':'unknown'}
    evaluated=m.evaluate(result,c,gold)
    assert evaluated['recall_at_10']==evaluated['recall_at_20']==7/8
    assert evaluated['coverage_at_budget']==6/8
    assert evaluated['not_recalled']==['E08'] and evaluated['budget_excluded']==['E07']
    assert evaluated['annotation_origin']=='assistant_constructed_synthetic_candidates'


def test_partial_span_is_not_complete_evidence(setup):
    m,c,gold=setup
    rows=rows_for(gold,c,['E01'])
    rows[0]['body_span']=dict(rows[0]['body_span'],end_char=rows[0]['body_span']['start_char']+20)
    result={'task_id':'Q02','candidates':rows,'selected':rows,'max_context_chars':8000,'answerability':'unknown'}
    assert m.evaluate(result,c,gold)['coverage_at_budget']==0


def test_no_answer_denominator_and_system_status_not_faked(setup):
    m,c,gold=setup
    result={'task_id':'Q04','candidates':[],'selected':[],'max_context_chars':8000,'answerability':'unknown'}
    evaluated=m.evaluate(result,c,gold)
    assert evaluated['recall_at_10'] is None and evaluated['coverage_at_budget'] is None
    assert evaluated['expected_status']=='insufficient_evidence' and evaluated['system_answerability']=='unknown'


@pytest.mark.parametrize('fault',['hash','range','query','scope','duplicate'])
def test_bad_labels_or_query_rejected(setup,tmp_path,fault):
    m,c,gold=setup
    data=json.loads(Path('examples/mock-v1/tasks.json').read_text())
    if fault=='hash': data['evidence_units']['E01']['source_sha256']='bad'
    if fault=='range': data['evidence_units']['E01']['line_end']=9999
    if fault=='query': data['tasks'][0]['query']=' '
    if fault=='scope': data['tasks'][0]['scope_document_ids']=[]
    if fault=='duplicate': data['tasks'].append(data['tasks'][0])
    p=tmp_path/'tasks.json';p.write_text(json.dumps(data))
    with pytest.raises(m.ProbeError):
        m.load_queries(p,c);m.load_labels(p,c)
