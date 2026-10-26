"""Pure source merging and semantic profile comparison; no IO in the planner."""
from dataclasses import replace
import copy
import pytest
from naiyue_rag.ingestion.file_integrity import plan_ingestion
from naiyue_rag.core.errors import IngestionJobError
from naiyue_rag import MarkdownLoader,IngestionSettings
from naiyue_rag.storage import ActiveVersion,IndexVersion,ChromaSettings,BM25Settings
from test_index_versions import version
from test_storage_bundle import make_bundle,KB
from test_encoding_settings import config


def selected(bundle):
    result=bundle.encoding_result
    return ActiveVersion(1,IndexVersion.from_dict(version(document_count=len(bundle.documents),
        chunk_count=len(bundle.chunks),source_fingerprint=bundle.relations['source_fingerprint'],
        model_space_id=result.model_space_id,representation_id=result.representation_id,
        tokenizer_id=result.tokenizer_id,dimensions=result.dimensions)))


def plan(bundle,incoming,**changes):
    args=dict(knowledge_base_id=KB,ingestion_settings=bundle.ingestion_settings,
        encoding_settings=bundle.encoding_settings,tokenizer_id=bundle.encoding_result.tokenizer_id,
        chroma_settings=ChromaSettings('knowledge_hub',2),bm25_settings=BM25Settings(1.5,.75),force=False)
    args.update(changes)
    return plan_ingestion(selected(bundle),bundle,incoming,**args)


def test_same_sources_reuse_and_empty_input_retains_history(tmp_path):
    bundle=make_bundle(tmp_path)
    current=plan(bundle,list(reversed(bundle.documents)))
    assert current.reuse_active and not current.added_ids and not current.updated_ids
    assert current.unchanged_ids==sorted(d.id for d in bundle.documents) and current.retained_ids==[]
    empty=plan(bundle,[])
    assert empty.reuse_active and empty.retained_ids==current.unchanged_ids
    assert empty.unchanged_ids==[] and len(empty.merged_documents)==3
    empty.merged_documents[0].text='mutated'
    assert bundle.documents[0].text!='mutated'


def test_update_add_and_same_bytes_different_paths(tmp_path):
    bundle=make_bundle(tmp_path);source=tmp_path/'source'
    (source/'L1_Module.md').write_text('# 新模块\n\n更新规则。\n')
    (source/'L2_Copy.md').write_bytes((source/'L2_A.md').read_bytes())
    loader=MarkdownLoader(source,KB,4096)
    incoming=[loader.load('L2_Copy.md'),loader.load('L1_Module.md')]
    result=plan(bundle,incoming)
    assert not result.reuse_active and len(result.merged_documents)==4
    assert result.added_ids==[incoming[0].id] and result.updated_ids==[incoming[1].id]
    assert len(result.retained_ids)==2 and result.unchanged_ids==[]
    assert [d.id for d in result.merged_documents]==sorted(d.id for d in result.merged_documents)
    copies=[d for d in result.merged_documents if d.metadata['source_path'] in ('L2_A.md','L2_Copy.md')]
    assert len({d.id for d in copies})==2 and len({d.metadata['source_sha256'] for d in copies})==1


@pytest.mark.parametrize('field',['chunk-size','overlap','model','prefix','tokenizer','collection','k1','b','force'])
def test_semantic_profile_changes_rebuild(tmp_path,field):
    bundle=make_bundle(tmp_path);args={}
    if field=='chunk-size':args['ingestion_settings']=IngestionSettings(50,10)
    elif field=='overlap':args['ingestion_settings']=IngestionSettings(40,5)
    elif field=='model':args['encoding_settings']=config(embedding={'model_revision':'v2'})
    elif field=='prefix':args['encoding_settings']=config(representation={'document_prefix':'other: '})
    elif field=='tokenizer':args['tokenizer_id']='b'*64
    elif field=='collection':args['chroma_settings']=ChromaSettings('changed_collection',2)
    elif field=='k1':args['bm25_settings']=BM25Settings(1.2,.75)
    elif field=='b':args['bm25_settings']=BM25Settings(1.5,.5)
    else:args['force']=True
    result=plan(bundle,bundle.documents,**args)
    assert not result.reuse_active and result.updated_ids==[] and len(result.unchanged_ids)==3


def test_execution_batch_sizes_do_not_change_semantic_identity(tmp_path):
    bundle=make_bundle(tmp_path)
    assert plan(bundle,bundle.documents,encoding_settings=config(runtime={'batch_size':1}),
        chroma_settings=ChromaSettings('knowledge_hub',1)).reuse_active


@pytest.mark.parametrize('fault',['duplicate','cross-kb','wrong-id','bad-source','bad-force','missing-base'])
def test_invalid_plan_cannot_become_reuse(tmp_path,fault):
    bundle=make_bundle(tmp_path);incoming=copy.deepcopy(bundle.documents);args={}
    if fault=='duplicate':incoming.append(incoming[0])
    elif fault=='cross-kb':incoming[0].metadata['knowledge_base_id']='other'
    elif fault=='wrong-id':incoming[0].id='doc-'+'f'*64
    elif fault=='bad-source':incoming[0].text+='corrupt'
    elif fault=='bad-force':args['force']=1
    else:
        with pytest.raises(IngestionJobError):
            plan_ingestion(selected(bundle),None,[],knowledge_base_id=KB,
                ingestion_settings=bundle.ingestion_settings,encoding_settings=bundle.encoding_settings,
                tokenizer_id=bundle.encoding_result.tokenizer_id,chroma_settings=ChromaSettings('knowledge_hub',2),
                bm25_settings=BM25Settings(1.5,.75),force=False)
        return
    with pytest.raises(IngestionJobError):plan(bundle,incoming,**args)


def test_first_empty_plan_is_not_a_reusable_success():
    result=plan_ingestion(None,None,[],knowledge_base_id=KB,ingestion_settings=IngestionSettings(40,10),
        encoding_settings=config(),tokenizer_id='a'*64,chroma_settings=ChromaSettings('knowledge_hub',2),
        bm25_settings=BM25Settings(1.5,.75),force=False)
    assert not result.reuse_active and result.merged_documents==[]
