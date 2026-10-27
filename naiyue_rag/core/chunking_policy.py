"""Replayable chunking rules; new-task defaults never rewrite saved rules."""
import hashlib
from importlib.metadata import version
import json
from .errors import SettingsError

LEGACY_CHUNKING_POLICY='markdown-source-v1'
CHINESE_CHUNKING_POLICY='markdown-source-zh-v2'
DEFAULT_CHUNKING_POLICY=CHINESE_CHUNKING_POLICY
LEGACY_SEPARATORS=('\n\n','\n','. ','! ','? ','; ',', ',' ','')


def chunking_parameters(policy):
    if type(policy) is not str or policy not in (LEGACY_CHUNKING_POLICY,CHINESE_CHUNKING_POLICY):
        raise SettingsError('invalid_ingestion_settings')
    if policy==CHINESE_CHUNKING_POLICY:
        return dict(policy=policy,separators=['\n\n','\n','. ','! ','? ','。','; ',', ','，',' ',''],
            keep_separator='end',strip_whitespace=False)
    return dict(policy=policy,separators=list(LEGACY_SEPARATORS),keep_separator=True,strip_whitespace=False)


def chunking_profile(settings):
    parameters=chunking_parameters(settings.chunking_policy)
    profile=dict(parser='markdown-it-py',parser_version=version('markdown-it-py'),
        splitter='recursive',splitter_version=version('langchain-text-splitters'),
        chunk_size=settings.chunk_size,chunk_overlap=settings.chunk_overlap,**parameters)
    profile['config_sha256']=hashlib.sha256(json.dumps(profile,sort_keys=True,
        ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return profile
