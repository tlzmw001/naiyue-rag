"""Explicit single-process JSONL append; all IO failures are observable."""
import copy
import json
import logging
from pathlib import Path

from .errors import TraceError
from .trace_context import validate_trace_report

LOGGER = logging.getLogger(__name__)


class TraceCollector:
    def __init__(self, traces_path):
        try:
            if not isinstance(traces_path, (str, Path)) or not str(traces_path).strip():
                raise ValueError()
            self._path = Path(traces_path).resolve()
            if self._path.is_dir(): raise ValueError()
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            LOGGER.error('trace_failed code=trace_write_failed')
            raise TraceError('trace_write_failed') from None

    @property
    def path(self):
        return self._path

    def collect(self, trace_report):
        validate_trace_report(trace_report)
        data = copy.deepcopy(trace_report)
        try:
            line = json.dumps(data, ensure_ascii=False, allow_nan=False) + '\n'
            with self._path.open('a', encoding='utf-8', newline='\n') as handle:
                if handle.write(line) != len(line): raise OSError()
        except Exception:
            LOGGER.error('trace_failed trace_id=%s code=trace_write_failed', data['trace_id'])
            raise TraceError('trace_write_failed') from None
