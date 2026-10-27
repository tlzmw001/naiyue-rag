"""Copy audited document pairs into a self-contained new generation."""
from ..core.encoding_snapshot import EncodingSnapshot,StoredEncodedRecord
from ..core.ingestion_encoding_summary import IngestionEncodingSummary
from ..core.encoded_types import EncodingResult
from ..core.errors import StorageError
from ..storage.artifact_bundle_v2 import IndexBundleV2
from ..storage.bundle_encoding import bundle_encoding


def compose_encoding_snapshot(documents,chunks,result,*,base,base_bundle_id,reuse_document_ids,
                               knowledge_base_id,encoding_settings,tokenizer_id):
    registry={d.id:d for d in documents};reuse=set(reuse_document_ids)
    old_records={};old_origins={}
    if reuse:
        if base is None:raise StorageError('bundle_source_mismatch')
        base.to_dict()
        old=base.encoding_snapshot if type(base) is IndexBundleV2 else EncodingSnapshot.from_result(knowledge_base_id,bundle_encoding(base))
        old_records={r.input.item_id:r for r in old.records}
        old_origins={o['item_id']:o for o in old.origins}
    fresh_records={};fresh_origins={};report=None
    if result is not None:
        if type(result) is not EncodingResult:raise StorageError('invalid_index_bundle')
        result=EncodingResult.from_dict(result.to_dict());report=result.report
        fresh=EncodingSnapshot.from_result(knowledge_base_id,result)
        fresh_records={r.input.item_id:r for r in fresh.records};fresh_origins={o['item_id']:o for o in fresh.origins}
    records=[];origins=[]
    for chunk in chunks:
        if chunk.source_ref in reuse:
            record=old_records.get(chunk.id);origin=dict(old_origins.get(chunk.id,{}))
            origin.update(kind='reused',source_bundle_id=base_bundle_id)
        else:
            record=fresh_records.get(chunk.id);origin=fresh_origins.get(chunk.id)
        if record is None or record.input.source_document_id!=chunk.source_ref or \
                record.input.source_sha256!=registry[chunk.source_ref].metadata['source_sha256']:
            raise StorageError('bundle_source_mismatch')
        records.append(StoredEncodedRecord(record.input,record.dense_vector,record.sparse));origins.append(origin)
    cfg=encoding_settings
    snapshot=EncodingSnapshot(knowledge_base_id,cfg.model_space_id,cfg.representation_id,tokenizer_id,
        cfg.embedding.expected_dimensions,records,origins)
    encoded=len(fresh_records)
    summary=IngestionEncodingSummary(len(records),encoded,len(records)-encoded,report)
    summary.validate_snapshot(snapshot)
    return snapshot,summary
