"""Prepare BM25 statistics over retrieval text; no prefix, scoring or model call."""
from collections import Counter
from ..core.encoding_settings import validate_encoding_settings
from ..core.sparse_encoding_settings import validate_sparse_settings
from ..core.sparse_types import SparseRecord
from ..core.encoding_types import EncodingInput,fail_encoding
from ..core.errors import EncodingError
from .input_preparer import plan_encoding_batches
from .sparse_tokenizer import SparseTokenizer


class SparseEncoder:
    def __init__(self,encoding_settings,sparse_settings):
        validate_encoding_settings(encoding_settings)
        validate_sparse_settings(sparse_settings)
        self.encoding_settings=encoding_settings;self.sparse_settings=sparse_settings
        self.tokenizer=SparseTokenizer(sparse_settings)

    @property
    def tokenizer_id(self):return self.tokenizer.tokenizer_id

    def encode_batch(self,inputs):
        validate_sparse_settings(self.sparse_settings)
        try:
            batches=plan_encoding_batches(inputs,self.encoding_settings)
            if len(batches)!=1:fail_encoding('invalid_sparse_batch')
            records=[]
            for item in inputs:
                tokens=self.tokenizer.tokenize(item.retrieval_text)
                records.append(SparseRecord(item.item_id,item.kind,item.retrieval_text_sha256,tokens,
                    dict(Counter(tokens)),len(tokens),len(set(tokens)),self.tokenizer_id))
            return records
        except EncodingError:raise
        except Exception:fail_encoding('sparse_encoding_failed')

    def query_terms(self,query_input):
        if type(query_input) is not EncodingInput or query_input.kind!='query':fail_encoding('invalid_sparse_query')
        record=self.encode_batch([query_input])[0]
        return list(dict.fromkeys(record.tokens))
