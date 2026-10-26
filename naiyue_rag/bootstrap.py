"""Assemble the internally shared snapshot through existing verified loaders."""
import logging

from experiments.embedding_probe import ProbeError
from experiments.vector_index import load_corpus
from .a2_snapshot import load_snapshot
from .core.errors import RetrievalError
from .core.settings import load_settings

LOGGER = logging.getLogger(__name__)


def load_snapshot_from_settings(settings_path):
    """Load all searchable sources in the configured library; no ACL input."""
    settings = load_settings(settings_path)
    config = settings.to_snapshot_config()
    try:
        corpus = load_corpus(config['corpus_run'], config['dataset'])
        ids = sorted(corpus['sources'])
    except ProbeError as error:
        LOGGER.error('snapshot_failed stage=resources code=%s', error.category)
        raise RetrievalError('resources', error.category) from None
    except Exception:
        LOGGER.error('snapshot_failed stage=resources code=snapshot_load_failed')
        raise RetrievalError('resources', 'snapshot_load_failed') from None
    return load_snapshot(config, ids, settings.runtime.tokenizer_cache_dir)
