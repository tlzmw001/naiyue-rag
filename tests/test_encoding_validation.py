"""Index ordering, numeric vector integrity and observable unknown usage."""
import copy
import json
import subprocess
import sys

import pytest

from naiyue_rag.core.errors import EncodingError
from naiyue_rag.encoding import prepare_query_encoding_input,normalize_embedding_response,ProviderBatchResult
from test_encoding_settings import config
from test_document_chunker import offline


def inputs():return [prepare_query_encoding_input(q,config()) for q in ['first','second']]


def response():
    return {'model':'synthetic-model','data':[{'index':1,'embedding':[2.,1.,0.]},
        {'index':0,'embedding':[1.,0.,0.]}],'usage':{'prompt_tokens':7,'total_tokens':7}}


def test_response_restores_index_and_binds_ids_hashes():
    items=inputs();raw=response();before=copy.deepcopy(raw)
    result=normalize_embedding_response(raw,items,config(),source_kind='simulated')
    assert result.vectors==[[1.,0.,0.],[2.,1.,0.]]
    assert result.input_ids==[i.item_id for i in items]
    assert result.input_hashes==[i.embedding_text_sha256 for i in items]
    assert result.source_kind=='simulated' and result.usage_status=='known'
    assert result.usage=={'prompt_tokens':7,'total_tokens':7}
    assert raw==before
    serialized=result.to_dict();serialized['vectors'][0][0]=999
    assert result.vectors[0][0]==1.


@pytest.mark.parametrize('fault',['count','index-duplicate','index-bool','index-missing','dimension','bool','nan','zero','model'])
def test_bad_response_never_becomes_vectors(fault,caplog):
    raw=response()
    if fault=='count':raw['data'].pop()
    elif fault=='index-duplicate':raw['data'][1]['index']=1
    elif fault=='index-bool':raw['data'][0]['index']=True
    elif fault=='index-missing':raw['data'][0].pop('index')
    elif fault=='dimension':raw['data'][0]['embedding'].pop()
    elif fault=='bool':raw['data'][0]['embedding'][0]=True
    elif fault=='nan':raw['data'][0]['embedding'][0]=float('nan')
    elif fault=='zero':raw['data'][0]['embedding']=[0.,0.,0.]
    else:raw['model']='SYNTHETIC_PRIVATE'
    with pytest.raises(EncodingError,match='^invalid_embedding_response$'):
        normalize_embedding_response(raw,inputs(),config(),source_kind='simulated')
    assert 'SYNTHETIC_PRIVATE' not in caplog.text


@pytest.mark.parametrize('usage,status',[(None,'unknown_missing'),({'prompt_tokens':True,'total_tokens':0},'unknown_invalid')])
def test_unknown_usage_preserves_vector_and_explicit_status(usage,status):
    raw=response();raw['usage']=usage
    result=normalize_embedding_response(raw,inputs(),config(),source_kind='simulated')
    assert len(result.vectors)==2 and result.usage is None and result.usage_status==status


def test_alias_explicit_size_limit_and_unavailable_source_kind():
    raw=response();raw['model']='alias'
    cfg=config(embedding={'allowed_response_models':['synthetic-model','alias']})
    items=[prepare_query_encoding_input(q,cfg) for q in ['first','second']]
    assert normalize_embedding_response(raw,items,cfg,source_kind='simulated').returned_model=='alias'
    with pytest.raises(EncodingError,match='^embedding_response_too_large$'):
        normalize_embedding_response(response(),inputs(),config(runtime={'max_response_bytes':10}),source_kind='simulated')
    with pytest.raises(EncodingError,match='^invalid_embedding_response$'):
        normalize_embedding_response(response(),inputs(),config(),source_kind='guessed')


def test_formal_package_import_does_not_load_experiments_or_snapshot():
    code="import sys,naiyue_rag; assert not any(n=='experiments' or n.startswith('experiments.') for n in sys.modules); assert 'naiyue_rag.a2_snapshot' not in sys.modules; assert not hasattr(naiyue_rag,'load_snapshot')"
    result=subprocess.run([sys.executable,'-c',code],text=True,capture_output=True)
    assert result.returncode==0,result.stderr


def test_result_serialization_revalidates_mutation_and_roundtrips():
    result=normalize_embedding_response(response(),inputs(),config(),source_kind='simulated')
    restored=ProviderBatchResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert restored.to_dict()==result.to_dict()
    result.vectors[0][0]=float('nan')
    with pytest.raises(EncodingError,match='^invalid_provider_batch_result$'):result.to_dict()
