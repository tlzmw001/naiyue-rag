"""Audit exact wheel/sdist members before considering any publication."""
from email.parser import Parser
import hashlib
import argparse
from packaging.version import Version
import json
from pathlib import Path,PurePosixPath
import sys
import tarfile
import zipfile

HISTORICAL={'a2_snapshot.py','bootstrap.py','chroma_store.py','retrieval.py','tracing.py'}
RESOURCES={'naiyue_rag/resources/config.yaml','naiyue_rag/resources/models.json'}


def audit(path,expected_version=None):
    if path.suffix=='.whl':
        with zipfile.ZipFile(path) as archive:
            names=set(archive.namelist())
            info=[n for n in names if n.endswith('.dist-info/METADATA')];assert len(info)==1
            metadata=Parser().parsestr(archive.read(info[0]).decode())
            version=metadata['Version']
            assert metadata['Name']=='naiyue-rag' and version and str(Version(version))==version
            if expected_version is not None:assert version==expected_version
            assert len(metadata.get_all('Requires-Dist'))>=25
            entry=[n for n in names if n.endswith('.dist-info/entry_points.txt')]
            assert len(entry)==1 and 'nyr = naiyue_rag.cli:main' in archive.read(entry[0]).decode()
            assert RESOURCES<=names
            for name in names:
                p=PurePosixPath(name)
                assert '..' not in p.parts and not p.is_absolute() and '\\' not in name and ':' not in name
                assert name.startswith('naiyue_rag/') or '.dist-info/' in name
                if name.startswith('naiyue_rag/'):
                    assert name.endswith('.py') or name in RESOURCES,name
                    assert not (p.parent==PurePosixPath('naiyue_rag') and p.name in HISTORICAL),name
            assert 'naiyue_rag/__main__.py' in names and 'naiyue_rag/cli.py' in names
    else:
        with tarfile.open(path,'r:gz') as archive:
            members=archive.getmembers();assert not any(m.issym() or m.islnk() for m in members)
            assert all(not PurePosixPath(m.name).is_absolute() and '..' not in PurePosixPath(m.name).parts and '\\' not in m.name for m in members)
            names={str(PurePosixPath(m.name).relative_to(PurePosixPath(m.name).parts[0])) for m in members if m.isfile()}
            assert RESOURCES<=names
            assert {'pyproject.toml','packaging_support.py','README.md'}<=names
            for name in names:
                p=PurePosixPath(name)
                assert '..' not in p.parts and not p.is_absolute() and '\\' not in name and ':' not in name
                assert p.parts[0] not in {'tests','experiments','data','research','examples','scripts','docs','.github'}
                assert not p.name.startswith('.env')
                assert not (p.parent==PurePosixPath('naiyue_rag') and p.name in HISTORICAL),name
    return {'version':version if path.suffix=='.whl' else expected_version,'artifact':path.name,'files':len(names),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-version');parser.add_argument('archives',nargs='+',type=Path)
    args=parser.parse_args()
    for path in args.archives:print(json.dumps(audit(path,args.expected_version),ensure_ascii=False))
