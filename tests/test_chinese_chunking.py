"""Chinese literal boundaries, source preservation and policy migration."""
import json
from pathlib import Path
import pytest
from naiyue_rag import DocumentChunker,IngestionSettings
from naiyue_rag.storage import IndexBundle
from test_document_chunker import document,assert_bound,HEADER,SEP,ROW,offline

TEXT='开关开启时检查阈值0.5。失败时保留错误码，成功时继续下一步。字段cvr_ltv保持原样，禁止改写TC-01。'


def test_new_tasks_default_to_chinese_policy_but_saved_settings_remain_legacy():
    settings=IngestionSettings(24,0)
    assert settings.chunking_policy=='markdown-source-zh-v2'
    assert settings.to_dict()['chunking_policy']=='markdown-source-zh-v2'
    assert IngestionSettings.from_dict(settings.to_dict())==settings
    assert IngestionSettings.from_dict(dict(chunk_size=24,chunk_overlap=0)).chunking_policy=='markdown-source-v1'


@pytest.mark.parametrize('newline',['\n','\r\n','\r'])
@pytest.mark.parametrize('overlap',[0,5])
def test_chinese_and_mixed_prose_has_real_spans_and_complete_punctuation(newline,overlap):
    text=('# 模块\n\n'+TEXT+'\n\n'+TEXT).replace('\n',newline)
    doc=document(text)
    chunks,_=DocumentChunker(IngestionSettings(24,overlap)).split_document(doc)
    assert_bound(doc,chunks)
    bodies=[c for c in chunks if c.metadata['kind']=='text']
    covered=set()
    for chunk in bodies:
        assert len(chunk.text)<=24
        covered.update(range(chunk.start_offset,chunk.end_offset))
        profile=chunk.metadata['component_metadata']
        assert profile['policy']=='markdown-source-zh-v2' and profile['keep_separator']=='end'
        assert '。' in profile['separators'] and '，' in profile['separators']
    assert all(i in covered for i,c in enumerate(text) if i>=text.index(TEXT) and not c.isspace())


def test_sentence_marks_stay_with_previous_text_and_atomic_units_are_protected():
    doc=document(TEXT)
    chunks,_=DocumentChunker(IngestionSettings(24,0)).split_document(doc)
    assert [c.text for c in chunks]==['开关开启时检查阈值0.5。','失败时保留错误码，成功时继续下一步。','字段cvr_ltv保持原样，禁止改写TC-01。']
    source=document(f'# 测试用例\n{HEADER}\n{SEP}\n{ROW}\n\n```python\nx = "。 ，"\n```\n','L2/A_测试用例.md')
    chunks,_=DocumentChunker(IngestionSettings(12,0)).split_document(source)
    assert_bound(source,chunks)
    assert next(c for c in chunks if c.metadata['kind']=='test_case').text==ROW
    code=next(c for c in chunks if c.metadata['kind']=='code')
    assert 'x = "。 ，"' in code.text and code.metadata['oversize']


def test_frozen_v1_is_readable_and_cannot_be_reused_as_v2():
    from test_file_integrity import plan
    raw=json.loads((Path(__file__).parent/'fixtures/chunking-v1-bundle.json').read_text())['bundle']
    bundle=IndexBundle.from_dict(raw)
    assert bundle.to_dict()==raw
    assert not plan(bundle,bundle.documents,ingestion_settings=IngestionSettings(40,10)).reuse_active
    assert plan(bundle,bundle.documents,ingestion_settings=IngestionSettings(40,10,chunking_policy='markdown-source-v1')).reuse_active
