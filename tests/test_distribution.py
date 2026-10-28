"""Candidate package contract and deliberately limited Windows durability."""
from pathlib import Path
import tomllib
import pytest
from test_storage_bundle import storage_settings

ROOT=Path(__file__).resolve().parents[1]


def test_candidate_metadata_installs_all_supported_runtime_features():
    config=tomllib.loads((ROOT/'pyproject.toml').read_text())
    project=config['project'];deps=project['dependencies']
    assert project['name']=='naiyue-rag' and project['scripts']=={
        'nyr':'naiyue_rag.cli:main',
        'nyr-embedding-audit':'naiyue_rag.validation.local_embedding_audit:main',
    }
    assert project['requires-python']=='>=3.12,<3.13'
    for dep in ['openai==2.54.0','chromadb==1.5.9','bm25s==0.3.13','torch==2.14.1',
                'sentence-transformers==6.1.0','fastapi==0.162.0','uvicorn==0.54.0','PyYAML==6.0.3']:
        assert dep in deps
    assert not any('pytest' in dep or 'llama-index' in dep for dep in deps)
    assert not project.get('optional-dependencies')


def test_windows_directory_sync_checks_directory_without_posix_open(tmp_path,monkeypatch,caplog):
    import naiyue_rag.storage.bundle_store as module
    from naiyue_rag.storage.bundle_store import BundleStore
    from naiyue_rag.core.errors import StorageError
    settings=storage_settings(tmp_path)
    store=BundleStore(settings)
    monkeypatch.setattr(module.sys,'platform','win32')
    def unsupported(*args,**kwargs):raise AssertionError('Windows must not open a POSIX directory descriptor')
    monkeypatch.setattr(module.os,'open',unsupported)
    with caplog.at_level('INFO'):
        store._sync_directory(tmp_path)
    assert 'directory_sync_unavailable' in caplog.text
    with pytest.raises(StorageError):store._sync_directory(tmp_path/'absent')


def test_posix_directory_sync_failure_is_not_downgraded(tmp_path,monkeypatch):
    import naiyue_rag.storage.bundle_store as module
    from naiyue_rag.storage.bundle_store import BundleStore
    settings=storage_settings(tmp_path);store=BundleStore(settings)
    monkeypatch.setattr(module.sys,'platform','linux')
    def fail(fd):raise OSError('SYNTHETIC_SYNC_FAILURE')
    monkeypatch.setattr(module.os,'fsync',fail)
    with pytest.raises(OSError,match='SYNTHETIC_SYNC_FAILURE'):store._sync_directory(tmp_path)


def test_ci_selection_does_not_execute_unshipped_experiment_adapters():
    import ast
    import runpy
    selected=runpy.run_path(str(ROOT/'scripts/run_formal_tests.py'))['FORMAL']
    legacy={f'naiyue_rag.{name}' for name in ('a2_snapshot','bootstrap','chroma_store','retrieval','tracing')}
    for name in selected:
        source=(ROOT/'tests'/name).read_text(encoding='utf-8')
        assert 'naiyue_rag' in source, name
        tree=ast.parse(source)
        imports={node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)}
        assert not imports&legacy, name


def test_archive_audit_uses_posix_member_names_on_windows(tmp_path,monkeypatch):
    import io
    from pathlib import PureWindowsPath
    import runpy
    import tarfile
    archive=tmp_path/'candidate.tar.gz'
    with tarfile.open(archive,'w:gz') as stream:
        for name in ('pyproject.toml','packaging_support.py','README.md',
                     'naiyue_rag/resources/config.yaml','naiyue_rag/resources/models.json'):
            data=b'synthetic archive-path fixture';info=tarfile.TarInfo('candidate/'+name);info.size=len(data)
            stream.addfile(info,io.BytesIO(data))
    audit=runpy.run_path(str(ROOT/'scripts/inspect_distribution.py'))['audit']
    monkeypatch.setitem(audit.__globals__,'Path',PureWindowsPath)
    assert audit(archive)['files']==5
