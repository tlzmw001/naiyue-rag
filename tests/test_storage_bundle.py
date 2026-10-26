"""Formal artifact contracts and configuration; no service or storage SDK calls."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
import yaml
from naiyue_rag import (MarkdownLoader,DocumentChunker,IngestionSettings,prepare_knowledge_base,
    prepare_document_encoding_inputs,BatchProcessor)
from naiyue_rag.storage import (IndexBundle,prepare_index_bundle,BundleStore,StorageSettings,load_storage_settings)
from naiyue_rag.core.errors import StorageError,SettingsError
from naiyue_rag.encoding.validation import ProviderBatchResult
from naiyue_rag.encoding.execution_report import new_report
from test_encoding_settings import config
from test_batch_processor import Sparse
from test_document_chunker import offline

PRIVATE='SYNTHETIC_PRIVATE'
KB='知识库/demo'


def storage_settings(tmp_path,**changes):
    raw=dict(storage_root=str(tmp_path/'storage'),knowledge_base_id=KB,max_documents=1000,
             max_chunks=10000,max_file_bytes=16777216,max_bundle_bytes=67108864,max_manifest_bytes=65536)
    raw.update(changes)
    return StorageSettings.from_dict(raw)


class Dense:
    def __init__(self,cfg):self.settings=cfg;self.calls=0
    def encode_batch(self,items,*,remaining_seconds):
        self.calls+=1;report=new_report();report.update(attempted_requests=1,http_status=200)
        return ProviderBatchResult([[1.,2.,3.] for item in items],[i.item_id for i in items],
            [i.embedding_text_sha256 for i in items],self.settings.model_space_id,'synthetic-model','simulated',
            dict(prompt_tokens=7,total_tokens=7),'known'),report


def ingredients(tmp_path,mode='normal',*,dense=None,sparse=None):
    source=tmp_path/'source';source.mkdir(parents=True)
    if mode not in ('empty','blank'):
        (source/'L1_Module.md').write_text('# 模块\n\n## 开关\n\nfeature_x=1启用，0关闭。\n\n[历史需求](L2_A.md)\n')
        (source/'L2_A.md').write_text('# 历史需求A\n\n> 上级：[模块](L1_Module.md)\n\nthreshold=0.5时检查边界。\n')
        (source/'L2_A_测试用例.md').write_text('# A测试用例\n\n## 维度一\n\n> 来源：L2_A §2，L999-L1000\n\n| 序号 | 用例标题 | 前置条件 | 测试步骤 | 预期结果 |\n| --- | --- | --- | --- | --- |\n| TC-01 | 边界 | 开关开启<br>threshold=0.5 | 调用feature_x | 明确结果 |\n')
    elif mode=='blank':(source/'blank.md').write_text('')
    cfg=config();ingestion=IngestionSettings(40,10)
    docs=MarkdownLoader(source,KB,4096).load_all()
    chunks,relations,diagnostics=prepare_knowledge_base(docs,DocumentChunker(ingestion),text_mode='raw')
    dense=dense or Dense(cfg);sparse=sparse or Sparse(cfg)
    result=BatchProcessor(cfg,dense,sparse).process(prepare_document_encoding_inputs(docs,chunks,cfg))
    return dict(documents=docs,chunks=chunks,relations=relations,encoding_result=result,
                knowledge_base_id=KB,encoding_settings=cfg,ingestion_settings=ingestion)


def make_bundle(tmp_path,mode='normal'):
    return prepare_index_bundle(**ingredients(tmp_path,mode))


def test_lossless_bundle_identity_context_and_roundtrip(tmp_path):
    data=ingredients(tmp_path);bundle=prepare_index_bundle(**data)
    raw=bundle.to_dict();restored=IndexBundle.from_dict(json.loads(json.dumps(raw)))
    assert restored.to_dict()==raw
    assert {c.id for c in bundle.chunks}=={r.input.item_id for r in bundle.encoding_result.records}
    case=next(c for c in bundle.chunks if c.metadata['kind']=='test_case')
    assert case.metadata['case_id']=='TC-01' and case.metadata['case_fields'][-1]=='明确结果'
    assert 'L999-L1000' in json.dumps(raw,ensure_ascii=False)
    assert bundle.relations['edges'] and bundle.preparation_diagnostics
    assert all(r.input.embedding_text_sha256!=r.input.retrieval_text_sha256 for r in bundle.encoding_result.records)
    data['documents'][0].text=PRIVATE
    assert PRIVATE not in json.dumps(bundle.to_dict())
    raw['documents'][0]['text']=PRIVATE
    assert PRIVATE not in json.dumps(restored.to_dict())

@pytest.mark.parametrize('mode',['empty','blank'])
def test_empty_bundle_retains_explicit_kb_and_no_fake_records(tmp_path,mode):
    bundle=make_bundle(tmp_path,mode)
    assert bundle.knowledge_base_id==KB and not bundle.chunks and bundle.encoding_result.records==[]
    assert bundle.encoding_result.knowledge_base_id is None and bundle.encoding_result.report.status=='empty'
    assert len(bundle.documents)==(mode=='blank')

@pytest.mark.parametrize('fault',['source','source-id','line-starts','chunk-text','chunk-context','chunk-view',
    'relation','missing-record','extra-record','input-hash','vector','tokenizer','scope','encoding-settings','diagnostic','extra-field'])
def test_mutated_bundle_rejected_without_payload(tmp_path,fault,caplog):
    raw=make_bundle(tmp_path).to_dict()
    if fault=='source':raw['documents'][0]['text']+=PRIVATE
    elif fault=='source-id':raw['documents'][0]['id']='other'
    elif fault=='line-starts':raw['documents'][0]['metadata']['line_starts']=[0]
    elif fault=='chunk-text':raw['chunks'][0]['text']=PRIVATE
    elif fault=='chunk-context':raw['chunks'][0]['metadata']['contexts'][0]['text']=PRIVATE
    elif fault=='chunk-view':raw['chunks'][0]['metadata']['retrieval_view']['text']=PRIVATE
    elif fault=='relation':raw['relations']['edges'][0]['source_document_id']='other'
    elif fault=='missing-record':raw['encoding_result']['records'].pop()
    elif fault=='extra-record':raw['encoding_result']['records'].append(copy.deepcopy(raw['encoding_result']['records'][0]))
    elif fault=='input-hash':raw['encoding_result']['records'][0]['input']['retrieval_text_sha256']='0'*64
    elif fault=='vector':raw['encoding_result']['records'][0]['dense_vector']=[0.,0.,0.]
    elif fault=='tokenizer':raw['encoding_result']['tokenizer_id']='0'*64
    elif fault=='scope':raw['knowledge_base_id']='elsewhere'
    elif fault=='encoding-settings':raw['encoding_settings']['representation']['document_prefix']='changed:'
    elif fault=='diagnostic':raw['preparation_diagnostics']=[]
    else:raw['secret']=PRIVATE
    with pytest.raises(StorageError):IndexBundle.from_dict(raw)
    assert PRIVATE not in caplog.text


def test_chunk_order_follows_result_ids_not_supplied_list_position(tmp_path):
    data=ingredients(tmp_path);expected=prepare_index_bundle(**data).to_dict()
    data['chunks'].reverse();data['documents'].reverse()
    assert prepare_index_bundle(**data).to_dict()==expected


def test_two_paths_same_bytes_are_distinct_documents(tmp_path):
    data=ingredients(tmp_path,'blank');root=tmp_path/'source'
    (root/'first.md').write_text('# 标题\n\n相同内容。')
    (root/'second.md').write_bytes((root/'first.md').read_bytes())
    docs=MarkdownLoader(root,KB,4096).load_all();chunks,relations,_=prepare_knowledge_base(docs,DocumentChunker(data['ingestion_settings']),text_mode='raw')
    cfg=data['encoding_settings'];result=BatchProcessor(cfg,Dense(cfg),Sparse(cfg)).process(prepare_document_encoding_inputs(docs,chunks,cfg))
    bundle=prepare_index_bundle(docs,chunks,relations,result,knowledge_base_id=KB,encoding_settings=cfg,ingestion_settings=data['ingestion_settings'])
    matching=[d for d in bundle.documents if d.text]
    assert len(matching)==2 and matching[0].id!=matching[1].id and matching[0].metadata['source_sha256']==matching[1].metadata['source_sha256']


def test_yaml_and_constructor_are_side_effect_free(tmp_path):
    raw=storage_settings(tmp_path).to_dict();raw['storage_root']='./private-index'
    p=tmp_path/'storage.yaml';p.write_text(yaml.safe_dump(raw));cfg=load_storage_settings(p)
    assert cfg.storage_root==str(tmp_path/'private-index') and cfg.knowledge_base_id==KB
    BundleStore(cfg)
    assert not Path(cfg.storage_root).exists() and not hasattr(cfg,'api_key')
    assert StorageSettings.from_dict(cfg.to_dict())==cfg

@pytest.mark.parametrize('key,value',[
    ('max_documents',True),('max_chunks',0),('max_file_bytes',-1),('max_bundle_bytes',1),
    ('max_manifest_bytes',float('inf')),('storage_root','../outside'),('storage_root','relative'),
    ('storage_root','/tmp/../private'),('knowledge_base_id',''),('knowledge_base_id','bad\x00id'),('api_key',PRIVATE)])
def test_invalid_settings_are_safe(tmp_path,key,value,caplog):
    raw=storage_settings(tmp_path).to_dict();raw[key]=value
    with pytest.raises(SettingsError):StorageSettings.from_dict(raw)
    assert PRIVATE not in caplog.text

@pytest.mark.parametrize('text',['x: 1\nx: 2','x: &a []\ny: *a','true: value'])
def test_strict_yaml_is_reused(tmp_path,text):
    p=tmp_path/'bad.yaml';p.write_text(text)
    with pytest.raises(SettingsError,match='invalid_settings_yaml'):load_storage_settings(p)


def test_settings_read_failure_is_logged_without_payload(tmp_path,caplog):
    with pytest.raises(SettingsError,match='settings_file_error'):
        load_storage_settings(tmp_path/(PRIVATE+'.yaml'))
    assert 'settings_file_error' in caplog.text and PRIVATE not in caplog.text
