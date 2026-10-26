"""Source-bound chunks and parameter effects, no live model or index writes."""
import copy
import hashlib
import json
import re
import socket

import pytest

from naiyue_rag import DocumentChunker
from naiyue_rag.core.errors import ChunkingError
from naiyue_rag.core.settings import Settings
from naiyue_rag.core.types import Document, Chunk, SourceSpan
from test_settings import configuration

HEADER = '| 用例标题 | 前置条件 | 测试步骤 | 预期结果 |'
SEP = '| --- | --- | --- | --- |'
ROW = '| 正常下发 | 开关开启<br>字段匹配 | 调用 `a\\|b` | 成功 |'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args,**kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbid)
    monkeypatch.setattr(socket.socket,'connect_ex',forbid)


def settings(tmp_path, size=100, overlap=20):
    from naiyue_rag.core.ingestion_settings import IngestionSettings
    return IngestionSettings(size,overlap)


def document(text, path='L1/module.md'):
    starts=[0] if text else []
    starts.extend(m.end() for m in re.finditer(r'\r\n|\r|\n',text) if m.end()<len(text))
    return Document('doc-synthetic',text,{'knowledge_base_id':'kb','source_path':path,
        'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'size_bytes':len(text.encode()),
        'line_starts':starts})


def assert_bound(doc, chunks):
    for chunk in chunks:
        assert isinstance(chunk,Chunk) and chunk.source_ref==doc.id
        assert chunk.text==doc.text[chunk.start_offset:chunk.end_offset]
        span=SourceSpan.from_dict(chunk.metadata['body_span'])
        assert span.source_sha256==doc.metadata['source_sha256']
        assert span.start_char==chunk.start_offset and span.end_char==chunk.end_offset
        for ctx in chunk.metadata['contexts']:
            at=ctx['span']; assert ctx['text']==doc.text[at['start_char']:at['end_char']]
        assert Chunk.from_dict(json.loads(json.dumps(chunk.to_dict(),ensure_ascii=False))).to_dict()==chunk.to_dict()
        assert 'line_starts' not in chunk.metadata


def test_prose_boundaries_and_real_parameter_effects(tmp_path):
    text='# 模块\n\n## 行为\n\n'+''.join(f'步骤{i:03d}说明。' for i in range(100))
    doc=document(text)
    small,_=DocumentChunker(settings(tmp_path,80,0)).split_document(doc)
    large,_=DocumentChunker(settings(tmp_path,180,0)).split_document(doc)
    overlapped,_=DocumentChunker(settings(tmp_path,80,30)).split_document(doc)
    assert len(small)>len(large)
    assert [(c.start_offset,c.end_offset) for c in small]!=[(c.start_offset,c.end_offset) for c in overlapped]
    assert any(b.start_offset<a.end_offset for a,b in zip(overlapped,overlapped[1:]))
    assert all(len(c.text)<=80 for c in small)
    for chunks in [small,large,overlapped]: assert_bound(doc,chunks)
    assert small[0].metadata['component_metadata']['config_sha256']!=large[0].metadata['component_metadata']['config_sha256']


@pytest.mark.parametrize('newline',['\n','\r\n','\r'])
def test_complete_case_has_columns_dimension_source_and_no_fabricated_id(tmp_path,newline):
    text=f'# 测试用例\n\n## 维度一\n\n> 来源：L2 §2，L999-L1000\n\n{HEADER}\n{SEP}\n{ROW}\n'
    doc=document(text.replace('\n',newline),'L2/A_测试用例.md')
    chunks,issues=DocumentChunker(settings(tmp_path,30,0)).split_document(doc)
    cases=[c for c in chunks if c.metadata['kind']=='test_case']
    assert len(cases)==1 and cases[0].text==ROW
    case=cases[0]
    assert case.metadata['case_id'] is None
    assert case.metadata['case_fields']==['正常下发','开关开启<br>字段匹配','调用 `a\\|b`','成功']
    assert {c['context_kind'] for c in case.metadata['contexts']}>={'dimension','columns','source_note','document_title'}
    assert case.metadata['body_span']['line_start']==9
    assert case.metadata['oversize'] is True
    assert any(i['category']=='atomic_oversize' for i in issues)
    assert any(i['category']=='stale_header_line_range' for i in issues)
    assert_bound(doc,chunks)


def test_variable_columns_and_non_tc_business_number(tmp_path):
    header='| 编号 | 用例名称 | 前提条件 | 测试步骤 | 预期结果 | 优先级 | 备注 |'
    row='| CASE-A | 正常 | x | call | ok | P1 | 附注 |'
    text='# 用例\n\n## 维度\n'+header+'\n'+'| --- '*7+'|\n'+row+'\n'
    doc=document(text,'L1/A_测试用例.md')
    chunks,_=DocumentChunker(settings(tmp_path)).split_document(doc)
    case=next(c for c in chunks if c.metadata['kind']=='test_case')
    assert case.metadata['case_id']=='CASE-A' and len(case.metadata['case_fields'])==7
    assert case.text==row


def test_atomic_case_exact_limit_is_not_oversize(tmp_path):
    doc=document(f'# 测试用例\n{HEADER}\n{SEP}\n{ROW}\n','L2/A_测试用例.md')
    chunks,_=DocumentChunker(settings(tmp_path,len(ROW),0)).split_document(doc)
    case=next(c for c in chunks if c.metadata['kind']=='test_case')
    assert case.text==ROW and case.metadata['oversize'] is False


def test_same_business_number_does_not_merge_distinct_source_rows(tmp_path):
    header='| 编号 | 用例名称 | 前置条件 | 测试步骤 | 预期结果 |'
    row='| CASE-A | 正常 | x | call | ok |'
    doc=document('# 测试用例\n'+header+'\n| --- | --- | --- | --- | --- |\n'+row+'\n'+row+'\n',
                 'L2/A_测试用例.md')
    chunks,_=DocumentChunker(settings(tmp_path)).split_document(doc)
    cases=[c for c in chunks if c.metadata['kind']=='test_case']
    assert len(cases)==2 and cases[0].id!=cases[1].id
    assert cases[0].metadata['case_id']==cases[1].metadata['case_id']=='CASE-A'
    assert cases[0].start_offset!=cases[1].start_offset


def test_code_and_general_table_are_atomic_even_when_oversize(tmp_path):
    code='~~~~python\n# not a heading\n'+'value = 1\n'*20+'~~~~'
    table='| 参数 | 值 |\n| --- | --- |\n| a | '+'值'*100+' |'
    doc=document('# 模块\n\n## 配置\n\n'+code+'\n\n'+table+'\n')
    chunks,_=DocumentChunker(settings(tmp_path,40,5)).split_document(doc)
    assert next(c for c in chunks if c.metadata['kind']=='code').text==code
    assert next(c for c in chunks if c.metadata['kind']=='table').text==table
    assert not any('# not a heading' in c.metadata['heading_path'] for c in chunks)
    assert_bound(doc,chunks)


def test_unknown_case_columns_keep_table_and_diagnose(tmp_path):
    table='| 自定义标题 | 自定义步骤 |\n| --- | --- |\n| A | x |'
    doc=document('# 测试用例\n\n'+table+'\n','L2/A_测试用例.md')
    chunks,issues=DocumentChunker(settings(tmp_path)).split_document(doc)
    assert any(c.text==table and c.metadata['kind']=='table' for c in chunks)
    assert any(i['category']=='unclassified_case_table' for i in issues)


def test_ragged_table_does_not_silently_drop_cells(tmp_path):
    doc=document(f'# 测试用例\n{HEADER}\n{SEP}\n| A | x | y | ok | extra |\n','L2/A_测试用例.md')
    with pytest.raises(ChunkingError,match='^invalid_table$'):
        DocumentChunker(settings(tmp_path)).split_document(doc)


def test_malformed_case_table_not_silently_split_as_prose(tmp_path):
    doc=document(f'# 测试用例\n{HEADER}\n| broken | delimiter |\n{ROW}\n','L2/A_测试用例.md')
    with pytest.raises(ChunkingError,match='^invalid_table$'):
        DocumentChunker(settings(tmp_path,20,0)).split_document(doc)


def test_empty_case_table_keeps_header_and_separator(tmp_path):
    table=HEADER+'\n'+SEP
    doc=document('# 测试用例\n'+table+'\n','L2/A_测试用例.md')
    chunks,_=DocumentChunker(settings(tmp_path)).split_document(doc)
    assert any(c.text==table and c.metadata['kind']=='table' for c in chunks)
    assert not any(c.metadata['kind']=='test_case' for c in chunks)


@pytest.mark.parametrize('text',['',' \r\n\t'])
def test_empty_input_has_no_fabricated_chunks(tmp_path,text):
    chunks,issues=DocumentChunker(settings(tmp_path)).split_document(document(text))
    assert chunks==[] and any(i['category']=='empty_source' for i in issues)


def test_headings_only_bom_and_repeat_text_are_source_bound(tmp_path):
    for text in ['\ufeff# 标题\r\n## 小节\r\n','# A\n重复内容。\n## B\n重复内容。\n']:
        doc=document(text)
        chunks,_=DocumentChunker(settings(tmp_path,50,10)).split_document(doc)
        assert chunks; assert_bound(doc,chunks)
        if '## B' in text:
            later=next(c for c in chunks if '## B' in c.text)
            assert '## B' in later.metadata['heading_path']


@pytest.mark.parametrize('fault',['text','hash','line_starts','size'])
def test_source_binding_mutations_are_rejected(tmp_path,fault):
    doc=document('# A\n正文\n')
    if fault=='text': doc.text+='changed'
    elif fault=='hash': doc.metadata['source_sha256']='0'*64
    elif fault=='line_starts': doc.metadata['line_starts']=[0,999]
    else: doc.metadata['size_bytes']=999
    with pytest.raises(ChunkingError,match='^invalid_chunking_document$'):
        DocumentChunker(settings(tmp_path)).split_document(doc)


def test_splitter_failure_and_unmapped_fragment_safe(tmp_path,monkeypatch,caplog):
    doc=document('# SYNTHETIC_PRIVATE_TITLE\n正文\n')
    chunker=DocumentChunker(settings(tmp_path))
    def fail(*args): raise RuntimeError('SYNTHETIC_PRIVATE_EXCEPTION')
    monkeypatch.setattr(chunker._splitter,'create_documents',fail)
    with pytest.raises(ChunkingError,match='^splitter_failed$'): chunker.split_document(doc)
    assert 'SYNTHETIC_PRIVATE' not in caplog.text
    monkeypatch.setattr(chunker._splitter,'create_documents',lambda texts: [type('Part',(),
        {'page_content':'not original','metadata':{'start_index':0}})()])
    with pytest.raises(ChunkingError,match='^unmapped_fragment$'): chunker.split_document(doc)


def test_missing_config_no_implicit_fallback(tmp_path):
    with pytest.raises(ChunkingError,match='^invalid_chunking_config$'):
        DocumentChunker(Settings.from_dict(configuration(tmp_path)))


def test_ids_stable_version_bound_and_outputs_isolated(tmp_path):
    doc=document('# A\n正文 '+ 'x'*200+'\n')
    chunker=DocumentChunker(settings(tmp_path))
    first,_=chunker.split_document(doc); again,_=chunker.split_document(doc)
    assert [c.to_dict() for c in first]==[c.to_dict() for c in again]
    first[0].metadata['contexts'].clear()
    fresh,_=chunker.split_document(doc)
    assert [c.to_dict() for c in fresh]==[c.to_dict() for c in again]
    revised,_=chunker.split_document(document(doc.text+'新内容'))
    assert {c.id for c in again}.isdisjoint(c.id for c in revised)
