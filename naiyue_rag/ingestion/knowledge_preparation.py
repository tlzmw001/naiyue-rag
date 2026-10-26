"""Prepare one explicit loaded library batch, without partial success or storage."""
from ..core.errors import ChunkingError, PreparationError, RelationError
from .chunk_preparation import prepare_document, _fail as fail_preparation
from .document_relations import build_document_relations, _fail as fail_relations


def prepare_knowledge_base(documents, chunker, *, text_mode):
    if type(text_mode) is not str or text_mode not in ('raw', 'labeled_case'):
        fail_preparation('invalid_text_mode')
    try:
        relations = build_document_relations(documents)
    except RelationError:
        raise
    except Exception:
        fail_relations('relation_build_failed')
    chunks = [];diagnostics = []
    try:
        for document in sorted(documents, key=lambda d:d.id):
            prepared,observed = prepare_document(document, chunker, text_mode=text_mode)
            chunks.extend(prepared);diagnostics.extend(observed)
    except (PreparationError, ChunkingError, RelationError):
        raise
    except Exception:
        fail_relations('knowledge_preparation_failed')
    return chunks, relations, diagnostics
