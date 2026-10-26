"""Source-bound term statistics; counters must agree with the retained token list."""
import copy
from collections import Counter
from dataclasses import dataclass,asdict
import re
from .encoding_types import fail_encoding
from .errors import EncodingError


@dataclass(repr=False)
class SparseRecord:
    item_id:str
    kind:str
    retrieval_text_sha256:str
    tokens:list
    term_frequencies:dict
    doc_length:int
    unique_terms:int
    tokenizer_id:str

    def __post_init__(self):
        try:
            if type(self.item_id) is not str or not self.item_id or self.kind not in ('document','query'):raise ValueError()
            for value in [self.retrieval_text_sha256,self.tokenizer_id]:
                if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError()
            if type(self.tokens) is not list or type(self.term_frequencies) is not dict:raise ValueError()
            for token in self.tokens:
                if type(token) is not str or not token.strip() or '\x00' in token:raise ValueError()
                token.encode('utf-8')
            if any(type(v) is not int or v<=0 for v in self.term_frequencies.values()):raise ValueError()
            if self.term_frequencies!=dict(Counter(self.tokens)):raise ValueError()
            if type(self.doc_length) is not int or self.doc_length!=len(self.tokens) or \
                    type(self.unique_terms) is not int or self.unique_terms!=len(self.term_frequencies):raise ValueError()
            self.tokens=list(self.tokens);self.term_frequencies=dict(self.term_frequencies)
        except Exception:fail_encoding('invalid_sparse_record')

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):fail_encoding('invalid_sparse_record')
        return cls(**copy.deepcopy(data))
