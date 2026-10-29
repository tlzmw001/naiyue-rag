from test_application_settings import configuration, write, load
from naiyue_rag.core.retrieval_settings import RetrievalSettings
from naiyue_rag.core.errors import SettingsError
import pytest


def test_existing_configuration_loads_defaults_and_new_settings_roundtrip(tmp_path):
    path = write(tmp_path / 'config.yaml')
    value = load(path)
    assert value.retrieval == RetrievalSettings()
    raw = value.to_dict()
    assert raw['retrieval'] == RetrievalSettings().to_dict()
    raw['retrieval'].update(max_concurrent_queries=4, max_queued_queries=10, request_timeout_seconds=60)
    changed = load(write(path, raw))
    assert changed.retrieval.max_concurrent_queries == 4
    assert changed.retrieval.request_timeout_seconds == 60


@pytest.mark.parametrize('key,value', [('max_concurrent_queries', True), ('max_queued_queries', -1),
    ('request_timeout_seconds', 0), ('shutdown_timeout_seconds', float('inf')), ('extra', 1)])
def test_invalid_retrieval_section_is_rejected(tmp_path, key, value):
    raw = configuration();raw['retrieval'] = RetrievalSettings().to_dict();raw['retrieval'][key] = value
    with pytest.raises(SettingsError):load(write(tmp_path / 'config.yaml', raw))
