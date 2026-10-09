"""Audit 2026-10-02 F7: the stream path enforces timeout_seconds.

iter_cli_process_events left the read loop only when proc.poll() was set AND
both pipes hit EOF, so a grandchild holding stdout kept the loop spinning past
timeout_seconds forever. proc.wait(timeout) ran after the loop and its
TimeoutExpired branch killed the leader only.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from agent_discord.contracts import EventKind
from agent_discord.puppetmaster.backend import iter_cli_process_events


class _HangingPipe:
    """A pipe a grandchild still holds open: readline blocks, never EOF."""

    def __init__(self, release: threading.Event) -> None:
        self._release = release

    def readline(self) -> str:
        self._release.wait(10)
        return ""


class _OrphanHoldingStdout:
    """Leader has exited (poll() returns 0) but its pipes stay open."""

    pid = 4242

    def __init__(self, release: threading.Event) -> None:
        self.stdout = _HangingPipe(release)
        self.stderr = _HangingPipe(release)
        self.returncode = 0
        self.killed = False

    def poll(self) -> Optional[int]:
        return 0

    def wait(self, timeout: Any = None) -> int:
        return 0

    def terminate(self) -> None:
        self.killed = True

    def kill(self) -> None:
        self.killed = True


def test_stream_times_out_and_kills_the_group(monkeypatch) -> None:
    release = threading.Event()
    proc = _OrphanHoldingStdout(release)
    killed: list[dict[str, Any]] = []

    def fake_terminate(target, **kwargs):
        killed.append({"proc": target, **kwargs})
        release.set()
        return True

    monkeypatch.setattr(
        "agent_discord.puppetmaster.backend.terminate_process_group", fake_terminate
    )
    events = list(
        iter_cli_process_events(proc, model="openrouter/auto", timeout_seconds=0.1)
    )
    assert [event.kind for event in events] == [EventKind.ERROR]
    assert events[0].summary.message == "timeout"
    # The whole group, not just the leader.
    assert killed and killed[0]["proc"] is proc
    assert killed[0]["started_new_session"] is True
    release.set()


def test_stream_still_completes_a_fast_run(monkeypatch) -> None:
    class _Pipe:
        def __init__(self, lines: list[str]) -> None:
            self._lines = list(lines)

        def readline(self) -> str:
            return self._lines.pop(0) if self._lines else ""

    class _Done:
        pid = 7
        returncode = 0

        def __init__(self) -> None:
            self.stdout = _Pipe(["job_id: j1\n", "All set.\n"])
            self.stderr = _Pipe([])

        def poll(self) -> int:
            return 0

        def wait(self, timeout: Any = None) -> int:
            return 0

    monkeypatch.setattr(
        "agent_discord.puppetmaster.backend._start_delta_follower",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "agent_discord.puppetmaster.backend.measured_job_usage", lambda *a, **kw: {}
    )
    monkeypatch.setattr(
        "agent_discord.puppetmaster.backend.job_show_text", lambda *a, **kw: ""
    )
    events = list(
        iter_cli_process_events(_Done(), model="openrouter/auto", timeout_seconds=30)
    )
    assert events[-1].kind == EventKind.RECEIPT
    assert "All set." in events[-1].summary.message
