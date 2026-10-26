"""Explicit relations bind the loaded registry and original source, never inferred truth."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from naiyue_rag.core.errors import RelationError
from naiyue_rag.ingestion.document_relations import build_document_relations
from test_document_chunker import document, offline


def doc(text,path,did,kb='kb'):
    value=document(text,path);value.id=did;value.metadata['knowledge_base_id']=kb
    return value


def links(result):
    return [e for e in result['edges'] if e['kind']=='markdown_link']


def pairs(result):
    return [e for e in result['edges'] if e['kind']=='filename_pair']


def categories(result):
    return {d['category'] for d in result['diagnostics']}


def assert_quotes(docs,result):
    sources={d.id:d for d in docs}
    for edge in result['edges']:
        src=sources[edge['from_document_id']];dst=sources[edge['to_document_id']]
        assert edge['from_source_sha256']==src.metadata['source_sha256']
        assert edge['to_source_sha256']==dst.metadata['source_sha256']
        if edge['kind']=='markdown_link':
            span=edge['source_span']
            assert src.text[span['start_char']:span['end_char']]==edge['quote']
            assert span['source_sha256']==src.metadata['source_sha256']
            declaration=edge['declaration']
            if declaration:
                at=declaration['source_span']
                assert src.text[at['start_char']:at['end_char']]==declaration['quote']
        else:
            assert edge['quote'] is None and edge['source_span'] is None


@pytest.mark.parametrize('newline',['\n','\r\n','\r'],ids=['LF','CRLF','CR'])
def test_links_pairs_cycle_and_repeated_quotes_have_exact_positions(newline):
    docs=[doc('# L2 A\n> 前置依赖：[M](../L1/L1_M.md)\n## 内容\n[M](../L1/L1_M.md)\n','L2/L2_A.md','A'),
          doc('# L1 M\n[A](../L2/L2_A.md)\n[M](L1_M.md)\n','L1/L1_M.md','M'),
          doc('# 测试用例\n> 对应需求：[A](L2_A.md)\n','L2/L2_A_测试用例.md','T')]
    docs=[doc(d.text.replace('\n',newline),d.metadata['source_path'],d.id) for d in docs]
    result=build_document_relations(docs)
    assert len(links(result))==5 and len(pairs(result))==1
    repeated=[e for e in links(result) if e['from_document_id']=='A']
    assert len({e['source_span']['start_char'] for e in repeated})==2
    assert len({e['edge_id'] for e in repeated})==2
    assert sorted(e['source_span']['line_start'] for e in repeated)==[2,4]
    declared=next(e for e in repeated if e['declaration'])
    assert declared['declaration']['label']=='前置依赖'
    assert any(e['from_document_id']==e['to_document_id']=='M' for e in links(result))
    assert_quotes(docs,result)
    assert json.loads(json.dumps(result,ensure_ascii=False))==result


def test_native_syntax_protects_fences_indented_code_images_comments_inline_code():
    text='# A\n\n~~~~md\n[x](b.md)\n~~~~\n\n    [x](b.md)\n\n> ```md\n> [x](b.md)\n> ```\n\n`[x](b.md)` ``[x](b.md)`` [x](b.md)\n\n![image [x](b.md)](b.md)\n\n<!-- [x](b.md) -->\n\n\\[x](b.md)\n'
    docs=[doc(text,'a.md','A'),doc('# B','b.md','B')]
    result=build_document_relations(docs)
    assert len(links(result))==1
    prefix='`[x](b.md)` ``[x](b.md)`` '
    assert links(result)[0]['source_span']['start_char']==text.index(prefix)+len(prefix)
    assert_quotes(docs,result)


@pytest.mark.parametrize('text',[
    '`start\n[x](b.md)\nend`',
    '![start\n[x](b.md)\nend](b.md)',
],ids=['multiline-inline-code','multiline-image'])
def test_multiline_inline_syntax_cannot_turn_inner_sample_into_document_edge(text):
    result=build_document_relations([doc(text,'a.md','A'),doc('# B','b.md','B')])
    assert not result['edges']


@pytest.mark.parametrize('target,category',[
    ('../escape.md','blocked_target'),('/tmp/a.md','blocked_target'),
    ('C:/a.md','blocked_target'),('//host/a.md','blocked_target'),
    ('a.md?x=1','blocked_target'),('%2e%2e/a.md','blocked_target'),
    ('%252e%252e/a.md','blocked_target'),('bad%ZZ.md','blocked_target'),
    ('a%00.md','blocked_target'),('a%5Cb.md','blocked_target'),
    ('C%3A/a.md','blocked_target'),('file%3A/a.md','blocked_target'),
    ('javascript:alert','blocked_target'),('file:///a.md','blocked_target'),
    ('https://example.com/a.md','external_reference'),('#local','local_anchor'),
    ('missing.md','target_not_loaded'),
])
def test_targets_never_escape_or_read_unloaded_sources(target,category,monkeypatch):
    docs=[doc(f'# A\n[x]({target})\n','a.md','A')]
    def forbidden(*args,**kwargs):raise AssertionError('target IO forbidden')
    monkeypatch.setattr(Path,'open',forbidden)
    monkeypatch.setattr(Path,'resolve',forbidden)
    result=build_document_relations(docs)
    assert not result['edges'] and category in categories(result)


def test_percent_decoding_once_and_unverified_fragment():
    docs=[doc('[x](../L1/%E6%A8%A1%E5%9D%97%20A.md#section)','L2/a.md','A'),
          doc('# 模块','L1/模块 A.md','B')]
    result=build_document_relations(docs)
    assert len(links(result))==1
    edge=links(result)[0]
    assert edge['canonical_target']=='L1/模块 A.md' and edge['fragment']=='section'
    assert 'fragment_unresolved' in categories(result)
    assert_quotes(docs,result)


@pytest.mark.parametrize('text',[
    '[x][key]\n[key]: b.md\n','[x](bad(link).md)',
    '[x](b.md "title")','[x](\nb.md)','[x](<b.md>)',r'[x\]](b.md)',
],ids=['reference','nested-target','title','multiline','angle-target','escaped-label'])
def test_unsupported_reference_is_diagnosed_without_partial_edge(text):
    result=build_document_relations([doc(text,'a.md','A'),doc('# B','b.md','B')])
    assert not result['edges'] and 'unsupported_reference' in categories(result)


@pytest.mark.parametrize('fault,expected',[
    ('missing','missing_pair'),('ambiguous','ambiguous_pair'),
    ('conflict','pair_conflict'),('unresolved-header','pair_conflict'),
    ('unsupported-header','pair_conflict'),('no-link-header','pair_conflict'),
],ids=['missing','ambiguous','conflict','unresolved','unsupported','no-link'])
def test_filename_pairing_ambiguity_and_header_conflict_are_explicit(fault,expected):
    text='# 测试用例\n'
    if fault=='conflict':text+='> 对应需求：[B](L2_B.md)\n'
    if fault=='unresolved-header':text+='> 对应需求：[B](missing.md)\n'
    if fault=='unsupported-header':text+='> 对应需求：[A][ref]\n'
    if fault=='no-link-header':text+='> 对应需求：尚待核对\n'
    docs=[doc(text,'L2/L2_A_测试用例.md','T')]
    if fault!='missing':docs.append(doc('# A','L2/L2_A.md','A'))
    if fault=='ambiguous':docs.append(doc('# A','other/L2_A.md','A2'))
    if fault=='conflict':docs.append(doc('# B','L2/L2_B.md','B'))
    result=build_document_relations(docs)
    assert not pairs(result) and expected in categories(result)
    if fault=='conflict':assert [(e['from_document_id'],e['to_document_id']) for e in links(result)]==[('T','B')]


def test_cross_level_pair_and_body_link_do_not_override_name():
    docs=[doc('# 测试用例\n> 上层引用：[B](../L1/B.md)\n## 内容\n> 对应模块：[B](../L1/B.md)\n','L2/L1_A_测试用例.md','T'),
          doc('# L1 A','L1/L1_A.md','A'),doc('# B','L1/B.md','B')]
    result=build_document_relations(docs)
    assert [(e['from_document_id'],e['to_document_id']) for e in pairs(result)]==[('T','A')]
    assert 'pair_conflict' not in categories(result)
    assert_quotes(docs,result)


def test_duplicate_correspondence_to_same_target_does_not_invent_conflict():
    docs=[doc('# 用例\n> 对应需求：[A](L2_A.md)、[A](L2_A.md)\n','L2_A_测试用例.md','T'),
          doc('# A','L2_A.md','A')]
    result=build_document_relations(docs)
    assert len(pairs(result))==1 and len(links(result))==2
    assert 'pair_conflict' not in categories(result)


def test_nfc_names_are_exact_and_case_sensitive():
    docs=[doc('# 用例','L2/L1_Cafe\u0301_测试用例.md','T'),doc('# A','L1/L1_Café.md','A'),
          doc('# B','other/L1_café.md','B')]
    result=build_document_relations(docs)
    assert [(e['from_document_id'],e['to_document_id']) for e in pairs(result)]==[('T','A')]


@pytest.mark.parametrize('fault',['hash','line_starts','duplicate-id','duplicate-path','cross-kb','unsafe-path','not-list'])
def test_invalid_registry_fails_whole_operation_without_sensitive_log(fault,caplog):
    first=doc('# SYNTHETIC_PRIVATE\n正文','a.md','A');docs=[first]
    if fault=='hash':first.metadata['source_sha256']='0'*64
    elif fault=='line_starts':first.metadata['line_starts']=[0,999]
    elif fault=='duplicate-id':docs.append(doc('# B','b.md','A'))
    elif fault=='duplicate-path':docs.append(doc('# B','a.md','B'))
    elif fault=='cross-kb':docs.append(doc('# B','b.md','B','other'))
    elif fault=='unsafe-path':first.metadata['source_path']='../SYNTHETIC_PRIVATE.md'
    else:docs=(first,)
    with pytest.raises(RelationError,match='^invalid_relation_documents$'):
        build_document_relations(docs)
    assert 'SYNTHETIC_PRIVATE' not in caplog.text
    assert 'code=invalid_relation_documents' in caplog.text


def test_version_identity_order_stability_and_mutable_output_isolation():
    docs=[doc('[B](b.md)','a.md','A'),doc('# B','b.md','B')]
    before=[d.to_dict() for d in docs]
    result=build_document_relations(docs)
    assert result==build_document_relations(list(reversed(docs)))
    assert [d.to_dict() for d in docs]==before
    changed=[docs[0],doc('# B\nupdated','b.md','B')]
    newer=build_document_relations(changed)
    assert result['source_fingerprint']!=newer['source_fingerprint']
    assert result['edges'][0]['edge_id']!=newer['edges'][0]['edge_id']
    result['nodes'][0]['source_path']='changed'
    assert build_document_relations(docs)['nodes'][0]['source_path']!='changed'


def test_empty_library_and_no_relation_documents_are_valid():
    result=build_document_relations([])
    assert result['knowledge_base_id'] is None and result['nodes']==[] and result['edges']==[]
    single=build_document_relations([doc('# 内容\n无引用','a.md','A')])
    assert single['edges']==[] and single['diagnostics']==[]


def test_parser_exception_is_observable_without_original_payload(monkeypatch,caplog):
    from naiyue_rag.ingestion import document_relations as module
    def failure():raise RuntimeError('SYNTHETIC_PRIVATE_PROVIDER_TEXT')
    monkeypatch.setattr(module,'_parser',failure)
    with pytest.raises(RelationError,match='^relation_parse_failed$'):
        build_document_relations([doc('# A','a.md','A')])
    assert 'SYNTHETIC_PRIVATE' not in caplog.text and 'code=relation_parse_failed' in caplog.text
