"""Pure preflight; query content never becomes filters, paths or instructions."""
from dataclasses import dataclass
from ..core.encoding_settings import EncodingSettings
from ..core.errors import QueryJobError,EncodingError
from ..encoding.input_preparer import prepare_query_encoding_input,plan_encoding_batches
from ..storage.document_views import _valid_document_id
from ..storage.version_types import MAX_REVISION


@dataclass(frozen=True,repr=False)
class _ProcessedQuery:
    query:str
    scope_document_ids:tuple|None
    exclude_document_ids:tuple
    expected_revision:int|None


class QueryProcessor:
    def __init__(self,encoding_settings,*,max_scope_documents):
        try:
            if type(encoding_settings) is not EncodingSettings or type(max_scope_documents) is not int or max_scope_documents<=0:
                raise ValueError()
            self.settings=EncodingSettings.from_dict(encoding_settings.to_dict())
            self.max_scope_documents=max_scope_documents
        except Exception:raise QueryJobError('request','query_invalid_request') from None

    def _ids(self,values,*,optional=False):
        if values is None:return None if optional else ()
        if type(values) is not list or len(values)>self.max_scope_documents or \
                any(not _valid_document_id(v) for v in values) or len(set(values))!=len(values):
            raise QueryJobError('request','query_invalid_scope')
        return tuple(values)

    def process(self,query,*,scope_document_ids=None,exclude_document_ids=None,expected_revision=None):
        try:
            if type(query) is not str or not query.strip():raise ValueError()
            query.encode('utf-8')
            if expected_revision is not None and (type(expected_revision) is not int or not 0<=expected_revision<=MAX_REVISION):
                raise ValueError()
            scope=self._ids(scope_document_ids,optional=True);exclude=self._ids(exclude_document_ids)
            item=prepare_query_encoding_input(query,self.settings)
            plan_encoding_batches([item],self.settings)
            return _ProcessedQuery(query,scope,exclude,expected_revision)
        except QueryJobError:raise
        except EncodingError as error:raise QueryJobError('request',error.code) from None
        except Exception:raise QueryJobError('request','query_invalid_request') from None
