"""Release gates use synthetic repositories/artifacts; never upload anything."""
import hashlib
import io
import json
from pathlib import Path
import runpy
import tarfile
import zipfile
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]


def tools():return runpy.run_path(str(ROOT/'scripts/release_tools.py'))


def project(root,version='1.2.3',licensed=True):
    package=root/'naiyue_rag';package.mkdir()
    (package/'_version.py').write_text(f'__version__={version!r}\n',encoding='utf-8')
    license_line='license="MIT"\nlicense-files=["LICENSE"]\n' if licensed else ''
    (root/'pyproject.toml').write_text('[project]\nname="naiyue-rag"\n'+license_line,encoding='utf-8')
    if licensed:(root/'LICENSE').write_text('Synthetic license fixture only.',encoding='utf-8')
    return root


def artifacts(root,version='1.2.3',*,sdist_version=None):
    root.mkdir(exist_ok=True);wheel=root/f'naiyue_rag-{version}-py3-none-any.whl';sdist=root/f'naiyue_rag-{version}.tar.gz'
    metadata=f'Metadata-Version: 2.4\nName: naiyue-rag\nVersion: {version}\n'
    with zipfile.ZipFile(wheel,'w') as stream:stream.writestr(f'naiyue_rag-{version}.dist-info/METADATA',metadata)
    raw=metadata.replace(f'Version: {version}\n',f'Version: {sdist_version or version}\n').encode()
    with tarfile.open(sdist,'w:gz') as stream:
        info=tarfile.TarInfo(f'naiyue_rag-{version}/PKG-INFO');info.size=len(raw);stream.addfile(info,io.BytesIO(raw))
    return wheel,sdist


def test_single_source_version_and_release_match(tmp_path):
    module=tools();root=project(tmp_path)
    assert module['source_version'](root)=='1.2.3'
    assert module['check_release'](root,'v1.2.3')=='1.2.3'


@pytest.mark.parametrize('tag',['1.2.3','v1.2.4','v01.2.3','v1.2.3.dev0','v1.2.3rc1','v1.2.3\n','v$(id)'])
def test_tag_must_be_exact_stable_version(tmp_path,tag):
    root=project(tmp_path)
    with pytest.raises(ValueError):tools()['check_release'](root,tag)


def test_license_is_required_only_for_real_release(tmp_path):
    root=project(tmp_path,licensed=False);module=tools()
    assert module['source_version'](root)=='1.2.3'
    with pytest.raises(ValueError,match='release_license_missing'):module['check_release'](root,'v1.2.3')


def test_dev_candidate_cannot_be_published_as_a_stable_tag(tmp_path):
    with pytest.raises(ValueError):tools()['check_release'](project(tmp_path,'1.2.3.dev0'),'v1.2.3')


def test_artifact_pair_has_matching_version_and_exact_names(tmp_path):
    wheel,sdist=artifacts(tmp_path)
    result=tools()['release_artifacts'](tmp_path,'1.2.3')
    assert result=={'wheel':wheel.name,'sdist':sdist.name,'version':'1.2.3'}


@pytest.mark.parametrize('fault',['extra','missing','mismatch','symlink'])
def test_bad_artifact_pair_fails_before_upload(tmp_path,fault):
    wheel,sdist=artifacts(tmp_path,sdist_version='9.9.9' if fault=='mismatch' else None)
    if fault=='extra':(tmp_path/'unexpected.txt').write_text('unrelated')
    elif fault=='missing':sdist.unlink()
    elif fault=='symlink':
        stored=tmp_path.parent/(tmp_path.name+'-wheel');wheel.rename(stored);wheel.symlink_to(stored)
    with pytest.raises(ValueError):tools()['release_artifacts'](tmp_path,'1.2.3')


def test_registry_hashes_are_exact_and_not_just_a_version_match(tmp_path):
    wheel,sdist=artifacts(tmp_path);module=tools()
    body={'info':{'name':'naiyue-rag','version':'1.2.3'},'urls':[
        {'filename':p.name,'digests':{'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}} for p in (wheel,sdist)]}
    module['check_registry'](tmp_path,'1.2.3',body)
    body['urls'][0]['digests']['sha256']='0'*64
    with pytest.raises(ValueError,match='release_registry_mismatch'):module['check_registry'](tmp_path,'1.2.3',body)


def load_workflow(name):return yaml.load((ROOT/'.github/workflows'/name).read_text(),Loader=yaml.BaseLoader)


def test_tag_is_the_only_publish_trigger_and_oidc_is_job_scoped():
    flow=load_workflow('publish-pypi.yml')
    assert set(flow['on'])=={'push'} and flow['on']['push']['tags']==['v*']
    assert 'id-token' not in flow['permissions']
    upload=flow['jobs']['publish'];assert upload['permissions']['id-token']=='write'
    assert upload['environment']['name']=='pypi' and upload['needs']==['validate']
    actions=[step.get('uses','') for step in upload['steps']]
    assert any(name.startswith('pypa/gh-action-pypi-publish@') for name in actions)
    assert not any(name.startswith('actions/checkout@') for name in actions)
    assert not any('run' in step for step in upload['steps'])
    assert 'guard' in flow['jobs']['validate']['needs']
    assert flow['jobs']['verify-public']['needs']==['validate','publish']


def test_all_platforms_install_the_same_built_artifacts():
    flow=load_workflow('package-validation.yml');jobs=flow['jobs']
    assert 'workflow_call' in flow['on'] and 'branches' in flow['on']['push']
    install=jobs['installed-artifact'];assert install['needs']==['build']
    assert install['strategy']['matrix']['os']==['ubuntu-24.04','windows-2022','macos-15']
    assert any(step.get('uses','').startswith('actions/download-artifact@') for step in install['steps'])
    assert not any('python -m build' in step.get('run','') for step in install['steps'])
    assert jobs['formal-regression']['needs']==['build']
    assert any(step.get('uses','').startswith('actions/download-artifact@') for step in jobs['formal-regression']['steps'])
    assert 'skip-existing' not in (ROOT/'.github/workflows/publish-pypi.yml').read_text()
    assert '0.1.0.dev0' not in (ROOT/'.github/workflows/package-validation.yml').read_text()


def registry_body(paths,version='1.2.3'):
    return {'info':{'name':'naiyue-rag','version':version},'urls':[
        {'filename':p.name,'digests':{'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}} for p in paths]}


def test_registry_verification_reads_public_metadata_and_retries_visibility(tmp_path,monkeypatch):
    from urllib.error import HTTPError
    from types import SimpleNamespace
    module=tools();clock=[0];calls=[];body=registry_body(artifacts(tmp_path))
    def read(url,timeout):
        calls.append(url)
        if len(calls)==1:raise HTTPError(url,404,'not visible',{},None)
        return io.BytesIO(json.dumps(body).encode())
    namespace=module['verify_index'].__globals__
    monkeypatch.setitem(namespace,'urlopen',read)
    monkeypatch.setitem(namespace,'time',SimpleNamespace(monotonic=lambda:clock[0],sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)))
    module['verify_index'](tmp_path,'1.2.3','https://pypi.org/pypi',10)
    assert calls==['https://pypi.org/pypi/naiyue-rag/1.2.3/json']*2 and clock[0]>0


def test_registry_verification_times_out_safely(tmp_path,monkeypatch):
    from urllib.error import URLError
    from types import SimpleNamespace
    module=tools();artifacts(tmp_path);clock=[0]
    def unavailable(*args,**kwargs):raise URLError('SYNTHETIC_PRIVATE_NETWORK_DETAIL')
    namespace=module['verify_index'].__globals__
    monkeypatch.setitem(namespace,'urlopen',unavailable)
    monkeypatch.setitem(namespace,'time',SimpleNamespace(monotonic=lambda:clock[0],sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)))
    with pytest.raises(ValueError,match='^release_registry_unavailable$'):
        module['verify_index'](tmp_path,'1.2.3','https://pypi.org/pypi',5)


def test_workflow_output_is_written_only_after_release_guard(tmp_path,monkeypatch,capsys):
    root=project(tmp_path);module=tools();output=tmp_path/'output'
    monkeypatch.setitem(module['main'].__globals__,'ROOT',root)
    assert module['main'](['version','--tag','v1.2.4','--github-output',str(output)])==2
    assert not output.exists() and 'release_version_mismatch' in capsys.readouterr().err
    assert module['main'](['version','--tag','v1.2.3','--github-output',str(output)])==0
    assert 'version=1.2.3\n' in output.read_text()


def test_auditor_supports_future_versions_but_requires_the_requested_one(tmp_path):
    from email.parser import Parser
    audit=runpy.run_path(str(ROOT/'scripts/inspect_distribution.py'))['audit']
    wheel=tmp_path/'naiyue_rag-1.2.3-py3-none-any.whl'
    metadata='Metadata-Version: 2.4\nName: naiyue-rag\nVersion: 1.2.3\n'+''.join(f'Requires-Dist: synthetic-dep-{i}\n' for i in range(25))
    with zipfile.ZipFile(wheel,'w') as stream:
        stream.writestr('naiyue_rag-1.2.3.dist-info/METADATA',metadata)
        stream.writestr('naiyue_rag-1.2.3.dist-info/entry_points.txt','[console_scripts]\nnyr = naiyue_rag.cli:main\n')
        for name in ('__main__.py','cli.py','resources/config.yaml','resources/models.json'):
            stream.writestr('naiyue_rag/'+name,'synthetic archive fixture')
    assert audit(wheel,'1.2.3')['version']=='1.2.3'
    with pytest.raises(AssertionError):audit(wheel,'1.2.4')
