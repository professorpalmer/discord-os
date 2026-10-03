"""Host log hygiene: stamp every line once, instead of fixing every print()."""

from __future__ import annotations

import atexit
import io
import os
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, TextIO, Union

HOST_LOG_MAX_BYTES = 10 * 1024 * 1024
HOST_LOG_GENERATIONS = 3
ROTATE_CHECK_INTERVAL_S = 60.0


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
            maybe_rotate_host_log()
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


_ROTATE_LOCK = threading.Lock()
_ROTATE_PATH: Optional[Path] = None
_ROTATE_MAX_BYTES = HOST_LOG_MAX_BYTES
_ROTATE_GENERATIONS = HOST_LOG_GENERATIONS
_ROTATE_NEXT_CHECK = 0.0


def rotate_host_log(
    log: Union[str, Path],
    *,
    max_bytes: int = HOST_LOG_MAX_BYTES,
    generations: int = HOST_LOG_GENERATIONS,
    force: bool = False,
) -> bool:
    """Copy-truncate ``host.log`` when it outgrows ``max_bytes``.

    Copy-truncate, not rename: launchd opens StandardOutPath once per spawn and
    holds that descriptor for the life of the process, so renaming host.log
    would leave the host writing into an unlinked inode nobody can read until
    the next respawn. Copying the bytes out to host.log.1 and then truncating
    host.log in place keeps that descriptor on the live file. Both launchd and
    ``start_detached`` open it in append mode, so the next write lands at the
    new end of file instead of leaving a sparse hole.
    """

    path = Path(log)
    if not _over_limit(path, max_bytes, force):
        return False
    with _ROTATE_LOCK:
        # Re-check under the lock: stdout and stderr are separate wrappers and
        # may both land here for the same overflow.
        if not _over_limit(path, max_bytes, force):
            return False
        keep = max(1, int(generations))
        try:
            path.with_name(f"{path.name}.{keep}").unlink()
        except OSError:
            pass
        for index in range(keep - 1, 0, -1):
            older = path.with_name(f"{path.name}.{index}")
            if not older.exists():
                continue
            try:
                os.replace(older, path.with_name(f"{path.name}.{index + 1}"))
            except OSError:
                pass
        try:
            shutil.copyfile(path, path.with_name(f"{path.name}.1"))
            with open(path, "r+b") as handle:
                handle.truncate(0)
        except OSError:
            return False
    return True


def _over_limit(path: Path, max_bytes: int, force: bool) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return force or size > max_bytes


def attach_host_log_rotation(
    workspace: Union[str, Path],
    *,
    max_bytes: int = HOST_LOG_MAX_BYTES,
    generations: int = HOST_LOG_GENERATIONS,
) -> Path:
    """Rotate this workspace's host.log now, then keep checking periodically."""

    global _ROTATE_PATH, _ROTATE_MAX_BYTES, _ROTATE_GENERATIONS, _ROTATE_NEXT_CHECK

    from agent_discord.host.service import host_log_path

    path = host_log_path(workspace)
    _ROTATE_PATH = path
    _ROTATE_MAX_BYTES = int(max_bytes)
    _ROTATE_GENERATIONS = int(generations)
    _ROTATE_NEXT_CHECK = 0.0
    rotate_host_log(path, max_bytes=max_bytes, generations=generations)
    return path


def maybe_rotate_host_log() -> bool:
    """Size check at most once per ``ROTATE_CHECK_INTERVAL_S``, from the writer."""

    global _ROTATE_NEXT_CHECK

    path = _ROTATE_PATH
    if path is None:
        return False
    now = time.monotonic()
    if now < _ROTATE_NEXT_CHECK:
        return False
    _ROTATE_NEXT_CHECK = now + ROTATE_CHECK_INTERVAL_S
    return rotate_host_log(
        path,
        max_bytes=_ROTATE_MAX_BYTES,
        generations=_ROTATE_GENERATIONS,
    )
