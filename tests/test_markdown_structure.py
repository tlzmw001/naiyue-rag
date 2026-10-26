"""Installed Markdown parser structure mapped to untouched source ranges."""
import pytest

from naiyue_rag.ingestion.markdown_structure import scan_document
from naiyue_rag.core.errors import ChunkingError
from test_document_chunker import document, HEADER, SEP, ROW, offline


def test_structure_uses_headings_and_code_maps():
    text='# A\n\n### B\n\n```\n# inside code\n```\n\n正文\n'
    doc=document(text)
    blocks,issues=scan_document(doc)
    assert not issues
    assert any(b['kind']=='code' and '# inside code' in text[b['start']:b['end']] for b in blocks)
    assert all('# inside code' not in [c['text'] for c in b['contexts']] for b in blocks)
    assert any('### B' in [h['text'] for h in b['headings']] for b in blocks)
    covered=set()
    for b in blocks: covered.update(range(b['start'],b['end']))
    assert {i for i,c in enumerate(text) if not c.isspace()}<=covered


def test_case_classification_has_evidence_and_metadata_not_history_claim():
    doc=document(f'# 测试用例\n{HEADER}\n{SEP}\n{ROW}\n','L1/A_测试用例.md')
    blocks,_=scan_document(doc)
    case=next(b for b in blocks if b['kind']=='test_case')
    assert case['classification']['basis']=='filename_suffix'
    assert case['classification']['kind']=='test_cases'
    assert 'historical' not in str(case['classification'])


def test_nested_code_is_protected():
    text='# A\n\n> ```\n> # inside\n> x\n> ```\n'
    blocks,_=scan_document(document(text))
    code=next(b for b in blocks if b['kind']=='code')
    assert '> # inside' in text[code['start']:code['end']]


def test_parser_failure_has_safe_code(monkeypatch,caplog):
    import naiyue_rag.ingestion.markdown_structure as module
    def fail(*args,**kwargs): raise RuntimeError('SYNTHETIC_PARSER_PRIVATE')
    monkeypatch.setattr(module.MarkdownIt,'parse',fail)
    with pytest.raises(ChunkingError,match='^structure_failed$'):
        scan_document(document('# A\n正文\n'))
    assert 'SYNTHETIC_PARSER_PRIVATE' not in caplog.text
