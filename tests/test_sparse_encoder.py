"""Real installed jieba, fixed lexical policy and verified cache lifecycle."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from naiyue_rag.encoding.sparse_encoder import SparseEncoder
from naiyue_rag.core.sparse_types import SparseRecord
from naiyue_rag.core.errors import EncodingError
from naiyue_rag.encoding import prepare_query_encoding_input
from test_sparse_encoding_settings import sparse_config
from test_encoding_settings import config
from test_document_chunker import offline

TEXT='开关 关 开关 TC-01 cvr_ltv route=1 threshold=0.5'
TERMS=['开关','开关','tc-01','cvr_ltv','route','1','threshold','0.5']

def encoder(tmp_path,**changes):return SparseEncoder(config(),sparse_config(tmp_path,**changes))

def item(text,cfg=None):return prepare_query_encoding_input(text,cfg or config())

def test_real_terms_tf_query_dedup_prefix_and_roundtrip(tmp_path):
    enc=encoder(tmp_path);source=item(TEXT);before=source.to_dict()
    result=enc.encode_batch([source])[0]
    assert result.tokens==TERMS
    assert result.term_frequencies=={'开关':2,'tc-01':1,'cvr_ltv':1,'route':1,'1':1,'threshold':1,'0.5':1}
    assert result.doc_length==8 and result.unique_terms==7
    assert result.item_id==source.item_id and result.kind=='query'
    assert result.retrieval_text_sha256==source.retrieval_text_sha256 and 'query' not in result.tokens
    assert enc.query_terms(source)==list(dict.fromkeys(TERMS)) and source.to_dict()==before
    assert SparseRecord.from_dict(json.loads(json.dumps(result.to_dict()))).to_dict()==result.to_dict()
    raw=result.to_dict();raw['tokens'].append('extra');assert result.tokens==TERMS

def test_complete_numbers_identifiers_and_search_overlap(tmp_path):
    enc=encoder(tmp_path)
    text='0 0.5 0.50 -1 +2 1e-3 v1.2 module.path _'
    assert enc.query_terms(item(text))==['0','0.5','0.50','-1','+2','1e-3','v1.2','module.path']
    assert enc.query_terms(item('人工智能'))==['人工','智能','人工智能']

def test_configured_minimum_and_lowercase_share_cache_but_not_token_identity(tmp_path):
    first=encoder(tmp_path)
    second=encoder(tmp_path,min_chinese_term_length=1,lowercase=False)
    assert second.query_terms(item('关 TC-01'))==['关','TC-01']
    assert first.tokenizer_id!=second.tokenizer_id
    assert first.tokenizer.cache_directory==second.tokenizer.cache_directory
    elsewhere=encoder(tmp_path/'other',max_terms_per_input=20000)
    assert first.tokenizer_id==elsewhere.tokenizer_id
    identity=first.tokenizer.identity;identity['policy']='changed'
    assert first.tokenizer.identity['policy']=='zh-search-ascii-lexical-v2'

@pytest.mark.parametrize('text',['!!! | < > _','关'])
def test_empty_terms_are_valid_not_execution_failures(tmp_path,text):
    enc=encoder(tmp_path);record=enc.encode_batch([item(text)])[0]
    assert record.tokens==[] and record.term_frequencies=={} and record.doc_length==record.unique_terms==0
    assert enc.query_terms(item(text))==[]

def test_same_cache_reused_without_dictionary_rebuild(tmp_path,monkeypatch):
    enc=encoder(tmp_path);directory=enc.tokenizer.cache_directory
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
    import jieba
    def forbidden(*args,**kwargs):raise AssertionError('unexpected dictionary rebuild')
    monkeypatch.setattr(jieba.Tokenizer,'gen_pfdict',forbidden)
    second=encoder(tmp_path)
    assert second.query_terms(item(TEXT))==list(dict.fromkeys(TERMS))
    assert files=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}

@pytest.mark.parametrize('fault',['cache','metadata','missing-metadata','extra-field','cache-symlink'])
def test_broken_cache_is_rejected_without_rewriting(tmp_path,fault,caplog):
    enc=encoder(tmp_path);folder=enc.tokenizer.cache_directory
    cache=folder/'jieba.cache';meta=folder/'metadata.json'
    if fault=='cache':cache.write_bytes(b'SYNTHETIC_PRIVATE')
    elif fault=='metadata':meta.write_text('{}')
    elif fault=='missing-metadata':meta.rename(folder/'metadata.old')
    elif fault=='extra-field':
        raw=json.loads(meta.read_text());raw['private']='SYNTHETIC_PRIVATE';meta.write_text(json.dumps(raw))
    else:
        cache.rename(folder/'cache.old');cache.symlink_to(folder/'cache.old')
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    with pytest.raises(EncodingError):encoder(tmp_path)
    after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    assert before==after and 'SYNTHETIC_PRIVATE' not in caplog.text

def test_cache_read_failure_cannot_fallback_rebuild(tmp_path,monkeypatch,caplog):
    enc=encoder(tmp_path);folder=enc.tokenizer.cache_directory
    before={p.name:p.stat().st_mtime_ns for p in folder.iterdir()}
    import jieba
    original=jieba.marshal.load
    def fail(handle):
        # Fail the library's file IO, not our earlier BytesIO structure validation.
        if getattr(handle,'name',None)==str(folder/'jieba.cache'):raise OSError('SYNTHETIC_PRIVATE')
        return original(handle)
    monkeypatch.setattr(jieba.marshal,'load',fail)
    with pytest.raises(EncodingError,match='^sparse_cache_load_failed$'):encoder(tmp_path)
    assert before=={p.name:p.stat().st_mtime_ns for p in folder.iterdir()}
    assert 'SYNTHETIC_PRIVATE' not in caplog.text

def test_swallowed_cache_write_failure_is_observable_and_safe(tmp_path,monkeypatch,caplog):
    import jieba
    def fail(*args,**kwargs):raise OSError('SYNTHETIC_PRIVATE')
    monkeypatch.setattr(jieba.marshal,'dump',fail)
    original=list(jieba.default_logger.filters)
    with pytest.raises(EncodingError):encoder(tmp_path)
    assert 'SYNTHETIC_PRIVATE' not in caplog.text
    assert 'sparse_cache' in caplog.text and list(jieba.default_logger.filters)==original

def test_metadata_write_failure_and_cache_directory_boundary(tmp_path,monkeypatch,caplog):
    import naiyue_rag.encoding.sparse_tokenizer as module
    original=module.os.replace
    def fail(src,dest):
        if Path(dest).name=='metadata.json':raise OSError('SYNTHETIC_PRIVATE')
        return original(src,dest)
    monkeypatch.setattr(module.os,'replace',fail)
    with pytest.raises(EncodingError,match='^sparse_cache_initialization_failed$'):encoder(tmp_path)
    assert 'SYNTHETIC_PRIVATE' not in caplog.text
    target=tmp_path/'target';target.mkdir();link=tmp_path/'link';link.symlink_to(target,target_is_directory=True)
    with pytest.raises(EncodingError):encoder(tmp_path,cache_dir=str(link))

def test_path_inspection_io_failure_is_safe_and_observable(tmp_path,monkeypatch,caplog):
    original=Path.is_symlink
    def fail(path):
        if path==tmp_path/'token-cache':raise PermissionError('SYNTHETIC_PRIVATE')
        return original(path)
    monkeypatch.setattr(Path,'is_symlink',fail)
    with pytest.raises(EncodingError,match='^sparse_resource_path_invalid$'):encoder(tmp_path)
    assert 'SYNTHETIC_PRIVATE' not in caplog.text

@pytest.mark.parametrize('fault',['empty','multi-batch','hash','identity','query-kind'])
def test_input_contract_failures_do_not_return_partial_records(tmp_path,fault):
    enc=encoder(tmp_path);inputs=[item('开关')]
    if fault=='empty':inputs=[]
    elif fault=='multi-batch':inputs=[item(q) for q in ['开关','异常','历史']]
    elif fault=='hash':inputs[0].retrieval_text='changed'
    elif fault=='identity':inputs=[item('开关',config(representation={'query_prefix':'other: '}))]
    else:inputs[0].kind='document'
    with pytest.raises(EncodingError):
        if fault=='query-kind':enc.query_terms(inputs[0])
        else:enc.encode_batch(inputs)

def test_terms_and_resource_limits_and_library_failure(tmp_path,monkeypatch,caplog):
    enc=encoder(tmp_path,max_terms_per_input=2)
    with pytest.raises(EncodingError,match='^sparse_term_limit$'):enc.encode_batch([item('a b c')])
    with pytest.raises(EncodingError,match='^sparse_resource_limit$'):encoder(tmp_path/'small',max_resource_bytes=10)
    def fail(*args,**kwargs):raise RuntimeError('SYNTHETIC_PRIVATE')
    monkeypatch.setattr(enc.tokenizer.engine,'cut_for_search',fail)
    with pytest.raises(EncodingError,match='^sparse_tokenization_failed$'):enc.encode_batch([item('开关')])
    assert 'SYNTHETIC_PRIVATE' not in caplog.text

@pytest.mark.parametrize('fault',['tf','length','unique','bool','empty-token','hash','extra','mutated'])
def test_record_serialization_revalidates_all_derived_statistics(tmp_path,fault):
    record=encoder(tmp_path).encode_batch([item(TEXT)])[0];raw=record.to_dict()
    if fault=='tf':raw['term_frequencies']['开关']=1
    elif fault=='length':raw['doc_length']=7
    elif fault=='unique':raw['unique_terms']=8
    elif fault=='bool':raw['doc_length']=True
    elif fault=='empty-token':raw['tokens'][0]=''
    elif fault=='hash':raw['tokenizer_id']='bad'
    elif fault=='extra':raw['private']='SYNTHETIC_PRIVATE'
    else:record.tokens.append('extra')
    with pytest.raises(EncodingError,match='^invalid_sparse_record$'):
        if fault=='mutated':record.to_dict()
        else:SparseRecord.from_dict(raw)
