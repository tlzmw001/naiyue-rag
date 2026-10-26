"""Shared synthetic configuration and fake vectors; never service evidence."""
from pathlib import Path

CORPUS = str(Path('data/experiments/common-evidence-corpus/20261010T021859Z-647de42b').resolve())


def config(tmp_path):
    return {'mode': 'live', 'dataset': str(Path('examples/mock-v1').resolve()), 'corpus_run': CORPUS,
            'tasks': str(Path('examples/mock-v1/tasks.json').resolve()),
            'endpoint': 'https://open.bigmodel.cn/api/paas/v4/embeddings', 'model': 'embedding-3',
            'dimensions': 2048, 'batch_size': 16, 'max_inputs': 56, 'max_requests': 5,
            'timeout_seconds': 30, 'deadline_seconds': 180, 'max_response_bytes': 4194304,
            'max_input_utf8_bytes': 3072, 'unit_price_cny_per_million': 0.5,
            'candidate_k': 20, 'max_context_chars': 8000, 'output_root': str(tmp_path), 'replay_run': None}


def vector(index=0):
    values = [0.0] * 2048
    values[index % 2] = 1.0
    return values


def response(count):
    return {'model': 'embedding-3', 'data': [{'index': i, 'embedding': vector(i)} for i in reversed(range(count))],
            'usage': {'prompt_tokens': count * 10, 'total_tokens': count * 10}}
