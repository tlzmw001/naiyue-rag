"""Audit prepared Embedding inputs against a local Ollama model without saving text."""
import argparse
from dataclasses import replace
import json
import logging
import math
import re
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from naiyue_rag import DocumentChunker, MarkdownLoader, prepare_knowledge_base
from naiyue_rag.core.application_settings import load_application_settings
from naiyue_rag.core.errors import EncodingError
from naiyue_rag.core.model_registry import load_model_registry
from naiyue_rag.encoding import prepare_document_encoding_inputs
from naiyue_rag.encoding.input_preparer import plan_encoding_batches

LOGGER = logging.getLogger(__name__)


class AuditError(Exception):
    def __init__(self, code, *, index=None):
        self.code = code
        self.index = index


def _local_origin(base_url):
    parsed = urlsplit(base_url)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or
            parsed.path.rstrip('/') != '/v1' or parsed.username is not None or
            parsed.password is not None or parsed.query or parsed.fragment):
        raise AuditError('ollama_url_not_local')
    return f'{parsed.scheme}://{parsed.netloc}'


def _json_request(opener, url, *, body=None, timeout, max_bytes):
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    request = Request(url, payload, {'Content-Type': 'application/json'} if payload is not None else {})
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
    except Exception as error:
        status = getattr(error, 'code', None)
        if type(status) is int:
            raise AuditError(f'ollama_http_{status}') from None
        raise AuditError('ollama_unavailable') from None
    if len(raw) > max_bytes:
        raise AuditError('ollama_response_too_large')
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AuditError('ollama_invalid_response') from None
    if type(result) is not dict:
        raise AuditError('ollama_invalid_response')
    return result


def _percentile(sorted_sizes, fraction):
    if not sorted_sizes:
        return 0
    return sorted_sizes[math.ceil((len(sorted_sizes) - 1) * fraction)]


def audit(config_path, *, probe):
    app = load_application_settings(config_path)
    encoding = load_model_registry(app).encoding_settings()
    origin = _local_origin(encoding.embedding.base_url)
    opener = build_opener(ProxyHandler({}))
    tags = _json_request(opener, origin + '/api/tags', timeout=encoding.runtime.timeout_seconds,
                         max_bytes=65536)
    models = tags.get('models')
    if type(models) is not list:
        raise AuditError('ollama_invalid_response')
    matches = [row for row in models if type(row) is dict and row.get('name') == encoding.embedding.model]
    if len(matches) != 1 or type(matches[0].get('digest')) is not str:
        raise AuditError('ollama_model_missing')
    digest = matches[0]['digest']
    if digest != encoding.embedding.model_revision:
        raise AuditError('ollama_model_digest_mismatch')

    documents = MarkdownLoader(app.knowledge_base_root, app.storage.knowledge_base_id,
                               app.storage.max_file_bytes).load_all()
    chunks, _, _ = prepare_knowledge_base(documents, DocumentChunker(app.ingestion),
                                          text_mode=encoding.representation.document_text_mode)
    # Widen only the in-memory audit budget so oversize inputs are counted before ingestion.
    per_input = max(encoding.runtime.max_input_utf8_bytes, app.storage.max_file_bytes * 4)
    audit_runtime = replace(encoding.runtime,
                            max_input_utf8_bytes=per_input,
                            max_batch_input_utf8_bytes=max(encoding.runtime.max_batch_input_utf8_bytes,
                                                           per_input * encoding.runtime.batch_size),
                            max_inputs=max(encoding.runtime.max_inputs, len(chunks)),
                            max_requests=max(encoding.runtime.max_requests, len(chunks)))
    items = prepare_document_encoding_inputs(documents, chunks,
                                             replace(encoding, runtime=audit_runtime))
    sizes = sorted(len(item.embedding_text.encode('utf-8')) for item in items)
    result = {
        'status': 'audited', 'model': encoding.embedding.model, 'model_digest': digest,
        'documents': len(documents), 'chunks': len(chunks), 'inputs': len(items),
        'configured_max_documents': app.storage.max_documents,
        'configured_max_chunks': app.storage.max_chunks,
        'configured_max_inputs': encoding.runtime.max_inputs,
        'atomic_oversize_chunks': sum(chunk.metadata.get('oversize', False) for chunk in chunks),
        'max_utf8_bytes': sizes[-1] if sizes else 0,
        'p50_utf8_bytes': _percentile(sizes, .50),
        'p95_utf8_bytes': _percentile(sizes, .95),
        'over_configured_byte_limit': sum(size > encoding.runtime.max_input_utf8_bytes for size in sizes),
        'no_truncation_probe': 'not_run',
    }
    if result['over_configured_byte_limit']:
        result['status'] = 'input_limit_exceeded'
        return result, 2
    try:
        result['planned_embedding_requests'] = len(plan_encoding_batches(items, encoding))
    except EncodingError as error:
        result['status'] = 'runtime_budget_exceeded'
        result['error_code'] = error.code
        return result, 2
    if probe:
        max_tokens = 0
        for index, item in enumerate(items):
            try:
                response = _json_request(opener, origin + '/api/embed',
                    body={'model': encoding.embedding.model, 'input': item.embedding_text,
                          'truncate': False}, timeout=encoding.runtime.timeout_seconds,
                    max_bytes=encoding.runtime.max_response_bytes)
                vectors = response.get('embeddings')
                tokens = response.get('prompt_eval_count')
                if (type(vectors) is not list or len(vectors) != 1 or
                        type(vectors[0]) is not list or
                        len(vectors[0]) != encoding.embedding.expected_dimensions or
                        type(tokens) is not int or tokens < 0):
                    raise AuditError('ollama_invalid_response')
                max_tokens = max(max_tokens, tokens)
            except AuditError as error:
                raise AuditError(error.code, index=index) from None
        result['no_truncation_probe'] = 'passed'
        result['max_prompt_eval_tokens'] = max_tokens
    return result, 0


def main():
    parser = argparse.ArgumentParser(description='Report only aggregate local Embedding input metrics.')
    parser.add_argument('--config', required=True)
    parser.add_argument('--probe', action='store_true', help='Check every input with /api/embed truncate=false.')
    args = parser.parse_args()
    try:
        result, status = audit(args.config, probe=args.probe)
    except Exception as error:
        code = getattr(error, 'code', None)
        if type(code) is not str or re.fullmatch(r'[a-z0-9_]+', code) is None:
            code = 'local_embedding_audit_failed'
        LOGGER.error('local_embedding_audit_failed code=%s exception_type=%s', code,
                     type(error).__name__)
        result = {'status': 'failed', 'error_code': code}
        if type(getattr(error, 'index', None)) is int:
            result['input_index'] = error.index
        status = 2
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
