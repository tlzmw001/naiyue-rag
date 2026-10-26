"""Serialized pairs are source/version bound and independent of caller-owned containers."""
import copy
import json
import pytest
from naiyue_rag.core.encoded_types import EncodedRecord,EncodingResult
from naiyue_rag.core.errors import EncodingError
from test_batch_processor import setup,inputs,PRIVATE


def test_roundtrip_and_defensive_copies():
    result=setup()[0].process(inputs());raw=result.to_dict()
    restored=EncodingResult.from_dict(json.loads(json.dumps(raw)))
    assert restored.to_dict()==raw and PRIVATE not in repr(restored)
    raw['records'][0]['dense_vector'][0]=999
    raw['report']['requests']['attempted_requests']=99
    assert restored.records[0].dense_vector[0]==1 and restored.report.requests['attempted_requests']==3
    pair=EncodedRecord.from_dict(restored.records[0].to_dict())
    original=restored.records[0]
    original.sparse.tokens.append(PRIVATE)
    assert pair.sparse.tokens==[]

@pytest.mark.parametrize('fault',['extra','nan','bool','zero','kind','id','hash','batch'])
def test_invalid_pair_rejected(fault):
    raw=setup()[0].process(inputs()).records[0].to_dict()
    if fault=='extra':raw['extra']=PRIVATE
    elif fault=='nan':raw['dense_vector'][0]=float('nan')
    elif fault=='bool':raw['dense_vector'][0]=True
    elif fault=='zero':raw['dense_vector']=[0.,0.,0.]
    elif fault=='kind':raw['sparse']['kind']='query'
    elif fault=='id':raw['sparse']['item_id']='other'
    elif fault=='hash':raw['sparse']['retrieval_text_sha256']='0'*64
    else:raw['batch_index']=True
    with pytest.raises(EncodingError,match='invalid_encoded_record'):EncodedRecord.from_dict(raw)

@pytest.mark.parametrize('fault',['extra','dimension','duplicate','kb','model','representation','tokenizer','count','fingerprint','batch-range','bool'])
def test_result_contract_rejects_inconsistent_consumption(fault):
    raw=setup()[0].process(inputs()).to_dict()
    if fault=='extra':raw['extra']=PRIVATE
    elif fault=='dimension':raw['dimensions']=4
    elif fault=='duplicate':raw['records'][-1]=copy.deepcopy(raw['records'][0])
    elif fault=='kb':raw['knowledge_base_id']='other'
    elif fault=='model':raw['model_space_id']='0'*64
    elif fault=='representation':raw['representation_id']='0'*64
    elif fault=='tokenizer':raw['tokenizer_id']='0'*64
    elif fault=='count':raw['records'].pop()
    elif fault=='fingerprint':raw['report']['input_fingerprint']='0'*64
    elif fault=='batch-range':raw['records'][0]['batch_index']=1
    else:raw['dimensions']=True
    with pytest.raises(EncodingError,match='invalid_encoding_result'):EncodingResult.from_dict(raw)


def test_mutated_objects_are_revalidated_on_consumption():
    result=setup()[0].process(inputs());result.records[-1].dense_vector=[0,0,0]
    with pytest.raises(EncodingError,match='invalid_encoding_result'):result.to_dict()
