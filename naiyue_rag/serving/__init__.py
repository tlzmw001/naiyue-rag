"""Shared retrieval scheduling, independent of network transports."""
from .control import RetrievalError
from ..core.retrieval_settings import RetrievalSettings

__all__ = ['RetrievalService', 'RetrievalError', 'RetrievalSettings']


def __getattr__(name):
    if name == 'RetrievalService':
        from .service import RetrievalService
        return RetrievalService
    raise AttributeError(name)
