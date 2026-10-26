"""Explicit versioned source reading, actual positions and bounded relation projection."""
from dataclasses import replace
import copy
import json
import pytest
from naiyue_rag.core.errors import QueryJobError,StorageError
from naiyue_rag.storage import BundleStore,ChromaStore,BM25Store
from test_query_preparation import job
from test_document_manager import prepared,second
from test_query_encoding import QUERY,PRIVATE


def reader(pipeline):
    from naiyue_rag import KnowledgeReader
    return KnowledgeReader(pipeline.storage_settings)


def test_complete_case_and_actual_lines_without_sdk_or_latest(job,monkeypatch):
    pipeline,*_=job;ready=pipeline.prepare(QUERY);bundle=pipeline.manager.bundles.load(ready.active.version.bundle_id)
    case=next(c for c in bundle.chunks if c.metadata['kind']=='test_case')
    def deny(*args,**kwargs):pytest.fail('reading must not use SDK or latest catalog')
    monkeypatch.setattr(ChromaStore,'audit',deny);monkeypatch.setattr(BM25Store,'audit',deny)
    monkeypatch.setattr(pipeline.manager.catalog,'read',deny)
    result=reader(pipeline).read_chunk(ready,case.id,max_characters=10000)
    assert set(result)=={'active','chunk'} and result['active']==ready.active.to_dict() and result['chunk']==case.to_dict()
    span=case.metadata['body_span'];lines=reader(pipeline).read_lines(ready,case.source_ref,
        start_line=span['line_start'],end_line=span['line_end'],max_characters=10000)
    assert case.text in lines['text'] and lines['span']['source_sha256']==case.metadata['source_sha256']
    assert lines['source_sha256']==case.metadata['source_sha256']
    result['chunk']['text']=PRIVATE
    assert reader(pipeline).read_chunk(ready,case.id,max_characters=10000)['chunk']==case.to_dict()
    assert json.loads(json.dumps(lines))==lines


def test_both_directions_and_name_pairing_keep_provenance(job):
    pipeline,*_=job;ready=pipeline.prepare(QUERY);bundle=pipeline.manager.bundles.load(ready.active.version.bundle_id)
    for document in bundle.documents:
        result=reader(pipeline).related_documents(ready,document.id,max_links=100)
        expected=sorted([edge for edge in bundle.relations['edges'] if document.id in
            (edge['from_document_id'],edge['to_document_id'])],key=lambda edge:edge['edge_id'])
        assert result['relations']==expected and result['omitted_by_scope']==0
        assert result['active']==ready.active.to_dict()
        if expected:
            result['relations'][0]['quote']=PRIVATE
            assert PRIVATE not in json.dumps(reader(pipeline).related_documents(ready,document.id,max_links=100))


def test_scope_never_follows_references_automatically(job):
    pipeline,*_=job;bundle=pipeline.manager.bundles.load(pipeline.manager.open_active().version.bundle_id)
    doc=next(d for d in bundle.documents if d.metadata['source_path']=='L2_A.md')
    ready=pipeline.prepare(QUERY,scope_document_ids=[doc.id])
    result=reader(pipeline).related_documents(ready,doc.id,max_links=100)
    expected=sum(doc.id in (e['from_document_id'],e['to_document_id']) for e in bundle.relations['edges'])
    assert result['relations']==[] and result['omitted_by_scope']==expected
    other=next(d for d in bundle.documents if d.id!=doc.id)
    with pytest.raises(QueryJobError,match='query_invalid_scope'):reader(pipeline).read_lines(ready,other.id,start_line=1,end_line=1,max_characters=1000)


@pytest.mark.parametrize('method',['chunk','lines','links'])
def test_read_budget_is_explicit_not_silent_truncation(job,method):
    pipeline,*_=job;ready=pipeline.prepare(QUERY);bundle=pipeline.manager.bundles.load(ready.active.version.bundle_id)
    case=next(c for c in bundle.chunks if c.metadata['kind']=='test_case')
    with pytest.raises(StorageError,match='document_limit_exceeded'):
        if method=='chunk':reader(pipeline).read_chunk(ready,case.id,max_characters=1)
        elif method=='lines':reader(pipeline).read_lines(ready,case.source_ref,start_line=1,end_line=2,max_characters=1)
        else:
            doc=next(d for d in bundle.documents if d.metadata['source_path']=='L2_A.md')
            reader(pipeline).related_documents(ready,doc.id,max_links=1)


@pytest.mark.parametrize('start,end,budget',[(0,1,100),(True,1,100),(2,1,100),(1,10000,100),(1,1,0),(1,1,True)])
def test_invalid_positions_and_limits_fail(job,start,end,budget):
    pipeline,*_=job;ready=pipeline.prepare(QUERY)
    with pytest.raises(QueryJobError,match='query_invalid_request'):reader(pipeline).read_lines(ready,ready.document_ids[0],
        start_line=start,end_line=end,max_characters=budget)


def test_forged_scope_projection_is_rejected_by_reader(job):
    pipeline,*_=job;ready=pipeline.prepare(QUERY)
    wrong=replace(ready,chunk_ids=ready.chunk_ids[:-1])
    with pytest.raises(QueryJobError,match='query_invalid_scope'):reader(pipeline).read_chunk(wrong,wrong.chunk_ids[0],max_characters=10000)


def test_new_active_and_removed_sources_do_not_rebind_reads(job,prepared,tmp_path):
    pipeline,active,bundle,*_=job;ready=pipeline.prepare(QUERY)
    manager,uid=second(prepared,tmp_path);new=manager.activate(uid,expected_revision=1).active
    (tmp_path/'source').rename(tmp_path/'source-offline')
    result=reader(pipeline).read_chunk(ready,ready.chunk_ids[0],max_characters=10000)
    assert new.revision==2 and result['active']==active.to_dict()
    assert result['chunk']==next(c.to_dict() for c in bundle.chunks if c.id==ready.chunk_ids[0])


def test_missing_bundle_io_failure_is_not_empty(job,monkeypatch):
    pipeline,*_=job;ready=pipeline.prepare(QUERY)
    def fail(*args,**kwargs):raise StorageError('bundle_read_failed')
    monkeypatch.setattr(BundleStore,'load',fail)
    with pytest.raises(StorageError):reader(pipeline).read_chunk(ready,ready.chunk_ids[0],max_characters=1000)


@pytest.mark.parametrize('separator',['','\n','\r\n','\r'])
def test_empty_document_and_actual_line_endings(job,tmp_path,separator):
    from naiyue_rag import QueryPipeline
    from test_ingestion_pipeline import job_for
    root=tmp_path/'line-case';(root/'source').mkdir(parents=True)
    text='' if not separator else separator.join(['# 模块','','正文A','正文B',''])
    (root/'source/lines.md').write_bytes(text.encode('utf-8'))
    ingester,*_=job_for(root);ingester.run(expected_revision=0)
    ready=QueryPipeline(ingester.manager,job[0].query_encoder).prepare(QUERY)
    from naiyue_rag import KnowledgeReader
    read=KnowledgeReader(ingester.settings)
    result=read.read_lines(ready,ready.document_ids[0],start_line=3 if separator else 1,end_line=4 if separator else 1,max_characters=1000)
    assert result['text']==('正文A'+separator+'正文B'+separator if separator else '')
    if separator:assert result['span']['line_start']==3 and result['span']['line_end']==4
    else:assert result['span'] is None
