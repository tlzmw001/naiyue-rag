"""Transport-independent bounded retrieval execution settings."""
from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class RetrievalSettings:
    max_concurrent_queries: int = 2
    max_queued_queries: int = 20
    request_timeout_seconds: float = 180
    shutdown_timeout_seconds: float = 10

    def __post_init__(self):
        if type(self.max_concurrent_queries) is not int or self.max_concurrent_queries < 1:
            raise ValueError('invalid_retrieval_settings')
        if type(self.max_queued_queries) is not int or self.max_queued_queries < 0:
            raise ValueError('invalid_retrieval_settings')
        for value in (self.request_timeout_seconds, self.shutdown_timeout_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('invalid_retrieval_settings')

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        if type(raw) is not dict or set(raw) != set(cls.__dataclass_fields__):
            raise ValueError('invalid_retrieval_settings')
        return cls(**raw)
