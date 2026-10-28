"""No-model removal and native incremental/full equivalence on synthetic sources."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from naiyue_rag.storage.bundle_encoding import bundle_encoding
from test_ingestion_pipeline import setup_job
from test_document_removal import target


def test_removal_copies_pairs_without_preparing_or_encoding_retained_documents(setup_job,monkeypatch):
    job,dense,_=setup_job;first=job.run(expected_revision=0);info=target(job)
    old=job.manager.bundles.load(first.active.version.bundle_id);before=dense.calls
    def deny(*args,**kwargs):pytest.fail('retained documents must not encode')
    monkeypatch.setattr(job.batch_processor,'process',deny)
    monkeypatch.setattr(job.chunker,'split_document',deny)
    receipt=job.remove_document(info.document_id,expected_revision=1)
    assert receipt.encoding_report is None and dense.calls==before
    assert receipt.encoding_summary.encoded_chunk_count==0
    current=job.manager.bundles.load(receipt.active.version.bundle_id)
    expected={r.input.item_id:r for r in bundle_encoding(old).records if r.input.source_document_id!=info.document_id}
    assert {r.input.item_id for r in bundle_encoding(current).records}==set(expected)
    for record in bundle_encoding(current).records:
        previous=expected[record.input.item_id]
        assert record.input.to_dict()==previous.input.to_dict() and record.dense_vector==previous.dense_vector
        assert record.sparse.to_dict()==previous.sparse.to_dict()
    assert all(o['kind']=='reused' and o['source_bundle_id']==first.active.version.bundle_id for o in current.encoding_snapshot.origins)
    assert job.manager.bundles.load(first.active.version.bundle_id).to_dict()==old.to_dict()


def native_acceptance(root,mode,policy):
    import socket
    def deny(*args,**kwargs):raise AssertionError('unexpected network')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=deny
    import httpx
    from naiyue_rag import (IngestionPipeline,IngestionSettings,EncodingSettings,OpenAICompatibleEmbedding,
        DenseEncoder,SparseEncoder,BatchProcessor,QueryEncoder,QueryPipeline,HybridSearch,KnowledgeReader,
        CoreReranker,ResponseBuilder,EvidenceSettings,prepare_knowledge_base,prepare_document_encoding_inputs)
    from naiyue_rag.storage import (DocumentManager,BundleStore,VectorUpserter,BM25Indexer,BM25Store,
        prepare_index_bundle,ChromaSettings,BM25Settings)
    from test_storage_bundle import ingredients,storage_settings
    from test_sparse_encoding_settings import sparse_config
    from test_openai_embedding import payload
    from test_hybrid_search import config as hybrid_config
    from test_reranking import config as rerank_config
    if mode=='incremental':
        data=ingredients(root);cfg=data['encoding_settings'];ing=IngestionSettings(40,10,chunking_policy=policy)
    else:
        seed=json.loads((root/'seed.json').read_text());cfg=EncodingSettings.from_dict(seed['encoding'])
        ing=IngestionSettings.from_dict(seed['ingestion'])
    storage=storage_settings(root);cs=ChromaSettings('acceptance_native',2);bs=BM25Settings(1.5,.75);seen=[]
    def respond(request):
        inputs=json.loads(request.content)['input'];seen.extend(inputs);raw=payload(len(inputs))
        # The provider fixture returns rows in reverse order; index owns the input mapping.
        for row in raw['data']:
            text=inputs[row['index']]
            digest=hashlib.sha256(text.encode()).digest()
            row['embedding']=[1+int.from_bytes(digest[i:i+4],'big')/(2**32) for i in (0,4,8)]
        raw['usage']={'prompt_tokens':7*len(inputs),'total_tokens':7*len(inputs)}
        return httpx.Response(200,json=raw)
    httpx.HTTPTransport=lambda **kwargs:httpx.MockTransport(respond)
    with OpenAICompatibleEmbedding(cfg,api_key='SYNTHETIC-NOT-A-KEY') as provider:
        dense=DenseEncoder(cfg,provider);sparse=SparseEncoder(cfg,sparse_config(root));batch=BatchProcessor(cfg,dense,sparse)
        pipeline=IngestionPipeline(storage,ing,batch,cs,bs,knowledge_base_root=root/'source',project_root=root)
        encoder=QueryEncoder(cfg,dense,sparse);reader=KnowledgeReader(storage);update_summary=None
        if mode=='incremental':
            # A genuine v1-format bundle, encoded by the same deterministic SDK boundary.
            chunks,relations,_=prepare_knowledge_base(data['documents'],pipeline.chunker,text_mode=cfg.representation.document_text_mode)
            encoded=batch.process(prepare_document_encoding_inputs(data['documents'],chunks,cfg))
            legacy=prepare_index_bundle(data['documents'],chunks,relations,encoded,knowledge_base_id=storage.knowledge_base_id,
                encoding_settings=cfg,ingestion_settings=ing)
            uid=BundleStore(storage).save(legacy).bundle_id
            VectorUpserter(storage,cs,project_root=root).build(uid);BM25Indexer(storage,bs).build(uid)
            first=pipeline.manager.activate(uid,expected_revision=0).active
            pin=QueryPipeline(pipeline.manager,encoder).prepare('  TC-01  ')
            removed=next(d for d in legacy.documents if d.metadata['source_path']=='L2_A.md')
            (root/'source/L1_Module.md').write_text('# 模块v2\n\nfeature_x=0时保留错误码，threshold=0.7。\n')
            (root/'source/L2_D.md').write_text('# 新需求D\n\nfeature_x=2，检查cvr_ltv和TC-02。\n')
            before=len(seen);updated=pipeline.run(expected_revision=first.revision)
            assert len(seen)-before==updated.encoding_summary.encoded_chunk_count
            assert updated.encoding_summary.reused_chunk_count>0
            update_summary=updated.encoding_summary.to_dict()
            source_bytes=(root/'source/L2_A.md').read_bytes();before=len(seen)
            receipt=pipeline.remove_document(removed.id,expected_revision=updated.active.revision)
            assert len(seen)==before and receipt.encoding_report is None
            assert receipt.encoding_summary.encoded_chunk_count==0
            assert (root/'source/L2_A.md').read_bytes()==source_bytes
        else:receipt=pipeline.run(expected_revision=0,force=True)
        bundle=BundleStore(storage).load(receipt.active.version.bundle_id)
        keyword=BM25Store(storage,bs)
        path,header,rows,records=keyword._prepare(receipt.active.version.bundle_id)
        native=keyword._load_index(path,header,rows,records);weights={}
        for term,col in native.vocab_dict.items():
            start,end=map(int,native.scores['indptr'][col:col+2])
            weights[term]={rows[int(row)]['item_id']:float(weight) for row,weight in zip(
                native.scores['indices'][start:end],native.scores['data'][start:end],strict=True)}
        bm25=dict(rows=rows,vocab=sorted(native.vocab_dict),avgdl=header['avgdl'],
            document_count=native.scores['num_docs'],parameters=header['parameters'])
        (root/'source').rename(root/'source-offline')
        if mode=='incremental':
            old=reader.read_lines(pin,removed.id,start_line=1,end_line=len(removed.metadata['line_starts']),max_characters=100000)
            assert old['text']==removed.text and old['active']==first.to_dict()
            assert removed.id not in {d.id for d in bundle.documents}
        builder=ResponseBuilder(reader,EvidenceSettings(100000,1000000));queries=[]
        for statistics in ('global','scope'):
            for restricted in (False,True):
                scope=sorted(d.id for d in bundle.documents if d.metadata['source_path'] in ('L1_Module.md','L2_D.md')) if restricted else None
                settings=hybrid_config(dense_top_k=20,sparse_top_k=20,fusion_top_k=20,bm25_statistics_scope=statistics)
                hybrid=HybridSearch(pipeline.manager,encoder,settings).search('  feature_x threshold 0.7 TC-01  ',scope_document_ids=scope)
                ranked=CoreReranker(rerank_config(enabled=False,top_k=20)).rerank(hybrid);response=builder.build(ranked)
                before=len(seen)
                for doc in bundle.documents:
                    if doc.id not in hybrid.prepared.document_ids:continue
                    read=reader.read_lines(hybrid.prepared,doc.id,start_line=1,end_line=len(doc.metadata['line_starts']),max_characters=100000)
                    assert read['text']==doc.text
                    reader.related_documents(hybrid.prepared,doc.id,max_links=100)
                for chunk in bundle.chunks:
                    if chunk.id in hybrid.prepared.chunk_ids:
                        assert reader.read_chunk(hybrid.prepared,chunk.id,max_characters=100000)['chunk']==chunk.to_dict()
                assert len(seen)==before
                queries.append(dict(statistics=statistics,scope=scope,
                    dense={h.chunk.id:h.distance for h in hybrid.dense_hits},sparse={h.chunk.id:h.score for h in hybrid.sparse_hits},
                    fused={h.chunk.id:h.score for h in hybrid.hits},evidence={e['chunk_id']:
                        {k:e[k] for k in ('document_id','source_path','source_sha256','body_span','body','contexts','kind')} for e in response['evidence']}))
        state=dict(encoding=cfg.to_dict(),ingestion=ing.to_dict(),documents=[d.to_dict() for d in bundle.documents],
            chunks=[c.to_dict() for c in bundle.chunks],relations=bundle.relations,
            pairs=[dict(input=r.input.to_dict(),vector=r.dense_vector,sparse=r.sparse.to_dict()) for r in bundle_encoding(bundle).records],
            summary=receipt.encoding_summary.to_dict(),update_summary=update_summary,queries=queries,bm25=bm25,weights=weights)
    print(json.dumps(state,ensure_ascii=False))


def launch(root,mode,policy):
    script='''
import sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_incremental_acceptance import native_acceptance
native_acceptance(Path(sys.argv[2]),sys.argv[3],sys.argv[4])
'''
    child=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).resolve().parents[1]),str(root),mode,policy],
        cwd=root,env={'HOME':str(root),'PATH':os.defpath,'OMP_NUM_THREADS':'1','NYR_NATIVE_DIAGNOSTICS':'1'},
        capture_output=True,text=True,timeout=120)
    assert child.returncode==0,child.stderr
    return json.loads(child.stdout)


@pytest.mark.parametrize('policy',['markdown-source-v1','markdown-source-zh-v2'])
def test_native_incremental_and_full_paths_have_same_final_sources_scores_and_evidence(tmp_path,policy):
    incremental=tmp_path/'incremental';baseline=tmp_path/'baseline';incremental.mkdir();baseline.mkdir()
    observed=launch(incremental,'incremental',policy)
    source=baseline/'source';source.mkdir()
    for doc in observed['documents']:
        (source/doc['metadata']['source_path']).write_bytes(doc['text'].encode('utf-8'))
    (baseline/'seed.json').write_text(json.dumps(dict(encoding=observed['encoding'],ingestion=observed['ingestion'])))
    expected=launch(baseline,'full',policy)
    for field in ('documents','chunks','relations','pairs'):assert observed[field]==expected[field]
    assert observed['bm25']==expected['bm25']
    assert observed['weights'].keys()==expected['weights'].keys()
    for term,weights in observed['weights'].items():
        assert weights==pytest.approx(expected['weights'][term],rel=1e-12,abs=1e-15)
    assert observed['summary']['encoded_chunk_count']==0 and observed['summary']['job_report'] is None
    assert expected['summary']['encoded_chunk_count']==len(expected['pairs'])
    assert observed['update_summary']['encoded_chunk_count']<observed['update_summary']['total_chunk_count']
    for actual,wanted in zip(observed['queries'],expected['queries'],strict=True):
        assert actual['statistics']==wanted['statistics'] and actual['scope']==wanted['scope']
        assert actual['evidence']==wanted['evidence']
        # Native float32 weights/distances: same tolerance as existing audits.
        for field in ('dense','sparse','fused'):
            assert actual[field]==pytest.approx(wanted[field],rel=1e-6,abs=1e-6)
