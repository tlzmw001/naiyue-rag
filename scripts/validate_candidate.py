"""Cross-platform clean wheel install, then real CLI smoke away from source cwd."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import venv
from packaging.version import Version
from inspect_distribution import audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--wheel',type=Path);source.add_argument('--package-version')
    parser.add_argument('--expected-version');parser.add_argument('--index-url',default='https://pypi.org/simple')
    parser.add_argument('--venv',type=Path,required=True)
    args=parser.parse_args();target=args.venv.resolve()
    if target.exists():parser.error('venv path must be new')
    if args.wheel is not None:
        wheel=args.wheel.resolve()
        if not wheel.is_file():parser.error('wheel must exist')
        version=audit(wheel,args.expected_version)['version'];requirement=str(wheel)
    else:
        version=args.package_version
        if str(Version(version))!=version or Version(version).local is not None:parser.error('invalid package version')
        if args.expected_version is not None and version!=args.expected_version:parser.error('version mismatch')
        requirement='naiyue-rag=='+version
    venv.EnvBuilder(with_pip=True).create(target)
    python=target/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    subprocess.run([str(python),'-m','pip','--isolated','install','--no-cache-dir','--index-url',args.index_url,requirement],check=True)
    subprocess.run([str(python),'-m','pip','check'],check=True)
    script=Path(__file__).with_name('installed_smoke.py').resolve()
    env=dict(os.environ);env.pop('PYTHONPATH',None)
    with tempfile.TemporaryDirectory(prefix='nyr-away-from-source-') as folder:
        subprocess.run([str(python),'-I',str(script),'--expected-version',version],cwd=folder,env=env,check=True)


if __name__=='__main__':main()
