"""Host log hygiene: stamp every line once, instead of fixing every print()."""

from __future__ import annotations

import atexit
import io
import sys
from datetime import datetime
from typing import Callable, Optional, TextIO


def local_timestamp() -> str:
    """ISO-8601 local time with offset, second resolution."""

    return datetime.now().astimezone().isoformat(timespec="seconds")


class TimestampedStream(io.TextIOBase):
    """Line-buffered text wrapper that prefixes each complete line with a stamp.

    The LaunchAgent points StandardOutPath and StandardErrorPath at one
    ``host.log`` and the codebase writes bare ``print(..., flush=True)`` lines
    from everywhere. Wrapping the two streams once, at host startup, stamps
    every one of those lines without editing a single call site.
    """

    def __init__(
        self,
        stream: TextIO,
        *,
        clock: Optional[Callable[[], str]] = None,
    ) -> None:
        self._stream = stream
        self._clock = clock or local_timestamp
        self._pending = ""

    @property
    def wrapped(self) -> TextIO:
        return self._stream

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._stream.fileno()

    def write(self, text: str) -> int:
        if not text:
            return 0
        buffered = self._pending + text
        head, newline, tail = buffered.rpartition("\n")
        self._pending = tail
        if newline:
            stamp = self._clock()
            self._stream.write("".join(f"{stamp} {line}\n" for line in head.split("\n")))
            self.flush()
        return len(text)

    def flush(self) -> None:
        # A partial line stays unstamped until its newline arrives; emitting it
        # here would split one logical line across two stamped records.
        try:
            self._stream.flush()
        except ValueError:
            # Interpreter teardown already closed the real stream.
            pass

    def drain(self) -> None:
        """Stamp and emit a trailing partial line (process exit)."""

        if self._pending:
            pending, self._pending = self._pending, ""
            try:
                self._stream.write(f"{self._clock()} {pending}\n")
            except ValueError:
                return
        self.flush()


_INSTALLED = False


def install_host_logging(
    *,
    clock: Optional[Callable[[], str]] = None,
    force: bool = False,
) -> bool:
    """Stamp stdout/stderr for the long-running host process.

    Called only from the ``host run`` / ``listen`` entry point, so ordinary
    one-shot CLI commands keep their plain output. Also a no-op when both
    streams are a terminal: an operator running ``listen`` in the foreground
    does not need a stamp on every line.
    """

    global _INSTALLED
    if _INSTALLED and not force:
        return False
    out = sys.stdout
    err = sys.stderr
    if not force and _is_tty(out) and _is_tty(err):
        return False
    stamped_out = TimestampedStream(out, clock=clock)
    stamped_err = TimestampedStream(err, clock=clock)
    sys.stdout = stamped_out
    sys.stderr = stamped_err
    atexit.register(stamped_out.drain)
    atexit.register(stamped_err.drain)
    _INSTALLED = True
    return True


def _is_tty(stream: object) -> bool:
    try:
        return bool(stream.isatty())  # type: ignore[attr-defined]
    except Exception:
        return False
