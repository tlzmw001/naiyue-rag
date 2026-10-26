"""Closed ingestion results and failures retain current-job observations only."""
import copy
import json
import pytest
from naiyue_rag import IngestionReceipt
from naiyue_rag.core.errors import IngestionJobError
from naiyue_rag.core.encoding_report import EncodingReport
from naiyue_rag.storage import ActiveVersion,IndexVersion
from test_index_versions import version
from test_storage_bundle import make_bundle,PRIVATE


@pytest.fixture
def receipt(tmp_path):
    bundle=make_bundle(tmp_path);report=bundle.encoding_result.report
    active=ActiveVersion(1,IndexVersion.from_dict(version(document_count=3,chunk_count=report.paired_input_count)))
    return IngestionReceipt('activated',active,3,0,0,0,report)


def test_receipt_roundtrip_and_report_copy(receipt):
    wire=receipt.to_dict();assert IngestionReceipt.from_dict(json.loads(json.dumps(wire)))==receipt
    assert set(wire)=={'status','active','added_document_count','updated_document_count',
        'unchanged_document_count','retained_document_count','encoding_report'}
    wire['encoding_report']['batches'].clear()
    assert receipt.encoding_report.batches and PRIVATE not in repr(receipt)
    source=receipt.encoding_report
    copied=IngestionReceipt('activated',receipt.active,3,0,0,0,source)
    source.batches.clear();assert copied.encoding_report.batches


@pytest.mark.parametrize('fault',['extra','missing','bool','negative','count','status','no-report',
    'report-count','failed-report','bad-active','wrong-container','reuse-with-added'])
def test_invalid_receipts_are_not_serialized(receipt,fault):
    raw=receipt.to_dict()
    if fault=='extra':raw['secret']=PRIVATE
    elif fault=='missing':raw.pop('status')
    elif fault=='bool':raw['updated_document_count']=False
    elif fault=='negative':raw['retained_document_count']=-1
    elif fault=='count':raw['added_document_count']=2
    elif fault=='status':raw['status']='success'
    elif fault=='no-report':raw['encoding_report']=None
    elif fault=='report-count':raw['active']=ActiveVersion(1,IndexVersion.from_dict(version(document_count=3,chunk_count=1))).to_dict()
    elif fault=='failed-report':raw['encoding_report']['status']='failed'
    elif fault=='bad-active':raw['active']['revision']=True
    elif fault=='reuse-with-added':raw.update(status='unchanged',encoding_report=None)
    else:raw=[]
    with pytest.raises(IngestionJobError,match='ingestion_invalid_request'):IngestionReceipt.from_dict(raw)


def test_reuse_has_no_new_encoding_report_and_force_can_be_unchanged(receipt):
    reused=IngestionReceipt('unchanged',receipt.active,0,0,2,1,None)
    assert reused.encoding_report is None and reused.to_dict()['encoding_report'] is None
    forced=IngestionReceipt('unchanged',receipt.active,0,0,3,0,receipt.encoding_report)
    assert forced.encoding_report.status=='success'


def test_job_error_roundtrip_and_defensive_copy(receipt):
    error=IngestionJobError('vector','chroma_write_failed',encoding_report=receipt.encoding_report,
        candidate_bundle_id='a'*64)
    assert error.activation_status=='not_attempted' and error.encoding_report.status=='success'
    assert IngestionJobError.from_dict(json.loads(json.dumps(error.to_dict()))).to_dict()==error.to_dict()
    receipt.encoding_report.batches.clear();assert error.encoding_report.batches
    assert str(error)=='chroma_write_failed' and PRIVATE not in repr(error)


@pytest.mark.parametrize('changes',[{'stage':'secret'},{'code':PRIVATE},{'candidate_bundle_id':'../x'},
    {'activation_status':'ok'},{'encoding_report':{}},{'extra':PRIVATE}])
def test_job_error_rejects_open_fields(changes):
    raw=dict(stage='load',code='ingestion_load_failed',encoding_report=None,
        candidate_bundle_id=None,activation_status='not_attempted');raw.update(changes)
    with pytest.raises(ValueError,match='ingestion_invalid_request'):IngestionJobError.from_dict(raw)


@pytest.mark.parametrize('stage,outcome',[('encode','activated'),('activate','not_attempted'),('finalize','not_committed')])
def test_job_error_cannot_claim_an_inconsistent_commit_state(stage,outcome):
    with pytest.raises(ValueError,match='ingestion_invalid_request'):
        IngestionJobError(stage,f'ingestion_{stage}_failed',activation_status=outcome)


@pytest.fixture
def removal_receipt(receipt):
    from naiyue_rag import RemovalReceipt
    from naiyue_rag.core.encoding_settings import digest
    from naiyue_rag.storage.document_views import DocumentInfo
    from test_storage_bundle import KB
    count=receipt.active.version.chunk_count
    previous=ActiveVersion(1,IndexVersion.from_dict(version(document_count=4,chunk_count=count+2)))
    current=ActiveVersion(2,IndexVersion.from_dict(version(document_count=3,chunk_count=count,bundle_id='a'*64)))
    info=DocumentInfo('doc-'+digest([KB,'gone.md']),'gone.md','b'*64,20,2)
    return RemovalReceipt('removed',info.document_id,previous,current,info,receipt.encoding_report)


def test_removal_receipt_roundtrip_and_defensive_copy(removal_receipt):
    from naiyue_rag import RemovalReceipt
    receipt=removal_receipt;raw=receipt.to_dict()
    assert set(raw)=={'status','requested_document_id','previous_active','active','removed_document','encoding_report'}
    assert RemovalReceipt.from_dict(json.loads(json.dumps(raw)))==receipt
    raw['encoding_report']['batches'].clear();raw['removed_document']['source_path']='changed.md'
    assert receipt.encoding_report.batches and receipt.removed_document.source_path=='gone.md'
    assert 'gone.md' not in repr(receipt) and PRIVATE not in repr(receipt)
    copied=RemovalReceipt.from_dict(receipt.to_dict())
    receipt.encoding_report.batches.clear();assert copied.encoding_report.batches


@pytest.mark.parametrize('fault',['extra','missing','status','id','missing-previous','missing-active','no-info',
    'no-report','document-id','kb-binding','doc-count','revision','same-version','report-count','failed-report',
    'not-found-with-info','not-found-with-report','not-found-changes-version','container'])
def test_invalid_removal_receipts_are_rejected(removal_receipt,fault):
    from naiyue_rag import RemovalReceipt
    raw=removal_receipt.to_dict()
    if fault=='extra':raw['secret']=PRIVATE
    elif fault=='missing':raw.pop('status')
    elif fault=='status':raw['status']='deleted'
    elif fault=='id':raw['requested_document_id']='../A'
    elif fault=='missing-previous':raw['previous_active']=None
    elif fault=='missing-active':raw['active']=None
    elif fault=='no-info':raw['removed_document']=None
    elif fault=='no-report':raw['encoding_report']=None
    elif fault=='document-id':raw['removed_document']['document_id']='doc-'+'0'*64
    elif fault=='kb-binding':raw['removed_document']['source_path']='other.md'
    elif fault=='doc-count':raw['active']=ActiveVersion(2,IndexVersion.from_dict(version(document_count=2))).to_dict()
    elif fault=='revision':raw['active']['revision']=3
    elif fault=='same-version':raw['active']=raw['previous_active']
    elif fault=='report-count':raw['active']=ActiveVersion(2,IndexVersion.from_dict(version(document_count=3,chunk_count=1))).to_dict()
    elif fault=='failed-report':raw['encoding_report']['status']='failed'
    elif fault=='not-found-with-info':raw.update(status='not_found',active=raw['previous_active'],encoding_report=None)
    elif fault=='not-found-with-report':raw.update(status='not_found',active=raw['previous_active'],removed_document=None)
    elif fault=='not-found-changes-version':raw.update(status='not_found',removed_document=None,encoding_report=None)
    else:raw=[]
    with pytest.raises(IngestionJobError,match='ingestion_invalid_request'):RemovalReceipt.from_dict(raw)


@pytest.mark.parametrize('active',[None,'selected'])
def test_not_found_removal_receipt_is_explicit_empty(active,receipt):
    from naiyue_rag import RemovalReceipt
    chosen=None if active is None else receipt.active
    result=RemovalReceipt('not_found','doc-'+'0'*64,chosen,chosen,None,None)
    assert RemovalReceipt.from_dict(result.to_dict())==result
