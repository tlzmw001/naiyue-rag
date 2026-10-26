"""An encoding input describes source and representation, never a retrieved answer."""
import copy
from dataclasses import dataclass,asdict
import hashlib
import logging
import re
from .errors import EncodingError
from .types import SourceSpan

LOGGER=logging.getLogger(__name__)


def fail_encoding(code):
    LOGGER.error('encoding_failed stage=encoding code=%s',code)
    raise EncodingError(code) from None


def text_sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass(repr=False)
class EncodingInput:
    item_id:str
    kind:str
    knowledge_base_id:str|None
    source_document_id:str|None
    source_sha256:str|None
    source_span:dict|None
    retrieval_text:str
    embedding_text:str
    retrieval_text_sha256:str
    embedding_text_sha256:str
    model_space_id:str
    representation_id:str
    query_sha256:str|None

    def __post_init__(self):
        try:
            if type(self.item_id) is not str or not self.item_id or self.kind not in ('document','query'):raise ValueError()
            for value in [self.retrieval_text,self.embedding_text]:
                if type(value) is not str or not value.strip():raise ValueError()
                value.encode('utf-8')
            for value in [self.retrieval_text_sha256,self.embedding_text_sha256,self.model_space_id,self.representation_id]:
                if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError()
            if text_sha(self.retrieval_text)!=self.retrieval_text_sha256 or text_sha(self.embedding_text)!=self.embedding_text_sha256:raise ValueError()
            if self.kind=='document':
                if any(type(v) is not str or not v for v in [self.knowledge_base_id,self.source_document_id,self.source_sha256]):raise ValueError()
                span=SourceSpan.from_dict(self.source_span)
                if span.source_sha256!=self.source_sha256 or self.query_sha256 is not None:raise ValueError()
            elif any(v is not None for v in [self.knowledge_base_id,self.source_document_id,self.source_sha256,self.source_span]) or \
                    self.query_sha256!=text_sha(self.retrieval_text):raise ValueError()
            self.source_span=copy.deepcopy(self.source_span)
        except Exception:fail_encoding('invalid_encoding_input')

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):fail_encoding('invalid_encoding_input')
        return cls(**copy.deepcopy(data))
