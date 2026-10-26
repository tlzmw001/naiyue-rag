"""Pure scope projection shared by the three actual prepared-snapshot consumers."""
from ..core.errors import QueryJobError


def validate_prepared_scope(prepared,bundle):
    known={d.id for d in bundle.documents};scope=set(prepared.document_ids)
    if not scope<=known or prepared.chunk_ids!=sorted(c.id for c in bundle.chunks if c.source_ref in scope):
        raise QueryJobError('resources','query_invalid_scope',active=prepared.active)
