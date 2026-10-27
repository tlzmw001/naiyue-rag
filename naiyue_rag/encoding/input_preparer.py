"""Validate M2 source/view contracts and prepare deterministic document/query inputs."""
from ..core.encoding_settings import validate_encoding_settings
from ..core.encoding_types import EncodingInput,fail_encoding,text_sha
from ..core.errors import EncodingError
from ..ingestion.chunk_preparation import ChunkRefiner
from ..ingestion.document_relations import _registry


def _input(uid,kind,text,cfg,doc=None,span=None):
    prefix=cfg.representation.document_prefix if kind=='document' else cfg.representation.query_prefix
    embedded=prefix+text
    if len(embedded.encode())>cfg.runtime.max_input_utf8_bytes or len(embedded.encode())>cfg.runtime.max_batch_input_utf8_bytes:
        fail_encoding('encoding_input_limit')
    return EncodingInput(uid,kind,doc.metadata['knowledge_base_id'] if doc else None,
        doc.id if doc else None,doc.metadata['source_sha256'] if doc else None,span,text,embedded,
        text_sha(text),text_sha(embedded),cfg.model_space_id,cfg.representation_id,text_sha(text) if kind=='query' else None)


def prepare_document_encoding_inputs(documents,chunks,settings):
    return _prepare_document_encoding_inputs(documents,chunks,settings,job_limits=True)


def _prepare_document_encoding_inputs(documents,chunks,settings,*,job_limits):
    validate_encoding_settings(settings)
    try:
        if type(documents) is not list or type(chunks) is not list:raise ValueError()
        registry,_,_=_registry(documents)
        ids=set();output=[]
        for chunk in chunks:
            if chunk.id in ids or chunk.source_ref not in registry:raise ValueError()
            ids.add(chunk.id);doc=registry[chunk.source_ref]
            expected=ChunkRefiner().transform(doc,[chunk],text_mode=settings.representation.document_text_mode)[0]
            if chunk.metadata.get('retrieval_view')!=expected.metadata['retrieval_view']:raise ValueError()
            text=expected.metadata['retrieval_view']['text']
            if settings.representation.text_layout=='contexts_then_view':
                text='\n'.join([c['text'] for c in expected.metadata['contexts']]+[text])
            output.append(_input(chunk.id,'document',text,settings,doc,expected.metadata['body_span']))
        if job_limits:plan_encoding_batches(output,settings)
        return output
    except EncodingError:raise
    except Exception:fail_encoding('invalid_encoding_input')


def prepare_query_encoding_input(query,settings):
    validate_encoding_settings(settings)
    try:
        if type(query) is not str or not query.strip():raise ValueError()
        query=query.strip()
        return _input('query-'+text_sha(query),'query',query,settings)
    except EncodingError:raise
    except Exception:fail_encoding('invalid_encoding_input')


def validate_input_profile(item,settings):
    if not isinstance(item,EncodingInput):fail_encoding('invalid_encoding_input')
    item.to_dict()
    if item.model_space_id!=settings.model_space_id or item.representation_id!=settings.representation_id:
        fail_encoding('encoding_identity_mismatch')
    prefix=settings.representation.document_prefix if item.kind=='document' else settings.representation.query_prefix
    if item.embedding_text!=prefix+item.retrieval_text:fail_encoding('invalid_encoding_input')


def plan_encoding_batches(inputs,settings):
    validate_encoding_settings(settings)
    if type(inputs) is not list:fail_encoding('invalid_encoding_input')
    if len(inputs)>settings.runtime.max_inputs:fail_encoding('encoding_input_limit')
    ids=set();batches=[];batch=[];size=0
    for item in inputs:
        validate_input_profile(item,settings)
        if item.item_id in ids:fail_encoding('invalid_encoding_input')
        ids.add(item.item_id);count=len(item.embedding_text.encode())
        if count>settings.runtime.max_input_utf8_bytes or count>settings.runtime.max_batch_input_utf8_bytes:fail_encoding('encoding_input_limit')
        if batch and (len(batch)>=settings.runtime.batch_size or size+count>settings.runtime.max_batch_input_utf8_bytes):
            batches.append(batch);batch=[];size=0
        batch.append(item);size+=count
    if batch:batches.append(batch)
    if len(batches)>settings.runtime.max_requests:fail_encoding('encoding_request_limit')
    return batches
