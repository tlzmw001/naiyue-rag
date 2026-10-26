import copy
import importlib
import json
from pathlib import Path

import pytest

from experiments.vector_index import digest, load_corpus
from vector_fixtures import CORPUS


@pytest.fixture
def mod():return importlib.import_module('experiments.relation_index')


def settings():
    return {'relation_policy':'explicit-doc-v1','max_graph_nodes':64,'seed_k':5,
            'max_seed_documents':3,'max_hops':2,'max_related_documents':8,'max_edge_visits':128}


def material(root,docs):
    sources={};units=[];knowledge=root/'knowledge';knowledge.mkdir(parents=True)
    for did,path,text,role,level in docs:
        target=knowledge/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
        starts=[0]+[i+1 for i,c in enumerate(text) if c=='\n' and i+1<len(text)]
        sources[did]={'document_id':did,'relative_path':path,'text':text,'line_starts':starts,
                      'source_sha256':digest(text.encode()),'role':role,'semantic_level':level}
        units.append({'unit_id':'u-'+did,'document_id':did,'semantic_level':level})
    return {'sources':sources,'units':units,'fingerprint':'test-material','excluded_ids':[]}


def seed(data,did):return [dict(next(u for u in data['units'] if u['document_id']==did),rank=1,score=.03)]


def test_mock_links_pairs_and_actual_spans(mod):
    data=load_corpus(CORPUS,'examples/mock-v1');graph=mod.build_index(data,'examples/mock-v1',settings())
    assert len(graph['nodes'])==11
    assert sum(e['kind']=='markdown_link' for e in graph['edges'])==20
    assert sum(e['kind']=='filename_pair' for e in graph['edges'])==3
    assert sum(d['category']=='target_not_indexed' for d in graph['diagnostics'])==2
    for e in graph['edges']:
        if e['kind']=='markdown_link':
            s=data['sources'][e['from_document_id']];span=e['source_span']
            assert s['text'][span['start_char']:span['end_char']]==e['quote']
        else:assert e['source_span'] is None and e['quote'] is None


def test_code_images_remote_and_unsupported_reference_not_edges(mod,tmp_path):
    text='# A\n[ok](b.md#section)\n`[code](b.md)`\n![image](b.md)\n[remote](https://example.com/x.md)\n```text\n[fenced](b.md)\n```\n[complex](bad(link).md)\n[ref][key]\n'
    data=material(tmp_path,[('A','a.md',text,'module','L1'),('B','b.md','# B\n','module','L1')])
    graph=mod.build_index(data,tmp_path,settings())
    assert len(graph['edges'])==1 and graph['edges'][0]['quote']=='[ok](b.md#section)'
    assert {'fragment_unresolved','unsupported_reference'} <= {d['category'] for d in graph['diagnostics']}


@pytest.mark.parametrize('target',['../escape.md','/tmp/escape.md','C:/escape.md','%2e%2e/escape.md','%252e%252e/escape.md','bad%ZZ.md'])
def test_unsafe_target_cannot_escape_registry(mod,tmp_path,target):
    data=material(tmp_path,[('A','a.md',f'# A\n[x]({target})\n','module','L1')])
    graph=mod.build_index(data,tmp_path,settings())
    assert not graph['edges'] and any(d['category']=='blocked_target' for d in graph['diagnostics'])


def test_symlink_escape(mod,tmp_path):
    data=material(tmp_path,[('A','a.md','# A\n[x](link.md)\n','module','L1')])
    outside=tmp_path/'private.md';outside.write_text('not part of corpus')
    (tmp_path/'knowledge/link.md').symlink_to(outside)
    graph=mod.build_index(data,tmp_path,settings())
    assert graph['diagnostics'][0]['category']=='blocked_target' and not graph['edges']


@pytest.mark.parametrize('fault',['missing','ambiguous','role','conflict'])
def test_naming_pair_failure_is_visible(mod,tmp_path,fault):
    docs=[('T','L2_A_测试用例.md','# T\n','historical_test_cases','L2')]
    if fault!='missing':docs.append(('A','L2_A.md','# A\n','system' if fault=='role' else 'historical_requirement','L2'))
    if fault=='ambiguous':docs.append(('A2','nested/L2_A.md','# A2\n','historical_requirement','L2'))
    if fault=='conflict':
        docs[0]=('T','L2_A_测试用例.md','# T\n> 对应需求：[B](L2_B.md)\n','historical_test_cases','L2')
        docs.append(('B','L2_B.md','# B\n','historical_requirement','L2'))
    graph=mod.build_index(material(tmp_path,docs),tmp_path,settings())
    assert not any(e['kind']=='filename_pair' for e in graph['edges'])
    expected={'missing':'missing_pair','ambiguous':'ambiguous_pair','role':'invalid_pair_role','conflict':'pair_conflict'}[fault]
    assert expected in {d['category'] for d in graph['diagnostics']}


def test_two_hops_reverse_cycles_l0_terminal_and_scope(mod,tmp_path):
    docs=[('A','a.md','# A\n[b](b.md)\n[root](root.md)\n','module','L1'),
          ('B','b.md','# B\n[c](c.md)\n','module','L1'),
          ('C','c.md','# C\n[a](a.md)\n[d](d.md)\n','module','L1'),
          ('D','d.md','# D\n','module','L1'),
          ('R','root.md','# Root\n[z](z.md)\n','system','L0'),
          ('Z','z.md','# Z\n','module','L1')]
    data=material(tmp_path,docs);graph=mod.build_index(data,tmp_path,settings())
    result=mod.expand(graph,seed(data,'A'),data,None,[],settings())
    assert {r['document_id'] for r in result['related_documents']}=={'B','C','R','D'}
    # C is a reverse neighbor of A, so D is two hops. R must not lead to Z.
    c=next(r for r in result['related_documents'] if r['document_id']=='C')
    assert c['best_path']['hops'][0]['direction']=='reverse'
    assert all(r['best_path']['hop_count']<=2 for r in result['related_documents'])
    scoped=mod.expand(graph,seed(data,'A'),data,['A','Z'],[],settings())
    assert scoped['related_documents']==[]
    assert mod.expand(graph,seed(data,'R'),data,None,[],settings())['seeds']==[]


def test_three_hop_and_document_limit_are_real_boundaries(mod,tmp_path):
    docs=[(d,d+'.md',f'# {d}\n'+(f'[next]({chr(ord(d)+1)}.md)\n' if d!='D' else ''),'module','L1') for d in 'ABCD']
    data=material(tmp_path,docs);graph=mod.build_index(data,tmp_path,settings())
    out=mod.expand(graph,seed(data,'A'),data,None,[],settings())
    assert [r['document_id'] for r in out['related_documents']]==['B','C']
    limited=mod.expand(graph,seed(data,'A'),data,None,[],dict(settings(),max_related_documents=1))
    assert [r['document_id'] for r in limited['related_documents']]==['B']
    assert [r['document_id'] for r in limited['document_limit_excluded']]==['C']
    with pytest.raises(mod.ProbeError,match='resource_error'):
        mod.expand(graph,seed(data,'A'),data,None,[],dict(settings(),max_edge_visits=1))
    with pytest.raises(mod.ProbeError,match='resource_error'):
        mod.build_index(data,tmp_path,dict(settings(),max_graph_nodes=2))


@pytest.mark.parametrize('fault',['hash','quote','pair','status','version'])
def test_cache_reload_and_semantic_corruption(mod,tmp_path,fault):
    data=load_corpus(CORPUS,'examples/mock-v1');cfg=settings();folder=tmp_path/'graph'
    graph=mod.build_index(data,'examples/mock-v1',cfg);mod.write_index(folder,graph)
    assert mod.load_index(folder,data,'examples/mock-v1',cfg)==graph
    header=json.loads((folder/'relation_manifest.json').read_text());rows=[json.loads(s) for s in (folder/'edges.jsonl').read_text().splitlines()]
    if fault=='hash':(folder/'edges.jsonl').write_text('[]\n')
    elif fault=='status':header['status']='partial'
    elif fault=='version':data=copy.deepcopy(data);data['sources'][rows[0]['from_document_id']]['source_sha256']='changed'
    else:
        if fault=='quote':next(e for e in rows if e['kind']=='markdown_link')['quote']='invented'
        else:next(e for e in rows if e['kind']=='filename_pair')['derivation']['rule']='guessed'
        (folder/'edges.jsonl').write_text('\n'.join(json.dumps(e) for e in rows)+'\n')
        header['files']['edges.jsonl']=digest((folder/'edges.jsonl').read_bytes())
    (folder/'relation_manifest.json').write_text(json.dumps(header))
    with pytest.raises(mod.ProbeError,match='relation_cache_mismatch'):mod.load_index(folder,data,'examples/mock-v1',cfg)


def test_existing_directory_is_not_overwritten(mod,tmp_path):
    graph=mod.build_index(load_corpus(CORPUS,'examples/mock-v1'),'examples/mock-v1',settings())
    folder=tmp_path/'existing';folder.mkdir();(folder/'marker').write_text('user work')
    with pytest.raises(mod.ProbeError,match='output_error'):mod.write_index(folder,graph)
    assert (folder/'marker').read_text()=='user work'


@pytest.mark.parametrize('text',['# A\n``[code](b.md)``\n','# A\n[broken](\nb.md\n)\n'])
def test_unsupported_inline_code_or_multiline_reference_is_observable(mod,tmp_path,text):
    data=material(tmp_path,[('A','a.md',text,'module','L1'),('B','b.md','# B\n','module','L1')])
    graph=mod.build_index(data,tmp_path,settings())
    assert graph['edges']==[]
    assert 'unsupported_reference' in {d['category'] for d in graph['diagnostics']}


@pytest.mark.parametrize('field,value',[('line_start',True),('start_char',False)])
def test_cache_span_integer_types_cannot_be_replaced_by_bool(mod,tmp_path,field,value):
    data=material(tmp_path,[('A','a.md','[B](b.md)\n','module','L1'),('B','b.md','# B\n','module','L1')])
    folder=tmp_path/'graph';cfg=settings();mod.write_index(folder,mod.build_index(data,tmp_path,cfg))
    rows=[json.loads(s) for s in (folder/'edges.jsonl').read_text().splitlines()]
    rows[0]['source_span'][field]=value
    (folder/'edges.jsonl').write_text('\n'.join(json.dumps(e) for e in rows)+'\n')
    header=json.loads((folder/'relation_manifest.json').read_text())
    header['files']['edges.jsonl']=digest((folder/'edges.jsonl').read_bytes())
    (folder/'relation_manifest.json').write_text(json.dumps(header))
    with pytest.raises(mod.ProbeError,match='relation_cache_mismatch'):mod.load_index(folder,data,tmp_path,cfg)


def test_body_correspondence_quote_does_not_override_header_pairing(mod,tmp_path):
    docs=[('T','L2_A_测试用例.md','# T\n## 说明\n> 对应需求：[B](L2_B.md)\n','historical_test_cases','L2'),
          ('A','L2_A.md','# A\n','historical_requirement','L2'),
          ('B','L2_B.md','# B\n','historical_requirement','L2')]
    graph=mod.build_index(material(tmp_path,docs),tmp_path,settings())
    assert [(e['from_document_id'],e['to_document_id']) for e in graph['edges'] if e['kind']=='filename_pair']==[('T','A')]
    assert any(e['kind']=='markdown_link' and e['to_document_id']=='B' for e in graph['edges'])
    assert 'pair_conflict' not in {d['category'] for d in graph['diagnostics']}
