"""The operator audit checks real prepared inputs and never prints their text."""
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
import yaml

from naiyue_rag.validation import local_embedding_audit as audit


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _):
        return self.payload


class LocalOllama:
    def __init__(self, *, embed_status=200):
        self.embed_status = embed_status
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request.full_url, json.loads(request.data) if request.data else None))
        if request.full_url.endswith('/api/tags'):
            return Response({'models': [{'name': 'synthetic-embedding', 'digest': 'digest-v1'}]})
        assert request.full_url.endswith('/api/embed')
        assert timeout > 0
        assert self.calls[-1][1]['truncate'] is False
        if self.embed_status != 200:
            raise HTTPError(request.full_url, self.embed_status, 'probe rejected', {}, None)
        return Response({'embeddings': [[.1, .2, .3]], 'prompt_eval_count': 7})


def configuration(tmp_path, text, *, max_input_bytes=3000, base_url='http://127.0.0.1:11434/v1/'):
    root = Path(tmp_path)
    knowledge = root / 'knowledge'
    knowledge.mkdir()
    (knowledge / 'source.md').write_text(text)
    config = yaml.safe_load(Path('naiyue_rag/resources/config.yaml').read_text())
    config['service']['access_token'] = 'a' * 32
    config['rerank']['backend'] = 'none'
    config['rerank']['model'] = None
    config['encoding']['runtime']['max_input_utf8_bytes'] = max_input_bytes
    path = root / 'config.yaml'
    path.write_text(yaml.safe_dump(config, allow_unicode=True))
    model = {
        'kind': 'embedding', 'provider': 'openai_compatible', 'base_url': base_url,
        'model': 'synthetic-embedding', 'expected_dimensions': 3,
        'request_dimensions': None, 'model_revision': 'digest-v1',
        'allowed_response_models': ['synthetic-embedding'], 'api_key': 'placeholder',
    }
    (root / 'models.json').write_text(json.dumps({'config_version': 1, 'models': {'embedding': model}}))
    return path


def test_probe_uses_prepared_text_but_reports_only_aggregate(tmp_path, monkeypatch):
    private = 'PRIVATE_CONTENT_MARKER'
    path = configuration(tmp_path, '# Heading\n\n' + private)
    ollama = LocalOllama()
    monkeypatch.setattr(audit, 'build_opener', lambda *_: ollama)

    result, status = audit.audit(path, probe=True)

    assert status == 0 and result['documents'] == result['chunks'] == result['inputs'] == 1
    assert result['no_truncation_probe'] == 'passed'
    assert result['max_prompt_eval_tokens'] == 7
    assert private in ollama.calls[1][1]['input']
    assert private not in json.dumps(result)


def test_oversize_input_is_counted_before_any_embedding_request(tmp_path, monkeypatch):
    path = configuration(tmp_path, '# Heading\n\n```text\n' + 'A' * 80 + '\n```', max_input_bytes=16)
    ollama = LocalOllama()
    monkeypatch.setattr(audit, 'build_opener', lambda *_: ollama)

    result, status = audit.audit(path, probe=True)

    assert status == 2 and result['status'] == 'input_limit_exceeded'
    assert result['over_configured_byte_limit'] >= 1
    assert [url.rsplit('/', 1)[-1] for url, _ in ollama.calls] == ['tags']


def test_native_context_failure_identifies_index_without_echoing_text(tmp_path, monkeypatch):
    private = 'PRIVATE_CONTENT_MARKER'
    path = configuration(tmp_path, '# Heading\n\n' + private)
    monkeypatch.setattr(audit, 'build_opener', lambda *_: LocalOllama(embed_status=400))

    with pytest.raises(audit.AuditError) as caught:
        audit.audit(path, probe=True)

    assert caught.value.code == 'ollama_http_400' and caught.value.index == 0
    assert private not in str(caught.value)


def test_nonlocal_model_url_rejected_before_opening_documents(tmp_path, monkeypatch):
    path = configuration(tmp_path, '# Heading\n\nPrivate', base_url='https://example.com/v1/')
    monkeypatch.setattr(audit, 'build_opener', lambda *_: pytest.fail('network must not open'))

    with pytest.raises(audit.AuditError, match='ollama_url_not_local'):
        audit.audit(path, probe=False)


def test_model_digest_mismatch_blocks_source_scan_and_probe(tmp_path, monkeypatch):
    path = configuration(tmp_path, '# Heading\n\nPrivate')
    models_path = Path(tmp_path) / 'models.json'
    models = json.loads(models_path.read_text())
    models['models']['embedding']['model_revision'] = 'different-digest'
    models_path.write_text(json.dumps(models))
    ollama = LocalOllama()
    monkeypatch.setattr(audit, 'build_opener', lambda *_: ollama)

    with pytest.raises(audit.AuditError, match='ollama_model_digest_mismatch'):
        audit.audit(path, probe=True)

    assert [url.rsplit('/', 1)[-1] for url, _ in ollama.calls] == ['tags']


def test_runtime_request_budget_blocks_probe_before_ingestion(tmp_path, monkeypatch):
    path = configuration(tmp_path, '# First\n\nText')
    (Path(tmp_path) / 'knowledge' / 'second.md').write_text('# Second\n\nText')
    config = yaml.safe_load(path.read_text())
    config['encoding']['runtime']['batch_size'] = 1
    config['encoding']['runtime']['max_requests'] = 1
    path.write_text(yaml.safe_dump(config))
    ollama = LocalOllama()
    monkeypatch.setattr(audit, 'build_opener', lambda *_: ollama)

    result, status = audit.audit(path, probe=True)

    assert status == 2 and result['status'] == 'runtime_budget_exceeded'
    assert result['error_code'] == 'encoding_request_limit'
    assert [url.rsplit('/', 1)[-1] for url, _ in ollama.calls] == ['tags']
