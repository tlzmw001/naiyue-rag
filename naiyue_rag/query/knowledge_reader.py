"""Explicit source reads from a pinned bundle; no SDK, provider or latest lookup."""
from ..storage.bundle_encoding import bundle_encoding
import copy
import logging
import re
from ..core.storage_settings import StorageSettings
from ..core.query_preparation import PreparedQuery
from ..core.errors import QueryJobError,StorageError
from ..storage import BundleStore
from ..storage.bundle_store import _json_bytes
from ..ingestion.markdown_structure import source_span
from .prepared_scope import validate_prepared_scope

LOGGER=logging.getLogger(__name__)


def _invalid(code='query_invalid_request',active=None):
    LOGGER.error('query_failed stage=resources code=%s',code)
    raise QueryJobError('resources',code,active=active) from None


def _positive(value):
    if type(value) is not int or value<=0:_invalid()


def _id(value,prefix):
    if type(value) is not str or re.fullmatch(prefix+'-[0-9a-f]{64}',value) is None:_invalid()


class KnowledgeReader:
    def __init__(self,storage_settings):
        if type(storage_settings) is not StorageSettings:_invalid()
        self.settings=StorageSettings.from_dict(storage_settings.to_dict());self.bundles=BundleStore(self.settings)

    def _bundle(self,prepared):
        try:
            if type(prepared) is not PreparedQuery:raise ValueError()
            prepared=PreparedQuery.from_dict(prepared.to_dict())
        except Exception:_invalid()
        if prepared.active is None:_invalid()
        version=prepared.active.version;bundle=self.bundles.load(version.bundle_id);result=bundle_encoding(bundle)
        expected=(self.settings.knowledge_base_id,len(bundle.documents),len(bundle.chunks),bundle.relations['source_fingerprint'],
                  result.model_space_id,result.representation_id,result.tokenizer_id,result.dimensions)
        actual=(version.knowledge_base_id,version.document_count,version.chunk_count,version.source_fingerprint,
                version.model_space_id,version.representation_id,version.tokenizer_id,version.dimensions)
        if expected!=actual or bundle.knowledge_base_id!=self.settings.knowledge_base_id:raise StorageError('catalog_identity_mismatch')
        validate_prepared_scope(prepared,bundle)
        return prepared,bundle

    def _bounded(self,result):
        try:_json_bytes(result,self.settings.max_bundle_bytes,newline=False)
        except StorageError as error:
            if error.code=='bundle_limit_exceeded':raise StorageError('document_limit_exceeded') from None
            raise
        return copy.deepcopy(result)

    def read_chunk(self,prepared,chunk_id,*,max_characters):
        _id(chunk_id,'unit');_positive(max_characters);prepared,bundle=self._bundle(prepared)
        if chunk_id not in prepared.chunk_ids:_invalid('query_invalid_scope',prepared.active)
        chunk=next(c for c in bundle.chunks if c.id==chunk_id)
        if len(chunk.text)>max_characters:raise StorageError('document_limit_exceeded')
        return self._bounded(dict(active=prepared.active.to_dict(),chunk=chunk.to_dict()))

    def read_lines(self,prepared,document_id,*,start_line,end_line,max_characters):
        _id(document_id,'doc');_positive(start_line);_positive(end_line);_positive(max_characters)
        if start_line>end_line:_invalid()
        prepared,bundle=self._bundle(prepared)
        if document_id not in prepared.document_ids:_invalid('query_invalid_scope',prepared.active)
        doc=next(d for d in bundle.documents if d.id==document_id);starts=doc.metadata['line_starts']
        if not starts:
            if (start_line,end_line)!=(1,1):_invalid(active=prepared.active)
            text='';span=None
        else:
            if end_line>len(starts):_invalid(active=prepared.active)
            start=starts[start_line-1];end=starts[end_line] if end_line<len(starts) else len(doc.text)
            text=doc.text[start:end];span=source_span(doc,start,end)
        if len(text)>max_characters:raise StorageError('document_limit_exceeded')
        return self._bounded(dict(active=prepared.active.to_dict(),document_id=doc.id,source_path=doc.metadata['source_path'],
            source_sha256=doc.metadata['source_sha256'],span=span,text=text))

    def related_documents(self,prepared,document_id,*,max_links):
        _id(document_id,'doc');_positive(max_links);prepared,bundle=self._bundle(prepared)
        if document_id not in prepared.document_ids:_invalid('query_invalid_scope',prepared.active)
        scope=set(prepared.document_ids);included=[];omitted=0
        for edge in bundle.relations['edges']:
            ends={edge['from_document_id'],edge['to_document_id']}
            if document_id not in ends:continue
            if not ends<=scope:omitted+=1
            else:included.append(edge)
        if len(included)>max_links:raise StorageError('document_limit_exceeded')
        return self._bounded(dict(active=prepared.active.to_dict(),document_id=document_id,
            relations=sorted(included,key=lambda edge:edge['edge_id']),omitted_by_scope=omitted))
