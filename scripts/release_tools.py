"""Read-only release guards; publishing is exclusively the PyPA Actions job."""
import argparse
import ast
from email.parser import BytesParser
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tarfile
import time
import tomllib
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit
from urllib.request import urlopen
import zipfile
from packaging.version import Version

ROOT=Path(__file__).resolve().parents[1]


def canonical_version(value):
    if type(value) is not str or str(Version(value))!=value or Version(value).local is not None:
        raise ValueError('release_version_invalid')
    return value


def source_version(root=ROOT):
    try:
        tree=ast.parse((root/'naiyue_rag/_version.py').read_text(encoding='utf-8'))
        values=[ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and
                len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='__version__']
        if len(values)!=1:raise ValueError()
        return canonical_version(values[0])
    except Exception:raise ValueError('release_version_invalid') from None


def check_release(root,tag):
    if type(tag) is not str or re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',tag) is None:
        raise ValueError('release_tag_invalid')
    version=source_version(root)
    if tag!='v'+version:raise ValueError('release_version_mismatch')
    project=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']
    license=project.get('license');patterns=project.get('license-files')
    if type(license) is not str or not license.strip() or type(patterns) is not list or not patterns:
        raise ValueError('release_license_missing')
    for pattern in patterns:
        if type(pattern) is not str or Path(pattern).is_absolute() or '..' in Path(pattern).parts:
            raise ValueError('release_license_missing')
        matches=list(root.glob(pattern))
        if not matches or any(p.is_symlink() or not p.is_file() or p.stat().st_size==0 for p in matches):
            raise ValueError('release_license_missing')
    return version


def artifact_names(version):
    canonical_version(version)
    return {'version':version,'wheel':f'naiyue_rag-{version}-py3-none-any.whl','sdist':f'naiyue_rag-{version}.tar.gz'}


def release_artifacts(dist,version):
    names=artifact_names(version)
    try:
        paths=[dist/names[key] for key in ('wheel','sdist')]
        if dist.is_symlink() or {p.name for p in dist.iterdir()}!={p.name for p in paths} or \
                any(p.is_symlink() or not p.is_file() for p in paths):raise ValueError()
        with zipfile.ZipFile(paths[0]) as stream:
            files=[n for n in stream.namelist() if n.endswith('.dist-info/METADATA')]
            if len(files)!=1:raise ValueError()
            wheel=BytesParser().parsebytes(stream.read(files[0]))
        with tarfile.open(paths[1],'r:gz') as stream:
            member=stream.getmember(f'naiyue_rag-{version}/PKG-INFO')
            if not member.isfile():raise ValueError()
            with stream.extractfile(member) as handle:sdist=BytesParser().parsebytes(handle.read())
        for metadata in (wheel,sdist):
            if metadata['Name']!='naiyue-rag' or metadata['Version']!=version:raise ValueError()
        if sorted(wheel.get_all('Requires-Dist',[]))!=sorted(sdist.get_all('Requires-Dist',[])):raise ValueError()
        return names
    except Exception:raise ValueError('release_artifacts_invalid') from None


def check_registry(dist,version,body):
    names=release_artifacts(dist,version)
    try:
        if body['info']['name']!='naiyue-rag' or body['info']['version']!=version:raise ValueError()
        urls=body['urls'];expected={names[k] for k in ('wheel','sdist')}
        if len(urls)!=2 or {item['filename'] for item in urls}!=expected:raise ValueError()
        for item in urls:
            if item.get('yanked',False) or item['digests']['sha256']!=hashlib.sha256((dist/item['filename']).read_bytes()).hexdigest():
                raise ValueError()
    except Exception:raise ValueError('release_registry_mismatch') from None


def verify_index(dist,version,index_url,timeout):
    release_artifacts(dist,version)
    url=urlsplit(index_url)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or \
            not math.isfinite(timeout) or timeout<=0:raise ValueError('release_registry_invalid_request')
    deadline=time.monotonic()+timeout;code='release_registry_unavailable'
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError(code)
        try:
            with urlopen(index_url.rstrip('/')+'/naiyue-rag/'+version+'/json',timeout=min(20,remaining)) as response:
                raw=response.read(2097153)
            if len(raw)>2097152:raise ValueError('release_registry_mismatch')
            check_registry(dist,version,json.loads(raw));return
        except (HTTPError,URLError,OSError):code='release_registry_unavailable'
        except (ValueError,KeyError,TypeError):code='release_registry_mismatch'
        remaining=deadline-time.monotonic()
        if remaining>0:time.sleep(min(3,remaining))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    version=commands.add_parser('version');version.add_argument('--tag',default='');version.add_argument('--github-output',type=Path)
    artifacts=commands.add_parser('artifacts');artifacts.add_argument('--dist',type=Path,required=True)
    artifacts.add_argument('--version',required=True);artifacts.add_argument('--github-output',type=Path)
    verify=commands.add_parser('verify-index');verify.add_argument('--dist',type=Path,required=True);verify.add_argument('--version',required=True)
    verify.add_argument('--index-url',default='https://pypi.org/pypi');verify.add_argument('--timeout-seconds',type=float,default=180)
    args=parser.parse_args(argv)
    try:
        if args.command=='version':result=artifact_names(check_release(ROOT,args.tag) if args.tag else source_version())
        elif args.command=='artifacts':result=release_artifacts(args.dist,args.version)
        else:
            verify_index(args.dist,args.version,args.index_url,args.timeout_seconds);result={'status':'verified','version':args.version}
        output=getattr(args,'github_output',None)
        if output is not None:
            with output.open('a',encoding='utf-8') as stream:
                for name,value in result.items():stream.write(name+'='+value+'\n')
        print(json.dumps(result));return 0
    except Exception as error:
        allowed={'release_tag_invalid','release_version_invalid','release_version_mismatch','release_license_missing',
                 'release_artifacts_invalid','release_registry_invalid_request','release_registry_unavailable','release_registry_mismatch'}
        code=str(error) if type(error) is ValueError and str(error) in allowed else 'release_check_failed'
        print(json.dumps({'error':{'code':code}}),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
