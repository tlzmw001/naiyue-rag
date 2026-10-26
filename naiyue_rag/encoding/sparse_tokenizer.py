"""Installed jieba algorithm with a verified cache and a fixed lexical policy."""
import copy
import hashlib
import io
import json
import logging
import marshal
import os
from pathlib import Path
import re
import sys
import jieba
from ..core.encoding_settings import digest
from ..core.sparse_encoding_settings import validate_sparse_settings
from ..core.encoding_types import fail_encoding
from ..core.errors import EncodingError
from ..core.yaml_config import MAX_SETTINGS_BYTES

POLICY='zh-search-ascii-lexical-v2'
SEGMENTS=re.compile(r'[+-](?=[0-9])[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*|[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*|[\u4e00-\u9fff]+')


def _check_path(path):
    try:
        if any(p.is_symlink() for p in [path,*path.parents]):fail_encoding('sparse_resource_path_invalid')
    except EncodingError:raise
    except Exception:fail_encoding('sparse_resource_path_invalid')


def _read_resource(path,limit,code):
    _check_path(path)
    try:
        if not path.is_file():raise ValueError()
        with path.open('rb') as handle:payload=handle.read(limit+1)
    except Exception:fail_encoding(code)
    if len(payload)>limit:fail_encoding('sparse_resource_limit')
    return payload


def _unique_object(pairs):
    data={}
    for key,value in pairs:
        if key in data:raise ValueError()
        data[key]=value
    return data


def _validate_cache(payload):
    try:
        stream=io.BytesIO(payload);value=marshal.load(stream)
        if stream.read(1) or type(value) is not tuple or len(value)!=2:raise ValueError()
        freq,total=value
        if type(freq) is not dict or not freq or type(total) is not int or total<=0:raise ValueError()
        if any(type(k) is not str or not k or type(v) is not int or v<0 for k,v in freq.items()):raise ValueError()
    except Exception:fail_encoding('sparse_cache_invalid')


class _DictionaryBoundTokenizer(jieba.Tokenizer):
    def __init__(self,snapshot,cache_only):
        super().__init__()
        self._snapshot=snapshot;self._cache_only=cache_only

    def get_dict_file(self):
        if self._cache_only:fail_encoding('sparse_cache_load_failed')
        return io.BytesIO(self._snapshot)


class _InitializationLogFilter(logging.Filter):
    def filter(self,record):
        record.msg='sparse_jieba_initialization_failed' if record.levelno>=logging.ERROR else 'sparse_jieba_initialization'
        record.args=();record.exc_info=None;record.exc_text=None;record.stack_info=None
        return True


class SparseTokenizer:
    def __init__(self,settings):
        validate_sparse_settings(settings)
        self.settings=settings
        dictionary=Path(jieba.__file__).parent/'dict.txt'
        payload=_read_resource(dictionary,settings.max_resource_bytes,'sparse_dictionary_read_failed')
        dictionary_sha=hashlib.sha256(payload).hexdigest()
        self._identity={'policy':POLICY,'jieba_version':jieba.__version__,'dictionary_sha256':dictionary_sha,
            'chinese_mode':'search','hmm':False,'min_chinese_term_length':settings.min_chinese_term_length,
            'lowercase':settings.lowercase,'lexical_pattern':SEGMENTS.pattern}
        self.tokenizer_id=digest(self._identity)
        cache_identity={'policy':'jieba-cache-v1','jieba_version':jieba.__version__,
            'dictionary_sha256':dictionary_sha,'python_version':list(sys.version_info[:2]),'marshal_version':marshal.version}
        root=Path(settings.cache_dir);_check_path(root)
        self.cache_directory=root/digest(cache_identity)
        _check_path(self.cache_directory)
        try:
            root.mkdir(parents=True,exist_ok=True)
            try:self.cache_directory.mkdir(mode=0o700);fresh=True
            except FileExistsError:fresh=False
            cache=self.cache_directory/'jieba.cache';metadata=self.cache_directory/'metadata.json'
            expected=None
            if not fresh:
                raw=_read_resource(metadata,min(MAX_SETTINGS_BYTES,settings.max_resource_bytes),'sparse_cache_invalid')
                try:
                    expected=json.loads(raw.decode('utf-8'),object_pairs_hook=_unique_object)
                    if type(expected) is not dict or set(expected)!={'cache_identity','cache_sha256','cache_size_bytes'} or \
                            expected['cache_identity']!=cache_identity or type(expected['cache_size_bytes']) is not int:raise ValueError()
                except (ValueError,UnicodeError):fail_encoding('sparse_cache_invalid')
                data=_read_resource(cache,settings.max_resource_bytes,'sparse_cache_invalid')
                if expected['cache_sha256']!=hashlib.sha256(data).hexdigest() or expected['cache_size_bytes']!=len(data):
                    fail_encoding('sparse_cache_invalid')
                _validate_cache(data)
            self.engine=_DictionaryBoundTokenizer(payload,cache_only=not fresh)
            self.engine.tmp_dir=str(self.cache_directory);self.engine.cache_file='jieba.cache'
            log_filter=_InitializationLogFilter();jieba.default_logger.addFilter(log_filter)
            try:self.engine.initialize()
            finally:jieba.default_logger.removeFilter(log_filter)
            if not self.engine.initialized:fail_encoding('sparse_cache_initialization_failed')
            data=_read_resource(cache,settings.max_resource_bytes,'sparse_cache_initialization_failed')
            _validate_cache(data)
            current={'cache_identity':cache_identity,'cache_sha256':hashlib.sha256(data).hexdigest(),'cache_size_bytes':len(data)}
            if fresh:
                pending=self.cache_directory/'metadata.pending'
                with pending.open('x',encoding='utf-8') as handle:
                    json.dump(current,handle,sort_keys=True,allow_nan=False)
                    handle.flush();os.fsync(handle.fileno())
                os.replace(pending,metadata)
            elif current!=expected:fail_encoding('sparse_cache_invalid')
        except EncodingError:raise
        except Exception:fail_encoding('sparse_cache_initialization_failed')

    @property
    def identity(self):return copy.deepcopy(self._identity)

    def tokenize(self,text):
        terms=[];generated=0
        try:
            for match in SEGMENTS.finditer(text):
                value=match.group()
                candidates=[value] if value.isascii() else self.engine.cut_for_search(value,HMM=False)
                for term in candidates:
                    generated+=1
                    if generated>self.settings.max_terms_per_input:fail_encoding('sparse_term_limit')
                    if value.isascii():
                        if not any(c.isalnum() for c in term):continue
                    elif len(term)<self.settings.min_chinese_term_length:continue
                    terms.append(term.lower() if self.settings.lowercase else term)
            return terms
        except EncodingError:raise
        except Exception:fail_encoding('sparse_tokenization_failed')
