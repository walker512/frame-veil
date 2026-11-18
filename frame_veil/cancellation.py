"""Main-thread SIGINT/SIGTERM cancellation with nested cleanup-aware scopes."""
import contextlib
import functools
import signal
import threading
from .core import Invalid

class Cancelled(Invalid):
    pass

_current = None

class _State:
    def __init__(self):
        self.requested = False
        self.deferred = 0

    def handler(self, signum, frame):
        # Do not interrupt cleanup a second time after cancellation began.
        if self.requested:
            return
        self.requested = True
        if not self.deferred:
            raise Cancelled('Local processing cancelled.')

    @contextlib.contextmanager
    def defer(self):
        self.deferred += 1
        try:
            yield
        finally:
            self.deferred -= 1
            if self.requested and not self.deferred:
                raise Cancelled('Local processing cancelled.')

@contextlib.contextmanager
def scope():
    global _current
    if threading.current_thread() is not threading.main_thread():
        raise Invalid('Cancellable media workflows require the main thread.')
    if _current is not None:
        yield _current
        return
    state = _State()
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    _current = state
    try:
        for s in previous:
            signal.signal(s, state.handler)
        yield state
    finally:
        state.requested = True  # Do not let a second signal interrupt restoration.
        for s, handler in previous.items():
            signal.signal(s, handler)
        _current = None

def cancellable(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with scope():
            return function(*args, **kwargs)
    return wrapped
