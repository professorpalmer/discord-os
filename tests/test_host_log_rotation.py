"""Audit 2026-10-02 G2-2: host.log rotates instead of growing forever."""

from __future__ import annotations

import io
from pathlib import Path

from agent_discord.host import logstream
from agent_discord.host.logstream import (
    HOST_LOG_GENERATIONS,
    HOST_LOG_MAX_BYTES,
    TimestampedStream,
    attach_host_log_rotation,
    maybe_rotate_host_log,
    rotate_host_log,
)


def _log(tmp_path: Path, body: str = "") -> Path:
    path = tmp_path / "host.log"
    path.write_text(body, encoding="utf-8")
    return path


def test_default_ceiling_is_ten_megabytes_and_three_generations():
    assert HOST_LOG_MAX_BYTES == 10 * 1024 * 1024
    assert HOST_LOG_GENERATIONS == 3


def test_under_the_ceiling_is_left_alone(tmp_path: Path):
    log = _log(tmp_path, "small\n")
    assert rotate_host_log(log, max_bytes=1024) is False
    assert log.read_text(encoding="utf-8") == "small\n"
    assert not (tmp_path / "host.log.1").exists()


def test_over_the_ceiling_copies_then_truncates_in_place(tmp_path: Path):
    log = _log(tmp_path, "x" * 64)
    inode = log.stat().st_ino
    assert rotate_host_log(log, max_bytes=16) is True
    # Same file, now empty: launchd's open descriptor still points at it.
    assert log.exists()
    assert log.stat().st_ino == inode
    assert log.read_text(encoding="utf-8") == ""
    assert (tmp_path / "host.log.1").read_text(encoding="utf-8") == "x" * 64


def test_rotation_keeps_at_most_three_generations(tmp_path: Path):
    log = _log(tmp_path)
    for marker in ("one", "two", "three", "four"):
        log.write_text(marker * 32, encoding="utf-8")
        assert rotate_host_log(log, max_bytes=16, generations=3) is True
    assert (tmp_path / "host.log.1").read_text(encoding="utf-8") == "four" * 32
    assert (tmp_path / "host.log.2").read_text(encoding="utf-8") == "three" * 32
    assert (tmp_path / "host.log.3").read_text(encoding="utf-8") == "two" * 32
    assert not (tmp_path / "host.log.4").exists()


def test_rotation_is_a_no_op_for_a_missing_log(tmp_path: Path):
    assert rotate_host_log(tmp_path / "nope.log", max_bytes=1, force=True) is False


def test_attach_rotates_at_startup(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(logstream, "_ROTATE_PATH", None)
    monkeypatch.setattr(logstream, "_ROTATE_NEXT_CHECK", 0.0)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "host.log").write_text("y" * 128, encoding="utf-8")
    path = attach_host_log_rotation(tmp_path, max_bytes=32, generations=3)
    assert path == logs / "host.log"
    assert (logs / "host.log").read_text(encoding="utf-8") == ""
    assert (logs / "host.log.1").read_text(encoding="utf-8") == "y" * 128
    assert logstream._ROTATE_PATH == path


def test_periodic_check_is_a_no_op_until_attached(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(logstream, "_ROTATE_PATH", None)
    monkeypatch.setattr(logstream, "_ROTATE_NEXT_CHECK", 0.0)
    assert maybe_rotate_host_log() is False


def test_periodic_check_throttles_to_the_interval(tmp_path: Path, monkeypatch):
    log = _log(tmp_path, "z" * 128)
    monkeypatch.setattr(logstream, "_ROTATE_PATH", log)
    monkeypatch.setattr(logstream, "_ROTATE_NEXT_CHECK", 0.0)
    monkeypatch.setattr(logstream, "_ROTATE_MAX_BYTES", 32)
    assert maybe_rotate_host_log() is True
    # Second call inside the interval does not even stat the file again.
    log.write_text("z" * 128, encoding="utf-8")
    assert maybe_rotate_host_log() is False
    assert log.read_text(encoding="utf-8") == "z" * 128


def test_writing_through_the_stamped_stream_triggers_rotation(tmp_path: Path, monkeypatch):
    log = _log(tmp_path, "w" * 128)
    monkeypatch.setattr(logstream, "_ROTATE_PATH", log)
    monkeypatch.setattr(logstream, "_ROTATE_NEXT_CHECK", 0.0)
    monkeypatch.setattr(logstream, "_ROTATE_MAX_BYTES", 32)
    stream = TimestampedStream(io.StringIO(), clock=lambda: "T")
    stream.write("host: tick\n")
    assert log.read_text(encoding="utf-8") == ""
    assert (tmp_path / "host.log.1").read_text(encoding="utf-8") == "w" * 128
