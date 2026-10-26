"""Rule preparation preserves evidence and describes only observed metadata."""
import copy
import hashlib
import json

import pytest

from naiyue_rag.core.errors import PreparationError
from naiyue_rag.core.types import Chunk
from naiyue_rag.ingestion.chunk_preparation import ChunkRefiner, MetadataEnricher
from test_document_chunker import document, settings, assert_bound, offline
from naiyue_rag import DocumentChunker

HEADER='| 编号 | 用例标题 | 前置条件 | 测试步骤 | 预期结果 | 备注 |'
ROW='| A-1 | 正常下发 | 开关开启 | 发起请求<br>检查日志 | 成功 | 未改动历史行为 |'


def case_chunks(tmp_path, row=ROW):
    text='# L1: 新服务测试用例\n\n## 维度一\n\n'+HEADER+'\n| --- | --- | --- | --- | --- | --- |\n'+row+'\n'
    doc=document(text,'L2/L1_新服务_测试用例.md')
    chunks,_=DocumentChunker(settings(tmp_path)).split_document(doc)
    return doc,chunks


@pytest.mark.parametrize('mode',['raw','labeled_case'])
def test_view_preserves_raw_source_all_columns_and_serialization(tmp_path,mode):
    doc,chunks=case_chunks(tmp_path);before=[c.to_dict() for c in chunks]
    refined=ChunkRefiner().transform(doc,chunks,text_mode=mode)
    output=MetadataEnricher().transform(doc,refined)
    assert_bound(doc,output)
    assert [c.to_dict() for c in chunks]==before
    case=next(c for c in output if c.metadata['kind']=='test_case')
    view=case.metadata['retrieval_view']
    expected=ROW if mode=='raw' else '编号：A-1\n用例标题：正常下发\n前置条件：开关开启\n测试步骤：发起请求\n检查日志\n预期结果：成功\n备注：未改动历史行为'
    assert view['text']==expected
    assert view['text_mode']==mode and view['policy_id']=='markdown-retrieval-view-v1'
    assert view['text_sha256']==hashlib.sha256(expected.encode()).hexdigest()
    info=case.metadata['document_info']
    assert info['title']['value']=='L1: 新服务测试用例' and info['title']['basis']=='document_heading'
    assert info['directory_level']=='L2'
    assert info['declared_level']['value']=='L1' and info['declared_level']['status']=='consistent'
    assert case.metadata['document_classification']==chunks[-1].metadata['document_classification']
    restored=Chunk.from_dict(json.loads(json.dumps(case.to_dict(),ensure_ascii=False)))
    assert restored.to_dict()==case.to_dict()


@pytest.mark.parametrize('cell,expected',[
    ('x<BR/>y<br />z','x\ny\nz'),
    (r'x\<br>y',r'x\<br>y'),
    ('`<br>`<br>after','`<br>`<br>after'),
    ('x  <tag>keep</tag> <!-- comment -->','x  <tag>keep</tag> <!-- comment -->'),
    (r'公式 `x\|y` = 2',r'公式 `x\|y` = 2'),
    ('',''),
],ids=['br-variants','escaped-br','conservative-code','retain-html-spaces','escaped-pipe','empty-cell'])
def test_cell_conversion_is_conservative_and_lossless(tmp_path,cell,expected):
    row=ROW.replace('发起请求<br>检查日志',cell)
    doc,chunks=case_chunks(tmp_path,row)
    case=next(c for c in ChunkRefiner().transform(doc,chunks,text_mode='labeled_case')
              if c.metadata['kind']=='test_case')
    assert f'测试步骤：{expected}\n预期结果：' in case.metadata['retrieval_view']['text']
    assert case.text==row


def test_non_case_prose_code_and_tables_remain_exact(tmp_path):
    doc=document('# L0 系统\r\n\r\n正文  x<br>y <!--留-->\r\n\r\n~~~~py\r\n  x = "<br>"\r\n~~~~\r\n\r\n| 名称 | 值 |\r\n| --- | --- |\r\n| x | y |\r\n','L0/L0_系统.md')
    chunks,_=DocumentChunker(settings(tmp_path,1000,0)).split_document(doc)
    out=ChunkRefiner().transform(doc,chunks,text_mode='labeled_case')
    assert {c.metadata['kind'] for c in out}=={'text','code','table'}
    for raw,new in zip(chunks,out):
        assert raw.text==new.text==new.metadata['retrieval_view']['text']
        assert new.metadata['retrieval_view']['rules']==[]


@pytest.mark.parametrize('path,text,expected,directory,status',[
    ('L2/L2_A.md','# L1: A\n正文','', 'L2','conflict'),
    ('L0/L1/A.md','# L2: A\n正文','L2',None,'consistent'),
    ('other/A.md','没有标题\n正文','',None,'unknown'),
    ('L1/L1_A.md','# 没标级别的标题\n正文','L1','L1','consistent'),
],ids=['declaration-conflict','directory-conflict','unknown','filename-only'])
def test_level_claims_never_infer_relationships(tmp_path,path,text,expected,directory,status):
    doc=document(text,path);chunks,_=DocumentChunker(settings(tmp_path)).split_document(doc)
    out=MetadataEnricher().transform(doc,chunks)
    info=out[-1].metadata['document_info']
    assert info['directory_level']==directory
    assert info['declared_level']['status']==status
    assert info['declared_level']['value']==(expected or None)
    assert 'dependencies' not in info and 'validity' not in info
    if status=='unknown':
        assert info['title']=={'value':'A','basis':'filename','span':None}


@pytest.mark.parametrize('fault',['body','context','context-line','fields','columns','version','path','duplicate'])
@pytest.mark.parametrize('stage',['refiner','enricher'])
def test_forged_inputs_fail_explicitly_and_safely(tmp_path,fault,stage,caplog):
    doc,chunks=case_chunks(tmp_path);case=next(c for c in chunks if c.metadata['kind']=='test_case')
    if fault=='body': case.text='X'*len(case.text)
    elif fault=='context': case.metadata['contexts'][0]['text']='SYNTHETIC_PRIVATE'
    elif fault=='context-line': case.metadata['contexts'][0]['span']['line_start']=99
    elif fault=='fields': case.metadata['case_fields'][0]='SYNTHETIC_PRIVATE'
    elif fault=='columns': case.metadata['case_columns'][0]='SYNTHETIC_PRIVATE'
    elif fault=='version': case.metadata['source_sha256']='0'*64
    elif fault=='path': case.metadata['source_path']='SYNTHETIC_PRIVATE'
    else: chunks.append(copy.deepcopy(case))
    with pytest.raises(PreparationError,match='^invalid_preparation_input$'):
        if stage=='refiner': ChunkRefiner().transform(doc,chunks,text_mode='raw')
        else: MetadataEnricher().transform(doc,chunks)
    assert 'SYNTHETIC_PRIVATE' not in caplog.text
    assert 'code=invalid_preparation_input' in caplog.text


@pytest.mark.parametrize('mode',[None,'unknown',False,{'secret':'SYNTHETIC_PRIVATE'}])
def test_invalid_mode_never_falls_back(tmp_path,mode,caplog):
    doc,chunks=case_chunks(tmp_path)
    with pytest.raises(PreparationError,match='^invalid_text_mode$'):
        ChunkRefiner().transform(doc,chunks,text_mode=mode)
    assert 'SYNTHETIC_PRIVATE' not in caplog.text


def test_repeat_preparation_is_stable_inputs_and_outputs_are_isolated(tmp_path):
    doc,chunks=case_chunks(tmp_path);refiner=ChunkRefiner();enricher=MetadataEnricher()
    first=enricher.transform(doc,refiner.transform(doc,chunks,text_mode='labeled_case'))
    again=enricher.transform(doc,refiner.transform(doc,first,text_mode='labeled_case'))
    assert [c.to_dict() for c in first]==[c.to_dict() for c in again]
    first[0].metadata['document_info']['title']['value']='changed'
    assert again[0].metadata['document_info']['title']['value']!='changed'
    raw=refiner.transform(doc,chunks,text_mode='raw')
    labeled=refiner.transform(doc,chunks,text_mode='labeled_case')
    r=raw[-1].metadata['retrieval_view'];l=labeled[-1].metadata['retrieval_view']
    assert r['input_sha256']==l['input_sha256'] and r['text_sha256']!=l['text_sha256']
    assert raw[-1].id==labeled[-1].id


def test_case_source_update_changes_view_input_fingerprint(tmp_path):
    doc,chunks=case_chunks(tmp_path);out=ChunkRefiner().transform(doc,chunks,text_mode='raw')
    updated,revised=case_chunks(tmp_path,ROW.replace('成功','失败'))
    newer=ChunkRefiner().transform(updated,revised,text_mode='raw')
    assert out[-1].metadata['retrieval_view']['input_sha256']!=newer[-1].metadata['retrieval_view']['input_sha256']
