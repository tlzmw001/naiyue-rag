"""Shared access to validated stored pairs; never fabricate a whole-snapshot job."""
from ..core.errors import StorageError
from .artifact_bundle import IndexBundle
from .artifact_bundle_v2 import IndexBundleV2


def bundle_encoding(bundle):
    if type(bundle) is IndexBundle:return bundle.encoding_result
    if type(bundle) is IndexBundleV2:return bundle.encoding_snapshot
    raise StorageError('invalid_index_bundle')
