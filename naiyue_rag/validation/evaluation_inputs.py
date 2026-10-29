"""Closed question files; human hints never become retrieval inputs."""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
from ..local_client import LocalServiceError
from ..storage.document_views import _valid_document_id

LOGGER=logging.getLogger(__name__)


class EvaluationError(LocalServiceError):
    def __init__(self,code):
        LOGGER.error('evaluation_failed code=%s',code)
        super().__init__(code)


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError()
        value[key]=item
    return value


def _invalid_constant(value):raise ValueError()


def _text(value,*,nonempty=False):
    if type(value) is not str or '\x00' in value or (nonempty and not value.strip()):raise ValueError()
    value.encode('utf-8')


def read_questions(path,*,max_questions=1000,max_input_bytes=16777216):
    try:
        if any(type(n) is not int or n<1 for n in (max_questions,max_input_bytes)):raise ValueError()
        source=Path(path).expanduser().absolute()
        if any(p.is_symlink() for p in (source,*source.parents)):raise ValueError()
        fd=os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(fd,'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError()
            payload=stream.read(max_input_bytes+1)
        if len(payload)>max_input_bytes:raise ValueError()
        rows=[];seen=set()
        for line in payload.decode('utf-8').split('\n'):
            if not line.strip():continue
            raw=json.loads(line,object_pairs_hook=_unique,parse_constant=_invalid_constant)
            allowed={'id','query','reference_notes','checkpoints','scope_document_ids','exclude_document_ids'}
            if type(raw) is not dict or not {'id','query'}<=set(raw) or set(raw)-allowed:raise ValueError()
            uid=raw['id']
            if type(uid) is not str or re.fullmatch('[A-Za-z0-9_-]{1,64}',uid) is None or uid in seen:raise ValueError()
            seen.add(uid);_text(raw['query'],nonempty=True)
            _text(raw.get('reference_notes',''))
            checks=raw.get('checkpoints',[])
            if type(checks) is not list:raise ValueError()
            for item in checks:_text(item,nonempty=True)
            request={'query':raw['query']}
            for field in ('scope_document_ids','exclude_document_ids'):
                if field not in raw:continue
                ids=raw[field]
                if type(ids) is not list or any(not _valid_document_id(uid) for uid in ids) or len(set(ids))!=len(ids):raise ValueError()
                request[field]=ids
            rows.append(dict(raw,request=request,request_sha256=digest(request)))
            if len(rows)>max_questions:raise ValueError()
        if not rows:raise ValueError()
        return {'sha256':hashlib.sha256(payload).hexdigest(),'questions':rows}
    except Exception:raise EvaluationError('evaluation_invalid_questions') from None
