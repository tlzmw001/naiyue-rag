"""Directory consumer, public Document contracts and untouched historical assets."""
import hashlib
import json
from pathlib import Path
import socket

import pytest

from naiyue_rag import MarkdownLoader
from naiyue_rag.core.types import Document
from experiments.markdown_probe import load_sources

MOCK = Path(__file__).resolve().parents[1] / 'examples/mock-v1'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args,**kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket,'connect',forbid)
    monkeypatch.setattr(socket.socket,'connect_ex',forbid)


def test_ordinary_markdown_without_manifest_consumes_public_document(tmp_path, monkeypatch):
    import naiyue_rag.ingestion.markdown_loader as module
    (tmp_path / 'plain.md').write_text('# 普通知识\n\n业务边界\n')
    original = module.Document; observed = []
    def observe(*args,**kwargs):
        value = original(*args,**kwargs); observed.append(value); return value
    monkeypatch.setattr(module,'Document',observe)
    docs = MarkdownLoader(tmp_path,'ordinary-kb',4096).load_all()
    assert len(docs) == len(observed) == 1 and docs[0] is observed[0]
    assert isinstance(docs[0],Document) and docs[0].text == '# 普通知识\n\n业务边界\n'
    assert not (tmp_path / 'manifest.json').exists()
    assert 'synthetic' not in docs[0].metadata
    assert Document.from_dict(json.loads(json.dumps(docs[0].to_dict(),ensure_ascii=False))).to_dict() == docs[0].to_dict()


def test_real_mock_structure_matches_old_bytes_and_line_locations_without_manifest():
    old = load_sources(MOCK)
    loader = MarkdownLoader(MOCK / 'knowledge','structure-fixture',1_048_576)
    docs = loader.load_all(); by_path = {doc.metadata['source_path']:doc for doc in docs}
    assert len(docs) == len(old) == 12
    for source in old:
        doc = by_path[source['relative_path']]
        assert doc.text == source['text']
        assert doc.metadata['source_sha256'] == source['source_sha256']
        assert doc.metadata['line_starts'] == source['line_starts']
        assert doc.id != source['document_id']
    assert {row['document_id'] for row in load_sources(MOCK)} == {row['document_id'] for row in old}


def test_complete_case_row_and_actual_position_preserved(tmp_path):
    root = tmp_path / 'knowledge'; root.mkdir()
    row = '| TC-01 | 正常下发 | 开关开启 | 调用接口<br>检查日志 | 字段符合要求 |'
    text = '# 用例\r\n\r\n## 维度1\r\n> 来源：L2 §2.1（手写L999）\r\n' + row + '\r\n'
    (root / 'case.md').write_bytes(text.encode())
    doc = MarkdownLoader(root,'kb-test',4096).load_all()[0]
    assert doc.text == text and row in doc.text
    start = doc.metadata['line_starts'][4]
    assert doc.text[start:start+len(row)] == row
    assert doc.metadata['source_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert 'L999' in doc.text  # kept as source text, never used to compute line offsets


def test_nested_directory_consumer_calls_loader_in_sorted_order(tmp_path, monkeypatch):
    (tmp_path / 'L2').mkdir(); (tmp_path / 'L1').mkdir()
    (tmp_path / 'L2/b.md').write_text('second'); (tmp_path / 'L1/a.md').write_text('first')
    loader = MarkdownLoader(tmp_path,'kb-test',4096); original = loader.load; calls = []
    def observe(relative): calls.append(str(relative)); return original(relative)
    monkeypatch.setattr(loader,'load',observe)
    docs = loader.load_all()
    assert calls == ['L1/a.md','L2/b.md']
    assert [doc.metadata['source_path'] for doc in docs] == calls


def test_exported_document_mutation_cannot_change_future_read(tmp_path):
    (tmp_path / 'a.md').write_bytes(b'A\nB\n')
    loader = MarkdownLoader(tmp_path,'kb-test',4096)
    first = loader.load('a.md'); exposed = first.to_dict(); exposed['metadata']['line_starts'].clear()
    assert first.metadata['line_starts'] == [0,2]
    first.metadata['line_starts'].clear(); first.text = 'caller change'
    second = loader.load('a.md')
    assert second.text == 'A\nB\n' and second.metadata['line_starts'] == [0,2]
