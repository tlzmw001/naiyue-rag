"""Reference-compatible equal-weight RRF with source and query consistency checks."""
from ..core.dense_results import DenseResult
from ..core.sparse_results import SparseResult
from ..core.hybrid_results import fused_hits


class RRFFusion:
    def __init__(self,k):
        if type(k) is not int or k<=0:raise ValueError('query_invalid_request')
        self.k=k

    def fuse(self,dense_result,sparse_result,*,top_k):
        if type(dense_result) is not DenseResult or type(sparse_result) is not SparseResult:
            raise ValueError('query_invalid_request')
        dense_result.to_dict();sparse_result.to_dict()
        if dense_result.prepared.to_dict()!=sparse_result.prepared.to_dict():raise ValueError('query_invalid_request')
        return fused_hits(dense_result.hits,sparse_result.hits,self.k,top_k)
