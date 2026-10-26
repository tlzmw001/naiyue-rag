import importlib
import pytest
from test_graph_transport import settings


def test_public_replay_still_requires_origin_but_worker_uses_explicit_job_paths(tmp_path):
    mod=importlib.import_module('experiments.graph_transport');cfg=dict(settings(tmp_path),mode='replay')
    with pytest.raises(mod.ProbeError):mod.validate_config(cfg)
    mod.validate_worker_config(cfg)
    with pytest.raises(mod.ProbeError):mod.validate_worker_config(dict(cfg,chat_endpoint='https://example.com'))
