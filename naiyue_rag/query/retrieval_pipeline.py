"""An explicit complete retrieval flow; each layer retains its own failure contract."""
from ..serving.control import checkpoint
class RetrievalPipeline:
    def __init__(self,search,reranker,builder):
        self.search=search;self.reranker=reranker;self.builder=builder

    def query(self,query,*,scope_document_ids=None,exclude_document_ids=None,expected_revision=None):
        checkpoint()
        hybrid=self.search.search(query,scope_document_ids=scope_document_ids,
            exclude_document_ids=exclude_document_ids,expected_revision=expected_revision)
        checkpoint();ranked=self.reranker.rerank(hybrid)
        checkpoint();result=self.builder.build(ranked)
        checkpoint();return result
