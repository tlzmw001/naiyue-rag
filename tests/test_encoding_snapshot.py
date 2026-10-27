"""Persistent source pairs are distinct from one job's observed requests."""
import copy
import pytest
from naiyue_rag.core.errors import StorageError
from test_storage_bundle import make_bundle,KB,Dense
from test_batch_processor import Sparse
from test_ingestion_types import receipt


def snapshot_for(root):
    from naiyue_rag.core.encoding_snapshot import EncodingSnapshot
    bundle=make_bundle(root)
    return bundle,EncodingSnapshot.from_result(KB,bundle.encoding_result)


def test_snapshot_pairs_origins_and_roundtrip_have_no_fake_job_report(tmp_path):
    from naiyue_rag.core.encoding_snapshot import EncodingSnapshot
    bundle,snapshot=snapshot_for(tmp_path)
    assert not hasattr(snapshot,'report') and not hasattr(snapshot.records[0],'batch_index')
    assert len(snapshot.records)==len(snapshot.origins)==len(bundle.chunks)
    assert all(o['kind']=='encoded' and o['source_bundle_id'] is None and
        o['source_job_id']==bundle.encoding_result.report.job_id for o in snapshot.origins)
    assert EncodingSnapshot.from_dict(snapshot.to_dict()).to_dict()==snapshot.to_dict()
    snapshot.records[0].dense_vector[0]=9
    assert bundle.encoding_result.records[0].dense_vector[0]==1


@pytest.mark.parametrize('fault',['duplicate','missing-origin','origin-id','origin-kind','origin-job',
    'origin-batch','origin-source','vector','tokenizer','scope','extra'])
def test_snapshot_rejects_corrupted_pairs_or_attribution(tmp_path,fault):
    from naiyue_rag.core.encoding_snapshot import EncodingSnapshot
    _,snapshot=snapshot_for(tmp_path);raw=snapshot.to_dict()
    if fault=='duplicate':raw['records'].append(copy.deepcopy(raw['records'][0]))
    elif fault=='missing-origin':raw['origins'].pop()
    elif fault=='origin-id':raw['origins'][0]['item_id']='unit-'+'0'*64
    elif fault=='origin-kind':raw['origins'][0]['kind']='unknown'
    elif fault=='origin-job':raw['origins'][0]['source_job_id']='bad'
    elif fault=='origin-batch':raw['origins'][0]['source_batch_index']=True
    elif fault=='origin-source':raw['origins'][0]['source_bundle_id']='0'*64
    elif fault=='vector':raw['records'][0]['dense_vector']=[0,0,0]
    elif fault=='tokenizer':raw['tokenizer_id']='b'*64
    elif fault=='scope':raw['knowledge_base_id']='other'
    else:raw['unexpected']=1
    with pytest.raises(StorageError):EncodingSnapshot.from_dict(raw)


def test_summary_matches_only_current_encoded_subset_and_its_batch_fingerprints(tmp_path):
    from naiyue_rag import BatchProcessor
    from naiyue_rag.core.encoding_snapshot import EncodingSnapshot
    from naiyue_rag.core.ingestion_encoding_summary import IngestionEncodingSummary
    bundle,old=snapshot_for(tmp_path);cfg=bundle.encoding_settings
    doc=bundle.documents[0].id
    inputs=[r.input for r in bundle.encoding_result.records if r.input.source_document_id==doc]
    result=BatchProcessor(cfg,Dense(cfg),Sparse(cfg)).process(inputs)
    fresh=EncodingSnapshot.from_result(KB,result)
    records={r.input.item_id:r for r in fresh.records};origins={o['item_id']:o for o in fresh.origins}
    raw=old.to_dict()
    for i,(record,origin) in enumerate(zip(raw['records'],raw['origins'],strict=True)):
        uid=record['input']['item_id']
        if uid in records:raw['records'][i]=records[uid].to_dict();raw['origins'][i]=origins[uid]
        else:origin.update(kind='reused',source_bundle_id='f'*64)
    merged=EncodingSnapshot.from_dict(raw);n=len(merged.records);changed=len(inputs)
    summary=IngestionEncodingSummary(n,changed,n-changed,result.report)
    summary.validate_snapshot(merged)
    assert summary.job_report.usage==result.report.usage
    assert summary.job_report.input_count==changed<n
    broken=copy.deepcopy(merged);next(o for o in broken.origins if o['kind']=='encoded')['source_job_id']='0'*32
    with pytest.raises(StorageError):summary.validate_snapshot(broken)
    with pytest.raises(StorageError):IngestionEncodingSummary(n,changed,n,result.report)


def test_zero_encoding_has_no_current_job_and_empty_snapshot_keeps_knowledge_base(tmp_path):
    from naiyue_rag.core.encoding_snapshot import EncodingSnapshot
    from naiyue_rag.core.ingestion_encoding_summary import IngestionEncodingSummary
    _,snapshot=snapshot_for(tmp_path);raw=snapshot.to_dict()
    for origin in raw['origins']:origin.update(kind='reused',source_bundle_id='a'*64)
    reused=EncodingSnapshot.from_dict(raw);n=len(reused.records)
    summary=IngestionEncodingSummary(n,0,n,None);summary.validate_snapshot(reused)
    assert summary.to_dict()['job_report'] is None
    raw['records']=[];raw['origins']=[]
    empty=EncodingSnapshot.from_dict(raw)
    assert empty.knowledge_base_id==KB
    IngestionEncodingSummary(0,0,0,None).validate_snapshot(empty)


def test_current_receipt_summary_allows_zero_encoding_without_reusing_past_report(receipt):
    from naiyue_rag import IngestionReceipt,IngestionEncodingSummary
    n=receipt.active.version.chunk_count
    summary=IngestionEncodingSummary(n,0,n,None)
    current=IngestionReceipt('activated',receipt.active,0,0,3,0,None,encoding_summary=summary)
    wire=current.to_dict()
    assert wire['encoding_report'] is None and wire['encoding_summary']['encoded_chunk_count']==0
    assert IngestionReceipt.from_dict(wire)==current
    assert 'encoding_summary' not in receipt.to_dict()
    assert IngestionReceipt.from_dict(receipt.to_dict())==receipt
    from naiyue_rag.core.errors import IngestionJobError
    with pytest.raises(IngestionJobError):
        IngestionReceipt('activated',receipt.active,0,0,3,0,receipt.encoding_report,encoding_summary=summary)
