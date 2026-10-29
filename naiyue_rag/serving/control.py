"""Request-local cancellation; no global cancellation or forced thread exit."""
from contextlib import contextmanager
from contextvars import ContextVar
import threading
import time

_CURRENT = ContextVar('nyr_retrieval_control', default=None)


class RetrievalError(ValueError):
    CODES = {'retrieval_timeout', 'retrieval_cancelled', 'retrieval_overloaded', 'retrieval_closed',
             'retrieval_shutdown_timeout', 'retrieval_invalid_request', 'retrieval_worker_failed',
             'retrieval_resources_changed', 'retrieval_cleanup_failed', 'retrieval_update_busy'}

    def __init__(self, code):
        self.code = code if code in self.CODES else 'retrieval_worker_failed'
        super().__init__(self.code)


class RequestControl:
    def __init__(self, deadline):
        self.deadline = deadline
        self.cancelled = threading.Event()

    def check(self):
        if time.monotonic() >= self.deadline:
            raise RetrievalError('retrieval_timeout')
        if self.cancelled.is_set():
            raise RetrievalError('retrieval_cancelled')

    @contextmanager
    def use(self):
        token = _CURRENT.set(self)
        try:
            self.check()
            yield
        finally:
            _CURRENT.reset(token)


def checkpoint():
    control = _CURRENT.get()
    if control is not None:
        control.check()


def remaining_timeout(seconds):
    control = _CURRENT.get()
    if control is None:
        return seconds
    control.check()
    return min(seconds, control.deadline - time.monotonic())
