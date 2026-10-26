"""Offline scope, persistence, and CLI wiring for common evidence corpus."""

import importlib
import json
import shutil
import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbid(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbid)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid)


@pytest.fixture
def probe():
    return importlib.import_module('experiments.corpus_probe')


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_full_export_scoped_export_and_cli(probe, tmp_path, capsys):
    full = probe.run('examples/mock-v1', [], ['MOCK-TASK-004'], 4000, tmp_path)
    assert full['status'] == 'complete' and full['source_count'] == 11
    assert full['case_count'] == 12 and full['blocked_count'] == 0
    folder = Path(full['output_dir'])
    sources = lines(folder / 'sources.jsonl')
    units = lines(folder / 'units.jsonl')
    assert len(sources) == 11 and len(units) == full['unit_count']
    assert all(u['document_id'] != 'MOCK-TASK-004' for u in units)
    assert all('text' not in s and 'expected_pairs' not in s for s in sources)
    assert '0' in (folder / 'report.md').read_text()
    assert json.loads((folder / 'summary.json').read_text()) == full
    scoped = probe.run('examples/mock-v1', ['MOCK-CASE-001'], ['MOCK-TASK-004'], 4000, tmp_path)
    assert scoped['source_count'] == 1 and scoped['case_count'] == 7
    assert {u['document_id'] for u in lines(Path(scoped['output_dir']) / 'units.jsonl')} == {'MOCK-CASE-001'}
    assert scoped['output_dir'] != full['output_dir']
    args = ['--dataset', 'examples/mock-v1', '--exclude-document-id', 'MOCK-TASK-004',
            '--max-evidence-chars', '4000', '--output-root', str(tmp_path)]
    assert probe.main(args) == 0
    assert 'status=complete' in capsys.readouterr().out


def test_labels_and_tasks_do_not_change_corpus(probe, tmp_path):
    copied = tmp_path / 'dataset'
    shutil.copytree('examples/mock-v1', copied)
    before = probe.run(copied, [], ['MOCK-TASK-004'], 4000, tmp_path / 'runs')
    (copied / 'tasks.json').unlink()
    manifest = json.loads((copied / 'manifest.json').read_text())
    manifest['expected_pairs'] = [{'malicious': 'different answer'}]
    manifest['intentional_anomalies'] = []
    (copied / 'manifest.json').write_text(json.dumps(manifest))
    after = probe.run(copied, [], ['MOCK-TASK-004'], 4000, tmp_path / 'runs')
    assert lines(Path(before['output_dir']) / 'units.jsonl') == lines(Path(after['output_dir']) / 'units.jsonl')


@pytest.mark.parametrize('include,exclude,limit', [
    (['missing'], ['MOCK-TASK-004'], 4000), ([], ['missing'], 4000),
    (['MOCK-CASE-001'], ['MOCK-CASE-001'], 4000),
    ([], ['MOCK-TASK-004'], 0), ([], ['MOCK-TASK-004'], True),
    (['MOCK-CASE-001', 'MOCK-CASE-001'], ['MOCK-TASK-004'], 4000)])
def test_invalid_scope_and_limit(probe, tmp_path, include, exclude, limit):
    with pytest.raises(ValueError): probe.run('examples/mock-v1', include, exclude, limit, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_empty_scope_rejected(probe, tmp_path):
    sources = probe.load_sources('examples/mock-v1')
    with pytest.raises(ValueError, match='empty_scope'):
        probe.run('examples/mock-v1', [], [s['document_id'] for s in sources], 4000, tmp_path)


def test_blocked_budget_keeps_full_output_and_cli_failure(probe, tmp_path, capsys):
    result = probe.run('examples/mock-v1', [], ['MOCK-TASK-004'], 100, tmp_path)
    assert result['status'] == 'blocked' and result['blocked_count'] > 0
    units = lines(Path(result['output_dir']) / 'units.jsonl')
    case = next(u for u in units if u['case_id'] == 'TC-01')
    assert len(case['body']) == 571 and case['body'] in case['rendered_text']
    assert case['eligible'] is False
    args = ['--dataset', 'examples/mock-v1', '--exclude-document-id', 'MOCK-TASK-004',
            '--max-evidence-chars', '100', '--output-root', str(tmp_path)]
    assert probe.main(args) == 2
    assert 'status=blocked' in capsys.readouterr().out


@pytest.mark.parametrize('fault', ['missing', 'hash', 'path', 'utf8'])
def test_input_failures_observed(probe, tmp_path, fault):
    copied = tmp_path / 'dataset'
    shutil.copytree('examples/mock-v1', copied)
    manifest = json.loads((copied / 'manifest.json').read_text())
    doc = manifest['documents'][0]
    target = copied / doc['path']
    if fault == 'missing': target.unlink()
    if fault == 'hash': target.write_text('modified')
    if fault == 'path': doc['path'] = '../outside.md'
    if fault == 'utf8':
        import hashlib
        target.write_bytes(b'\xff')
        doc['sha256'] = hashlib.sha256(b'\xff').hexdigest()
    (copied / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError): probe.run(copied, [], ['MOCK-TASK-004'], 4000, tmp_path / 'runs')
    assert not (tmp_path / 'runs').exists()


def test_exclusion_happens_before_component(probe, tmp_path, monkeypatch):
    called = []
    original = probe.build_units
    def build(src, limit):
        assert src['document_id'] != 'MOCK-TASK-004'
        called.append(src['document_id'])
        return original(src, limit)
    monkeypatch.setattr(probe, 'build_units', build)
    result = probe.run('examples/mock-v1', ['MOCK-CASE-001'], ['MOCK-TASK-004'], 4000, tmp_path)
    assert result['status'] == 'complete' and called == ['MOCK-CASE-001']


def test_output_collision_preserves_existing_files(probe, tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'new_run_id', lambda: 'collision')
    folder = tmp_path / 'collision'
    folder.mkdir()
    marker = folder / 'report.md'
    marker.write_text('existing')
    with pytest.raises(ValueError, match='output_error'):
        probe.run('examples/mock-v1', [], ['MOCK-TASK-004'], 4000, tmp_path)
    assert marker.read_text() == 'existing'


def test_write_failure_has_no_completion_summary(probe, tmp_path, monkeypatch):
    original = Path.open
    def fail(path, *args, **kwargs):
        if path.name == 'units.jsonl': raise PermissionError('injected')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail)
    with pytest.raises(ValueError, match='output_error'):
        probe.run('examples/mock-v1', [], ['MOCK-TASK-004'], 4000, tmp_path)
    assert not list(tmp_path.rglob('summary.json'))


def test_cli_source_error_is_explicit(probe, tmp_path, capsys):
    args = ['--dataset', str(tmp_path / 'missing'), '--exclude-document-id', 'MOCK-TASK-004',
            '--max-evidence-chars', '4000', '--output-root', str(tmp_path)]
    assert probe.main(args) == 2
    assert 'source_error' in capsys.readouterr().err
