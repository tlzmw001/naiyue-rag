"""Configured recursive prose splitting plus protected Markdown business units."""
import copy
import hashlib
import json

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..core.errors import ChunkingError, ContractError, SettingsError
from ..core.ingestion_settings import validate_ingestion_settings
from ..core.chunking_policy import LEGACY_SEPARATORS,chunking_profile
from ..core.types import Chunk
from .markdown_structure import scan_document, source_span, fail_chunking

SEPARATORS=list(LEGACY_SEPARATORS)


class DocumentChunker:
    def __init__(self,settings):
        try:
            validate_ingestion_settings(settings)
            self._size=settings.chunk_size;self._overlap=settings.chunk_overlap
            self._profile=chunking_profile(settings)
            self._splitter=RecursiveCharacterTextSplitter(chunk_size=self._size,chunk_overlap=self._overlap,
                separators=self._profile['separators'],length_function=len,is_separator_regex=False,
                keep_separator=self._profile['keep_separator'],strip_whitespace=self._profile['strip_whitespace'],
                add_start_index=True)
        except (SettingsError,ValueError,TypeError):
            fail_chunking('invalid_chunking_config')

    def _chunk(self,document,block,start,end,index):
        span=source_span(document,start,end);body=document.text[start:end]
        identity=[document.id,document.metadata['source_sha256'],block['kind'],start,end]
        uid='unit-'+hashlib.sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        oversize=block['kind']!='text' and len(body)>self._size
        diagnostic=[]
        if oversize:diagnostic=[{'category':'atomic_oversize','severity':'warning',
            'document_id':document.id,'span':span}]
        metadata={k:copy.deepcopy(v) for k,v in document.metadata.items() if k!='line_starts'}
        metadata.update({'body_span':span,'kind':block['kind'],'chunk_index':index,
            'heading_path':[h['text'] for h in block['headings']], 'contexts':copy.deepcopy(block['contexts']),
            'case_id':block['case_id'],'case_fields':copy.deepcopy(block['case_fields']),
            'case_columns':copy.deepcopy(block['case_columns']), 'document_classification':dict(block['classification']),
            'component_metadata':copy.deepcopy(self._profile),'oversize':oversize,'diagnostics':diagnostic})
        try:return Chunk(uid,body,metadata,start,end,document.id)
        except ContractError:fail_chunking('invalid_chunking_document')

    def split_document(self,document):
        blocks,issues=scan_document(document);chunks=[]
        for block in blocks:
            if block['kind']!='text':
                chunk=self._chunk(document,block,block['start'],block['end'],len(chunks))
                chunks.append(chunk);issues.extend(copy.deepcopy(chunk.metadata['diagnostics']))
                continue
            raw=document.text[block['start']:block['end']]
            try:parts=self._splitter.create_documents([raw])
            except Exception:fail_chunking('splitter_failed')
            if not parts:fail_chunking('splitter_failed')
            previous=-1
            for part in parts:
                try:
                    offset=part.metadata['start_index'];text=part.page_content
                    if type(offset) is not int or type(text) is not str or not text or \
                            not 0<=offset<len(raw) or offset<previous or \
                            raw[offset:offset+len(text)]!=text or len(text)>self._size:raise ValueError()
                except (ValueError,KeyError,TypeError,AttributeError):fail_chunking('unmapped_fragment')
                previous=offset
                chunks.append(self._chunk(document,block,block['start']+offset,
                                          block['start']+offset+len(text),len(chunks)))
        return chunks,issues
