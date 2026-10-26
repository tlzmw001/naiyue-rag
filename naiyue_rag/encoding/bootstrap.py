"""Explicit application assembly: model settings plus one project-scoped credential."""
from ..core.encoding_settings import load_encoding_settings
from ..core.credentials import resolve_api_key
from .openai_embedding import OpenAICompatibleEmbedding


def load_embedding_provider(settings_path,*,project_root,key_env):
    """Return an owned client; the caller must close it or use its context manager."""
    settings=load_encoding_settings(settings_path)
    api_key=resolve_api_key(project_root,key_env)
    return OpenAICompatibleEmbedding(settings,api_key=api_key)
