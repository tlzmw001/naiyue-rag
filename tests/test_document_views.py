"""Strict metadata-only results and pure projections over validated saved sources."""
import copy
import hashlib
import json
import pytest
from naiyue_rag.storage import DocumentInfo,DocumentList,DocumentDetail,ActiveVersion,IndexVersion
from naiyue_rag.storage.document_views import project_list,project_detail
from naiyue_rag.core.errors import StorageError
from test_index_versions import version
from test_storage_bundle import KB,PRIVATE,make_bundle


def document_id(path,kb=KB):
    return 'doc-'+hashlib.sha256(json.dumps([kb,path],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def info(path='L2_A.md',count=2):
    return DocumentInfo(document_id(path),path,'a'*64,100,count)


def active(documents=1,chunks=2):
    return ActiveVersion(1,IndexVersion.from_dict(version(document_count=documents,chunk_count=chunks)))


def test_metadata_views_roundtrip_copy_and_repr():
    item=info();source=[item];ids=['unit-'+'1'*64,'unit-'+'2'*64]
    listing=DocumentList(active(),source);detail=DocumentDetail(active(),item,ids)
    source.clear();ids.clear()
    assert len(listing.documents)==1 and len(detail.chunk_ids)==2
    for obj in (item,listing,detail):
        wire=json.loads(json.dumps(obj.to_dict()))
        assert type(obj).from_dict(wire).to_dict()==obj.to_dict()
        assert 'L2_A.md' not in repr(obj) and KB not in repr(obj)
    wire=listing.to_dict();wire['documents'][0]['source_path']=PRIVATE
    assert listing.documents[0].source_path=='L2_A.md'
    wire=detail.to_dict();wire['chunk_ids'].clear()
    assert len(detail.chunk_ids)==2
    assert set(item.to_dict())=={'document_id','source_path','source_sha256','size_bytes','chunk_count'}


@pytest.mark.parametrize('field,value',[
    ('document_id','a'*64),('document_id','doc-'+'A'*64),('source_sha256','x'),
    ('size_bytes',True),('size_bytes',-1),('chunk_count',False),('chunk_count',-1),
    ('source_path','/tmp/a.md'),('source_path','../a.md'),('source_path','a/../b.md'),
    ('source_path','a//b.md'),('source_path','a\\b.md'),('source_path','C:/a.md'),
    ('source_path','a.pdf'),('source_path','a\x00.md'),('source_path',None)])
def test_invalid_document_info(field,value,caplog):
    raw=info().to_dict();raw[field]=value
    with pytest.raises(StorageError,match='document_invalid_request'):DocumentInfo.from_dict(raw)
    assert PRIVATE not in caplog.text


@pytest.mark.parametrize('kind',['info','list','detail'])
@pytest.mark.parametrize('fault',['extra','missing','wrong-container'])
def test_closed_dto_fields(kind,fault):
    cls,raw={'info':(DocumentInfo,info().to_dict()),
        'list':(DocumentList,DocumentList(active(),[info()]).to_dict()),
        'detail':(DocumentDetail,DocumentDetail(active(),info(),['unit-'+'1'*64,'unit-'+'2'*64]).to_dict())}[kind]
    if fault=='extra':raw['extra']=PRIVATE
    elif fault=='missing':raw.pop(next(iter(raw)))
    else:raw=[]
    with pytest.raises(StorageError,match='document_invalid_request'):cls.from_dict(raw)


@pytest.mark.parametrize('fault',['no-active','counts','duplicates','unsorted','cross-kb','mutated-active'])
def test_list_state_and_identity_contract(fault):
    items=[info('a.md',1),info('b.md',1)];selected=active(2,2)
    if fault=='no-active':selected=None
    elif fault=='counts':selected=active(2,3)
    elif fault=='duplicates':items[1]=items[0]
    elif fault=='unsorted':items.reverse()
    elif fault=='cross-kb':items[0]=DocumentInfo(document_id('a.md','other'),'a.md','a'*64,100,1)
    else:object.__setattr__(selected,'revision',True)
    with pytest.raises(StorageError,match='document_invalid_request'):DocumentList(selected,items)


@pytest.mark.parametrize('fault',['no-active','no-document','count','duplicate','syntax','cross-kb','empty-library'])
def test_detail_state_and_identity_contract(fault):
    item=info();selected=active();ids=['unit-'+'1'*64,'unit-'+'2'*64]
    if fault=='no-active':selected=None
    elif fault=='no-document':item=None
    elif fault=='count':ids.pop()
    elif fault=='duplicate':ids[1]=ids[0]
    elif fault=='syntax':ids[1]='chunk-'+'2'*64
    elif fault=='cross-kb':item=DocumentInfo(document_id('L2_A.md','other'),'L2_A.md','a'*64,100,2)
    else:selected=active(0,0)
    with pytest.raises(StorageError,match='document_invalid_request'):DocumentDetail(selected,item,ids)


def test_empty_states_are_distinct():
    absent=DocumentList(None,[]);empty=DocumentList(active(0,0),[])
    assert absent.active is None and empty.active is not None
    assert DocumentDetail(None,None,[]).to_dict()==dict(active=None,document=None,chunk_ids=[])
    assert DocumentDetail(active(),None,[]).document is None
    blank=DocumentInfo(document_id('blank.md'),'blank.md','b'*64,0,0)
    assert DocumentDetail(active(1,0),blank,[]).document.size_bytes==0


def test_projection_order_counts_and_source_identity(tmp_path):
    bundle=make_bundle(tmp_path);bundle.documents.reverse();bundle.chunks.reverse()
    selected=ActiveVersion(1,IndexVersion.from_dict(version(document_count=len(bundle.documents),chunk_count=len(bundle.chunks))))
    listing=project_list(selected,bundle)
    assert [d.source_path for d in listing.documents]==['L1_Module.md','L2_A.md','L2_A_测试用例.md']
    for item in listing.documents:
        doc=next(d for d in bundle.documents if d.id==item.document_id)
        assert item.source_sha256==doc.metadata['source_sha256']
        assert item.size_bytes==len(doc.text.encode('utf-8'))
        group=sorted([c for c in bundle.chunks if c.source_ref==doc.id],key=lambda c:(c.start_offset,c.end_offset,c.id))
        detail=project_detail(selected,bundle,doc.id)
        assert item.chunk_count==len(group) and detail.chunk_ids==[c.id for c in group]
    assert project_detail(selected,bundle,'doc-'+'0'*64).document is None


@pytest.mark.parametrize('fault',['unknown-source','duplicate-chunk','duplicate-document'])
def test_projection_rejects_internal_inconsistency(tmp_path,fault):
    bundle=make_bundle(tmp_path)
    selected=ActiveVersion(1,IndexVersion.from_dict(version(document_count=len(bundle.documents),chunk_count=len(bundle.chunks))))
    if fault=='unknown-source':bundle.chunks[0].source_ref='doc-'+'f'*64
    elif fault=='duplicate-chunk':bundle.chunks.append(copy.deepcopy(bundle.chunks[0]))
    else:bundle.documents.append(copy.deepcopy(bundle.documents[0]))
    with pytest.raises(StorageError,match='document_integrity_failed'):project_list(selected,bundle)
