"""Ordinary Markdown files, stable identities and observable read boundaries."""
import hashlib
import json
from pathlib import Path
import socket
import traceback

import pytest

from naiyue_rag import MarkdownLoader
from naiyue_rag.core.errors import LoadError
from naiyue_rag.core.types import Document


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)


def make_source(tmp_path, raw=b'# Heading\nBody\n', relative='L1/service.md'):
    root = tmp_path / 'knowledge'; path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    return root, path


@pytest.mark.parametrize('raw,starts', [
    (b'', []), (b'A', [0]), (b'A\nB\n', [0,2]),
    (b'A\r\nB\r\n', [0,3]), (b'A\rB\r', [0,2]),
    (b'A\r\nB\nC\rD', [0,3,5,7]), ('\ufeff# 中文\r\n正文'.encode(), [0,7]),
])
def test_raw_bytes_text_hash_and_actual_line_starts(tmp_path, raw, starts):
    root, path = make_source(tmp_path, raw)
    doc = MarkdownLoader(root, 'kb-test', 4096).load('L1/service.md')
    assert isinstance(doc, Document) and doc.text.encode('utf-8') == raw
    assert doc.metadata == {'knowledge_base_id':'kb-test','source_path':'L1/service.md',
                            'source_sha256':hashlib.sha256(raw).hexdigest(),
                            'size_bytes':len(raw), 'line_starts':starts}
    identity_bytes = json.dumps(['kb-test','L1/service.md'],ensure_ascii=False,separators=(',',':')).encode()
    assert doc.id == 'doc-' + hashlib.sha256(identity_bytes).hexdigest()
    assert Document.from_dict(doc.to_dict()).to_dict() == doc.to_dict()
    assert path.read_bytes() == raw


def test_update_retains_id_and_changes_version(tmp_path):
    root, path = make_source(tmp_path)
    loader = MarkdownLoader(root, 'kb-test', 4096)
    before = loader.load('L1/service.md'); repeated = loader.load('L1/service.md')
    assert repeated.to_dict() == before.to_dict()
    path.write_bytes(b'# Revised\nNew boundary\n')
    after = loader.load('L1/service.md')
    assert before.id == after.id
    assert before.metadata['source_sha256'] != after.metadata['source_sha256']
    assert before.text != after.text


def test_root_move_is_stable_but_path_or_library_change_is_new_id(tmp_path):
    first = tmp_path / 'first'; second = tmp_path / 'second'
    first.mkdir(); second.mkdir()
    (first / 'a.md').write_bytes(b'unchanged'); (second / 'a.md').write_bytes(b'unchanged')
    a = MarkdownLoader(first, 'kb-test', 4096).load('a.md')
    b = MarkdownLoader(second, 'kb-test', 4096).load('a.md')
    assert a.id == b.id and a.metadata['source_sha256'] == b.metadata['source_sha256']
    (second / 'b.md').write_bytes(b'unchanged')
    renamed = MarkdownLoader(second, 'kb-test', 4096).load('b.md')
    other_library = MarkdownLoader(second, 'kb-other', 4096).load('a.md')
    assert len({a.id, renamed.id, other_library.id}) == 3
    assert renamed.metadata['source_sha256'] == a.metadata['source_sha256']


def test_directory_sorted_and_not_content_deduplicated(tmp_path):
    root = tmp_path / 'knowledge'; root.mkdir()
    (root / 'b.MD').write_bytes(b'same'); (root / 'a.md').write_bytes(b'same')
    (root / 'notes.txt').write_text('not Markdown')
    docs = MarkdownLoader(root, 'kb-test', 4096).load_all()
    assert [d.metadata['source_path'] for d in docs] == ['a.md','b.MD']
    assert docs[0].id != docs[1].id
    assert docs[0].metadata['source_sha256'] == docs[1].metadata['source_sha256']
    assert sorted(p.name for p in root.iterdir()) == ['a.md','b.MD','notes.txt']


def test_empty_directory_has_no_fabricated_document(tmp_path):
    assert MarkdownLoader(tmp_path, 'kb-test', 4096).load_all() == []


@pytest.mark.parametrize('key,value', [
    ('root',None), ('root',True), ('root','missing'),
    ('knowledge_base_id',''), ('knowledge_base_id',None), ('knowledge_base_id','\ud800'),
    ('max_file_bytes',True), ('max_file_bytes',0), ('max_file_bytes',-1), ('max_file_bytes','10'),
])
def test_invalid_constructor_configuration(tmp_path, key, value):
    args = {'root':tmp_path, 'knowledge_base_id':'kb-test', 'max_file_bytes':4096}
    args[key] = tmp_path / 'missing' if key == 'root' and value == 'missing' else value
    with pytest.raises(LoadError, match='^invalid_loader_config$'):
        MarkdownLoader(args['root'],args['knowledge_base_id'],args['max_file_bytes'])


@pytest.mark.parametrize('relative', [None, '', '/outside.md', '../outside.md', 'L1/../service.md',
                                      '\x00.md', '\ud800.md'])
def test_invalid_or_escaping_paths(tmp_path, relative):
    loader = MarkdownLoader(tmp_path, 'kb-test', 4096)
    with pytest.raises(LoadError, match='^invalid_source_path$'): loader.load(relative)


@pytest.mark.parametrize('relative', ['notes.txt','document.pdf'])
def test_unsupported_format_not_read(tmp_path, relative, monkeypatch):
    path = tmp_path / relative; path.write_text('content')
    loader = MarkdownLoader(tmp_path, 'kb-test', 4096)
    def forbid(*args, **kwargs): raise AssertionError('must not read')
    monkeypatch.setattr(Path, 'open', forbid)
    with pytest.raises(LoadError, match='^unsupported_source$'): loader.load(relative)


@pytest.mark.parametrize('mode,code', [('missing','source_read_failed'),('directory','source_read_failed'),
                                      ('encoding','invalid_source_encoding'),('size','source_too_large')])
def test_file_boundary_failures(tmp_path, mode, code):
    path = tmp_path / 'a.md'
    if mode == 'directory': path.mkdir()
    elif mode == 'encoding': path.write_bytes(b'\xff')
    elif mode == 'size': path.write_bytes(b'12345')
    loader = MarkdownLoader(tmp_path, 'kb-test', 4)
    with pytest.raises(LoadError, match=f'^{code}$'): loader.load('a.md')


def test_byte_limit_inclusive_and_read_uses_limit_plus_one(tmp_path, monkeypatch):
    (tmp_path / 'a.md').write_bytes(b'1234')
    loader = MarkdownLoader(tmp_path, 'kb-test', 4)
    assert loader.load('a.md').text == '1234'
    original = Path.open; sizes = []
    class ObservedReader:
        def __init__(self, handle): self.handle = handle
        def __enter__(self): return self
        def __exit__(self, *args): self.handle.close(); return False
        def read(self, size): sizes.append(size); return self.handle.read(size)
    monkeypatch.setattr(Path,'open',lambda self,*args,**kwargs:ObservedReader(original(self,*args,**kwargs)))
    assert loader.load('a.md').text == '1234'
    assert sizes == [5]


def test_unrepresentable_read_limit_still_has_observable_error(tmp_path, caplog):
    (tmp_path / 'a.md').write_bytes(b'A')
    loader = MarkdownLoader(tmp_path, 'kb-test', 2**100)
    with pytest.raises(LoadError, match='^source_read_failed$'): loader.load('a.md')
    assert 'stage=load code=source_read_failed' in caplog.text


@pytest.mark.parametrize('kind', ['file_inside','file_outside','directory'])
def test_symlinks_are_explicitly_rejected(tmp_path, kind):
    root = tmp_path / 'knowledge'; root.mkdir()
    target = root / 'original.md' if kind == 'file_inside' else tmp_path / 'outside.md'
    target.write_text('original')
    if kind == 'directory':
        (root / 'alias').symlink_to(tmp_path, target_is_directory=True)
        loader = MarkdownLoader(root, 'kb-test', 4096)
        with pytest.raises(LoadError, match='^invalid_source_path$'): loader.load_all()
    else:
        (root / 'alias.md').symlink_to(target)
        with pytest.raises(LoadError, match='^invalid_source_path$'):
            MarkdownLoader(root, 'kb-test', 4096).load('alias.md')


def test_single_read_produces_text_and_hash_from_same_bytes(tmp_path, monkeypatch):
    path = tmp_path / 'a.md'; path.write_bytes(b'first')
    loader = MarkdownLoader(tmp_path,'kb-test',4096); original = Path.open; reads = []
    class ChangingReader:
        def __enter__(self): self.handle = original(path,'rb'); return self
        def __exit__(self,*args): self.handle.close(); return False
        def read(self,size):
            reads.append(size); raw = self.handle.read(size)
            with original(path,'wb') as writer: writer.write(b'second')
            return raw
    monkeypatch.setattr(Path,'open',lambda *args,**kwargs:ChangingReader())
    doc = loader.load('a.md')
    assert doc.text == 'first' and doc.metadata['source_sha256'] == hashlib.sha256(b'first').hexdigest()
    assert len(reads) == 1


def test_read_failure_safe_and_observable(tmp_path, monkeypatch, caplog):
    path = tmp_path / 'SYNTHETIC_PRIVATE_PATH.md'; path.write_text('SYNTHETIC_PRIVATE_BODY')
    loader = MarkdownLoader(tmp_path,'kb-test',4096)
    def fail(*args,**kwargs): raise PermissionError('SYNTHETIC_PRIVATE_EXCEPTION')
    monkeypatch.setattr(Path,'open',fail)
    with pytest.raises(LoadError, match='^source_read_failed$') as caught: loader.load(path.name)
    visible = caplog.text + ''.join(traceback.format_exception(caught.value))
    assert 'stage=load code=source_read_failed' in visible
    for sentinel in ['SYNTHETIC_PRIVATE_PATH','SYNTHETIC_PRIVATE_BODY','SYNTHETIC_PRIVATE_EXCEPTION']:
        assert sentinel not in visible


def test_scan_failure_is_not_an_empty_success(tmp_path, monkeypatch, caplog):
    import naiyue_rag.ingestion.markdown_loader as module
    loader = MarkdownLoader(tmp_path,'kb-test',4096)
    def fail_walk(*args,**kwargs):
        kwargs['onerror'](PermissionError('SYNTHETIC_SCAN_PRIVATE'))
        return iter(())
    monkeypatch.setattr(module.os,'walk',fail_walk)
    with pytest.raises(LoadError, match='^source_scan_failed$'): loader.load_all()
    assert 'stage=load code=source_scan_failed' in caplog.text
    assert 'SYNTHETIC_SCAN_PRIVATE' not in caplog.text


def test_batch_failure_raises_instead_of_returning_partial_list(tmp_path):
    (tmp_path / 'a.md').write_text('valid'); (tmp_path / 'b.md').write_bytes(b'\xff')
    with pytest.raises(LoadError, match='^invalid_source_encoding$'):
        MarkdownLoader(tmp_path,'kb-test',4096).load_all()
