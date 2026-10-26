"""Explicitly owned model client; credential resolution has no global side effects."""
from ..core.credentials import resolve_api_key
from ..core.rerank_settings import load_llm_rerank_settings
from .llm import LLMReranker


def load_llm_reranker(settings_path,*,project_root,key_env):
    settings=load_llm_rerank_settings(settings_path)
    key=resolve_api_key(project_root,key_env)
    return LLMReranker(settings,api_key=key)
