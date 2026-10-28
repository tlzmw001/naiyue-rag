"""One explicit base per configured path; no directories are created here."""
from pathlib import Path


def resolve_application_path(value,base,*,directory=True):
    if type(value) is not str or not value.strip() or any(ord(c)<32 for c in value):raise ValueError()
    value.encode('utf-8')
    raw=Path(value)
    if '..' in raw.parts:raise ValueError()
    target=raw.expanduser()
    if not target.is_absolute():target=Path(base)/target
    for index,part in enumerate((target,*target.parents)):
        if part.is_symlink():raise ValueError()
        if part.exists() and (directory or index>0) and not part.is_dir():raise ValueError()
    if not directory and target.exists() and not target.is_file():raise ValueError()
    return str(target.resolve())
