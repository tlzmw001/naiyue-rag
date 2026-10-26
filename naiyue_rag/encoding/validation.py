"""Normalize one OpenAI-shaped response with explicit provenance and index binding."""
import copy
from dataclasses import dataclass,asdict
import json
import logging
import math
import re
from ..core.encoding_settings import validate_encoding_settings
from ..core.encoding_types import fail_encoding
from ..core.errors import EncodingError
from .input_preparer import plan_encoding_batches

LOGGER=logging.getLogger(__name__)


@dataclass(repr=False)
class ProviderBatchResult:
    vectors:list
    input_ids:list
    input_hashes:list
    model_space_id:str
    returned_model:str
    source_kind:str
    usage:dict|None
    usage_status:str

    def __post_init__(self):
        try:
            if type(self.vectors) is not list or not self.vectors or type(self.input_ids) is not list or \
                    type(self.input_hashes) is not list or len(self.vectors)!=len(self.input_ids) or \
                    len(self.vectors)!=len(self.input_hashes):raise ValueError()
            for vector in self.vectors:
                if type(vector) is not list or not vector or len(vector)!=len(self.vectors[0]) or \
                        any(type(v) not in (int,float) or not math.isfinite(v) for v in vector):raise ValueError()
                norm=math.hypot(*vector)
                if not math.isfinite(norm) or norm==0:raise ValueError()
            if any(type(v) is not str or not v for v in self.input_ids) or len(set(self.input_ids))!=len(self.input_ids):raise ValueError()
            if any(type(v) is not str or not re.fullmatch('[0-9a-f]{64}',v) for v in self.input_hashes+[self.model_space_id]):raise ValueError()
            if type(self.returned_model) is not str or not self.returned_model or self.source_kind not in ('simulated','service'):raise ValueError()
            if self.usage_status=='known':
                usage,status=_usage(self.usage)
                if status!='known' or usage!=self.usage:raise ValueError()
            elif self.usage_status not in ('unknown_missing','unknown_invalid') or self.usage is not None:raise ValueError()
            self.vectors=copy.deepcopy(self.vectors);self.input_ids=list(self.input_ids)
            self.input_hashes=list(self.input_hashes);self.usage=copy.deepcopy(self.usage)
        except Exception:fail_encoding('invalid_provider_batch_result')

    def to_dict(self):
        self.__post_init__()
        return copy.deepcopy(asdict(self))

    @classmethod
    def from_dict(cls,data):
        if type(data) is not dict or set(data)!=set(cls.__dataclass_fields__):fail_encoding('invalid_provider_batch_result')
        return cls(**copy.deepcopy(data))


def _usage(value):
    if value is None:return None,'unknown_missing'
    try:
        if type(value) is not dict:raise ValueError()
        fields=['prompt_tokens','total_tokens']+(['completion_tokens'] if 'completion_tokens' in value else [])
        if any(type(value[k]) is not int or value[k]<0 for k in fields) or value['total_tokens']<value['prompt_tokens']:raise ValueError()
        return {k:value[k] for k in fields},'known'
    except (ValueError,TypeError,KeyError):
        LOGGER.warning('encoding_observation code=usage_invalid')
        return None,'unknown_invalid'


def normalize_embedding_response(payload,inputs,settings,*,source_kind):
    validate_encoding_settings(settings)
    batches=plan_encoding_batches(inputs,settings)
    if len(batches)!=1:fail_encoding('invalid_embedding_response')
    try:
        if source_kind not in ('simulated','service') or type(payload) is not dict:raise ValueError()
        if payload.get('model') not in settings.embedding.allowed_response_models or type(payload.get('data')) is not list or len(payload['data'])!=len(inputs):raise ValueError()
        # Validate vectors before JSON bound calculation so NaN is a vector error.
        vectors=[None]*len(inputs)
        for row in payload['data']:
            index=row['index'];vector=row['embedding']
            if type(index) is not int or not 0<=index<len(inputs) or vectors[index] is not None or \
                    type(vector) is not list or len(vector)!=settings.embedding.expected_dimensions or \
                    any(type(v) not in (int,float) or not math.isfinite(v) for v in vector):raise ValueError()
            norm=math.hypot(*vector)
            if not math.isfinite(norm) or norm==0:raise ValueError()
            vectors[index]=list(vector)
        if any(v is None for v in vectors):raise ValueError()
        if len(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode())>settings.runtime.max_response_bytes:
            fail_encoding('embedding_response_too_large')
        usage,status=_usage(payload.get('usage'))
        return ProviderBatchResult(vectors,[i.item_id for i in inputs],[i.embedding_text_sha256 for i in inputs],
            settings.model_space_id,payload['model'],source_kind,usage,status)
    except EncodingError:raise
    except Exception:fail_encoding('invalid_embedding_response')
