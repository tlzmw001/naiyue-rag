"""YAML and Loader -> native splitter -> public source-bound Chunk."""
import json
from pathlib import Path

from naiyue_rag import MarkdownLoader, DocumentChunker
from naiyue_rag.core.settings import load_settings
from test_settings import configuration, write_settings
from test_document_chunker import assert_bound, offline


def test_yaml_values_reach_real_splitter_and_loader(tmp_path,monkeypatch):
    root=tmp_path/'knowledge';root.mkdir()
    (root/'L1_A.md').write_text('# 模块\n\n'+'说明内容。'*100)
    raw=configuration(tmp_path);raw['ingestion']={'chunk_size':73,'chunk_overlap':11}
    config=load_settings(write_settings(tmp_path,raw))
    chunker=DocumentChunker(config.ingestion);calls=[];original=chunker._splitter.create_documents
    def observe(texts):calls.extend(texts);return original(texts)
    monkeypatch.setattr(chunker._splitter,'create_documents',observe)
    docs=MarkdownLoader(root,'kb',4096).load_all()
    chunks,_=chunker.split_document(docs[0])
    assert calls and chunker._splitter._chunk_size==73 and chunker._splitter._chunk_overlap==11
    assert all(len(c.text)<=73 for c in chunks)
    assert_bound(docs[0],chunks)
    assert all(c.metadata['component_metadata']['chunk_size']==73 for c in chunks)
    assert all(c.metadata['component_metadata']['chunk_overlap']==11 for c in chunks)


def test_existing_structure_material_keeps_all_twelve_case_rows(tmp_path):
    raw=configuration(tmp_path);raw['ingestion']={'chunk_size':1000,'chunk_overlap':200}
    chunker=DocumentChunker(load_settings(write_settings(tmp_path,raw)).ingestion)
    root=Path(__file__).resolve().parents[1]/'examples/mock-v1/knowledge'
    docs=MarkdownLoader(root,'structure-kb',1_048_576).load_all()
    count=0
    for doc in docs:
        chunks,issues=chunker.split_document(doc);assert_bound(doc,chunks)
        if doc.metadata['source_path'].endswith('_测试用例.md'):
            expected=[line for line in doc.text.splitlines() if line.startswith('| TC-')]
            actual=[c.text for c in chunks if c.metadata['kind']=='test_case']
            assert actual==expected
            count+=len(actual)
    assert count==12
