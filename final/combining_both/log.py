"""Where the run talks to you.

Two jobs, both of which `print` could not do:

  1. a level, so a run can be made quieter or noisier from the command line
     instead of by editing the code that prints;
  2. ORDER. Pages are read several at a time (config.WORKERS), and four threads
     printing into one terminal interleave into nonsense. A worker's output is
     captured into a buffer instead, and each buffer is replayed the moment that
     page's turn comes round — so a parallel run reads exactly like a serial one
     and still prints as it goes, rather than all at the end.

The format is bare "%(message)s": every existing message already carries its own
"  " indent or "  ! " marker, and those conventions are worth keeping.
"""
import logging
import sys
import threading
from contextlib import contextmanager

log = logging.getLogger("ocr")


class _Stdout(logging.StreamHandler):
    """Whatever sys.stdout is NOW, not whatever it was at import.

    StreamHandler holds the stream it was built with, which quietly ignores any
    later redirect — a notebook, a test capturing output, a `> run.log`."""

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
    list instead of the terminal. Nothing is lost — `replay` prints it later, in
    whatever order the caller wants.

    active=False yields None and captures nothing: the thread keeps talking
    straight to the terminal. That is the single-worker case, where there is no
    second thread to interleave with and buffering would only add a delay."""
    if not active:
        yield None
        return
    _local.buf = buf = []
    try:
        yield buf
    finally:
        _local.buf = None


def replay(buf) -> None:
    """Print a buffer from `collected`. None means it was never captured — it
    has already been printed — so there is nothing to do."""
    for record in buf or ():
        _console.emit(record)


# A sane default the moment anything imports this, so a module used from a
# notebook or a test — anywhere script.py's flag parsing never runs — still
# talks. script.py calls setup() again with whatever the flags asked for.
setup(0)
