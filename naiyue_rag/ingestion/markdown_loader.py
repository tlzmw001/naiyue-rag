"""Read bounded Markdown sources without normalizing their content."""
import hashlib
import json
import logging
import os
from pathlib import Path
import re

from ..core.errors import LoadError
from ..core.types import Document

LOGGER = logging.getLogger(__name__)


def _fail(code):
    LOGGER.error('source_failed stage=load code=%s', code)
    raise LoadError(code) from None


def _valid_text(value):
    if type(value) is not str or not value.strip() or '\x00' in value:
        return False
    try:
        value.encode('utf-8')
    except UnicodeError:
        return False
    return True


class MarkdownLoader:
    """All ordinary Markdown in one explicit, internally shared library root."""

    def __init__(self, knowledge_base_root, knowledge_base_id, max_file_bytes):
        if not isinstance(knowledge_base_root, (str, Path)) or not _valid_text(str(knowledge_base_root)) or \
                not _valid_text(knowledge_base_id) or type(max_file_bytes) is not int or max_file_bytes <= 0:
            _fail('invalid_loader_config')
        try:
            root = Path(knowledge_base_root).resolve()
            if not root.is_dir(): _fail('invalid_loader_config')
        except LoadError:
            raise
        except (OSError, ValueError, RuntimeError):
            _fail('invalid_loader_config')
        self._root = root
        self._knowledge_base_id = knowledge_base_id
        self._max_file_bytes = max_file_bytes

    def load(self, relative_path):
        """Return one Document whose content and version share the same read."""
        if not isinstance(relative_path, (str, Path)) or not _valid_text(str(relative_path)):
            _fail('invalid_source_path')
        try:
            given = Path(relative_path)
            if given.is_absolute() or '..' in given.parts: _fail('invalid_source_path')
            target = self._root
            for part in given.parts:
                target = target / part
                if target.is_symlink(): _fail('invalid_source_path')
            target = target.resolve()
            if not target.is_relative_to(self._root): _fail('invalid_source_path')
            if target.suffix.lower() != '.md': _fail('unsupported_source')
            if not target.is_file(): _fail('source_read_failed')
            with target.open('rb') as handle:
                raw = handle.read(self._max_file_bytes + 1)
        except LoadError:
            raise
        except (OSError, ValueError, RuntimeError, OverflowError):
            _fail('source_read_failed')
        if len(raw) > self._max_file_bytes: _fail('source_too_large')
        try:
            text = raw.decode('utf-8')
        except UnicodeError:
            _fail('invalid_source_encoding')
        relative = target.relative_to(self._root).as_posix()
        identity = json.dumps([self._knowledge_base_id, relative], ensure_ascii=False,
                              separators=(',', ':')).encode('utf-8')
        line_starts = [0] if text else []
        line_starts.extend(match.end() for match in re.finditer(r'\r\n|\r|\n', text)
                           if match.end() < len(text))
        return Document('doc-' + hashlib.sha256(identity).hexdigest(), text,
                        {'knowledge_base_id':self._knowledge_base_id, 'source_path':relative,
                         'source_sha256':hashlib.sha256(raw).hexdigest(),
                         'size_bytes':len(raw), 'line_starts':line_starts})

    def load_all(self):
        """Fail visibly on scan/load errors; never return a partial batch."""
        def scan_failed(error):
            _fail('source_scan_failed')
        paths = []
        try:
            if not self._root.is_dir(): _fail('source_scan_failed')
            for directory, dirnames, filenames in os.walk(self._root, followlinks=False, onerror=scan_failed):
                base = Path(directory)
                for name in dirnames:
                    if (base / name).is_symlink(): _fail('invalid_source_path')
                for name in filenames:
                    if Path(name).suffix.lower() == '.md':
                        paths.append((base / name).relative_to(self._root).as_posix())
        except LoadError:
            raise
        except (OSError, ValueError, RuntimeError):
            _fail('source_scan_failed')
        return [self.load(relative) for relative in sorted(paths)]
