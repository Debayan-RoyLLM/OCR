"""Where the run talks to you.

Two jobs `print` could not do: a level, so a run can be made quieter from the
command line; and ORDER — pages are read several at a time (config.WORKERS) and
four threads printing into one terminal interleave into nonsense. A worker's
output is captured into a buffer and replayed when that page's turn comes, so a
parallel run reads like a serial one and still prints as it goes.

The format is bare "%(message)s": messages carry their own "  " indent and
"  ! " marker.
"""
import logging
import sys
import threading
from contextlib import contextmanager

log = logging.getLogger("ocr")


class _Stdout(logging.StreamHandler):
    """Whatever sys.stdout is NOW. StreamHandler holds the stream it was built
    with, which ignores a later redirect — a notebook, a test, a `> run.log`."""

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, _):
        pass


_console = _Stdout()
_console.setFormatter(logging.Formatter("%(message)s"))

_local = threading.local()


class _Router(logging.Handler):
    """Straight to the terminal, unless this thread is being captured."""

    def emit(self, record):
        buf = getattr(_local, "buf", None)
        if buf is None:
            _console.emit(record)
        else:
            buf.append(record)


def setup(verbosity: int = 0) -> None:
    """verbosity: -1 quiet (warnings only), 0 normal, 1 verbose (everything)."""
    log.setLevel({-1: logging.WARNING, 0: logging.INFO}.get(verbosity, logging.DEBUG))
    log.handlers[:] = [_Router()]
    log.propagate = False


@contextmanager
def collected(active: bool = True):
    """Everything logged by THIS thread inside the block lands in the yielded
    list instead of the terminal; `replay` prints it later.

    active=False yields None and captures nothing — the single-worker case,
    where there is nothing to interleave with and buffering only adds delay."""
    if not active:
        yield None
        return
    _local.buf = buf = []
    try:
        yield buf
    finally:
        _local.buf = None


def replay(buf) -> None:
    """Print a buffer from `collected`. None means it was never captured, so it
    has already been printed."""
    for record in buf or ():
        _console.emit(record)


# So anything imported from a notebook or a test talks without script.py's flag
# parsing having run. script.py calls setup() again with the real verbosity.
setup(0)
