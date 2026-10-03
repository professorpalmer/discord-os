"""Audit 2026-10-02 G2-2: host.log lines carry a timestamp."""

from __future__ import annotations

import io
import sys

from agent_discord.host import logstream
from agent_discord.host.logstream import TimestampedStream, install_host_logging, local_timestamp


def test_timestamped_stream_stamps_each_complete_line():
    sink = io.StringIO()
    stream = TimestampedStream(sink, clock=lambda: "2026-10-02T21:20:00-04:00")
    print("host: starting", file=stream)
    print("cleared 2 leftover running job(s)", file=stream)
    assert sink.getvalue() == (
        "2026-10-02T21:20:00-04:00 host: starting\n"
        "2026-10-02T21:20:00-04:00 cleared 2 leftover running job(s)\n"
    )


def test_timestamped_stream_stamps_multiline_write_per_line():
    sink = io.StringIO()
    stream = TimestampedStream(sink, clock=lambda: "T")
    stream.write("a\nb\n")
    assert sink.getvalue() == "T a\nT b\n"


def test_timestamped_stream_holds_partial_line_until_newline():
    sink = io.StringIO()
    stream = TimestampedStream(sink, clock=lambda: "T")
    stream.write("half")
    assert sink.getvalue() == ""
    stream.write(" line\n")
    assert sink.getvalue() == "T half line\n"


def test_timestamped_stream_drain_emits_trailing_partial():
    sink = io.StringIO()
    stream = TimestampedStream(sink, clock=lambda: "T")
    stream.write("no newline")
    stream.drain()
    assert sink.getvalue() == "T no newline\n"


def test_install_host_logging_wraps_stdout_and_stderr(monkeypatch):
    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.setattr(logstream, "_INSTALLED", False)
    assert install_host_logging(clock=lambda: "T") is True
    print("bare print from anywhere", flush=True)
    print("to stderr", file=sys.stderr, flush=True)
    assert out.getvalue() == "T bare print from anywhere\n"
    assert err.getvalue() == "T to stderr\n"


def test_install_host_logging_is_idempotent(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    monkeypatch.setattr(logstream, "_INSTALLED", False)
    assert install_host_logging() is True
    assert install_host_logging() is False


def test_install_host_logging_no_op_at_a_terminal(monkeypatch):
    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    tty_out = _Tty()
    tty_err = _Tty()
    monkeypatch.setattr(sys, "stdout", tty_out)
    monkeypatch.setattr(sys, "stderr", tty_err)
    monkeypatch.setattr(logstream, "_INSTALLED", False)
    assert install_host_logging() is False
    assert sys.stdout is tty_out
    assert sys.stderr is tty_err


def test_local_timestamp_is_iso_8601_with_offset():
    stamp = local_timestamp()
    assert stamp[4] == "-" and stamp[10] == "T"
    # Offset or Z suffix, never a naive stamp.
    assert stamp[-6] in {"+", "-"} or stamp.endswith("Z")
