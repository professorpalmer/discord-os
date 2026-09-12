"""Path A: SSH remote cook — mock ssh, fail closed, no credential argv."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from agent_discord.contracts import (
    ContextSnapshot,
    DispatchRequest,
    EventKind,
    TaskStatus,
)
from agent_discord.host.remote_cook import (
    SSH_COOK_CAPABLE,
    SshRemoteCookBackend,
    assert_ssh_remote_cook_ready,
    build_remote_agentic_argv,
    probe_ssh_host,
    run_ssh_remote_cook,
    ssh_cook_enabled,
    spoken_ssh_unreachable,
)
from agent_discord.host.runners import HostAllowlistError, RemoteHost, host_runner_argv
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN


def _req(**meta) -> DispatchRequest:
    return DispatchRequest(
        task_id="t1",
        run_id="r1",
        prompt="review invoices",
        model=AGENTIC_MODEL_PIN.canonical,
        context=ContextSnapshot(task_id="t1", memories=(), bindings={}, provenance={}),
        metadata=meta or {"compute_mode": "analyze"},
    )


@dataclass
class _Proc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def test_ssh_cook_enabled_kill_switch(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_OS_SSH_COOK", raising=False)
    assert ssh_cook_enabled() is True
    monkeypatch.setenv("DISCORD_OS_SSH_COOK", "0")
    assert ssh_cook_enabled() is False


def test_probe_and_run_mock_ssh() -> None:
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    calls: list[list[str]] = []

    def _exec(argv, *, timeout_seconds=0):
        calls.append(list(argv))
        if argv and argv[-1] == "true":
            return _Proc(0)
        return _Proc(0, stdout=json.dumps({"summary": "ok from lab"}))

    ok, detail = probe_ssh_host(host, exec_fn=_exec)
    assert ok and SSH_COOK_CAPABLE in detail

    remote = build_remote_agentic_argv(_req())
    proc = run_ssh_remote_cook(host, remote, exec_fn=_exec)
    assert proc.returncode == 0
    assert all(c[:3] == ["ssh", "-o", "BatchMode=yes"] for c in calls)
    blob = " ".join(" ".join(c) for c in calls)
    assert "token=" not in blob
    assert "OPENROUTER" not in blob


def test_backend_dispatch_success_and_unreachable() -> None:
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")

    def _ok(argv, *, timeout_seconds=0):
        if argv and argv[-1] == "true":
            return _Proc(0)
        return _Proc(0, stdout=json.dumps({"summary": "remote done"}))

    backend = SshRemoteCookBackend(host=host, exec_fn=_ok, probe_first=True)
    result = backend.dispatch(_req(host_id="lab", host_kind="ssh", compute_mode="analyze"))
    assert result.status == TaskStatus.COMPLETED
    assert "remote done" in result.final_summary

    def _bad(argv, *, timeout_seconds=0):
        return _Proc(255, stderr="Connection refused")

    backend = SshRemoteCookBackend(host=host, exec_fn=_bad, probe_first=True)
    result = backend.dispatch(_req())
    assert result.status == TaskStatus.FAILED
    assert "Denied" in (result.final_summary or "")
    assert "lab" in (result.final_summary or "")


def test_assert_ready_fail_closed(monkeypatch) -> None:
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    monkeypatch.setenv("DISCORD_OS_SSH_COOK", "0")
    with pytest.raises(HostAllowlistError) as exc:
        assert_ssh_remote_cook_ready(host, exec_fn=lambda *a, **k: _Proc(0))
    assert "Denied" in str(exc.value.spoken)

    monkeypatch.setenv("DISCORD_OS_SSH_COOK", "1")

    def _bad(argv, *, timeout_seconds=0):
        return _Proc(255, stderr="No route to host")

    with pytest.raises(HostAllowlistError) as exc:
        assert_ssh_remote_cook_ready(host, exec_fn=_bad)
    assert "ssh unreachable" in str(exc.value.spoken).lower()
    assert spoken_ssh_unreachable("lab").startswith("Denied.")

    # local / None no-op
    assert_ssh_remote_cook_ready(None)
    assert_ssh_remote_cook_ready(
        RemoteHost(id="nas", label="NAS", kind="local", target="/tmp")
    )


def test_host_runner_argv_no_secrets_in_remote_cook_path() -> None:
    host = RemoteHost(
        id="lab",
        label="Lab",
        kind="ssh",
        target="cary@lab.local",
        workdir="/Users/cary/Projects",
    )
    remote = build_remote_agentic_argv(
        _req(host_workdir="/Users/cary/Projects", compute_mode="implement")
    )
    argv = host_runner_argv(host, remote)
    joined = " ".join(argv)
    assert argv[:3] == ["ssh", "-o", "BatchMode=yes"]
    assert "ghp_" not in joined
    assert "token=" not in joined
    assert "password=" not in joined


def test_ssh_stream_progress_pipe_before_receipt() -> None:
    """Path A stream yields PROGRESS from remote lines before the final receipt."""

    import threading
    import time

    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")

    class _Pipe:
        def __init__(self, lines: list[str]) -> None:
            self._lines = list(lines)
            self._idx = 0
            self._closed = threading.Event()

        def readline(self) -> str:
            if self._idx < len(self._lines):
                line = self._lines[self._idx]
                self._idx += 1
                # Pace lines so the consumer can observe mid-stream progress.
                if self._idx == 2:
                    time.sleep(0.05)
                return line
            self._closed.wait(timeout=2)
            return ""

    class _Child:
        def __init__(self) -> None:
            self.pid = 77
            self.returncode = None
            self.stdout = _Pipe(
                [
                    "DISCORD_OS_REMOTE_PID=4242\n",
                    "progress: 35% stage: plan drafting approach\n",
                    '{"type":"token","content":"editing invoices.py"}\n',
                    json.dumps({"summary": "remote live done"}) + "\n",
                ]
            )
            self.stderr = _Pipe([])
            self._done = threading.Event()
            threading.Thread(target=self._finish, daemon=True).start()

        def _finish(self) -> None:
            # After stdout lines are queued by the reader, mark complete.
            time.sleep(0.2)
            self.returncode = 0
            self.stdout._closed.set()
            self.stderr._closed.set()
            self._done.set()

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self._done.wait(timeout=timeout or 2)
            return self.returncode if self.returncode is not None else 0

        def terminate(self) -> None:
            self.returncode = -15
            self.stdout._closed.set()
            self.stderr._closed.set()

        def kill(self) -> None:
            self.terminate()

    child = _Child()

    def _popen(argv):
        assert argv[:3] == ["ssh", "-o", "BatchMode=yes"]
        blob = " ".join(argv)
        assert "OPENROUTER" not in blob
        assert "token=" not in blob
        return child

    backend = SshRemoteCookBackend(
        host=host, probe_first=False, popen_fn=_popen, timeout_seconds=5.0
    )
    events = list(backend.stream(_req(host_id="lab", host_kind="ssh", compute_mode="analyze")))
    kinds = [e.kind for e in events]
    assert EventKind.DISPATCH in kinds
    assert EventKind.PROGRESS in kinds
    assert EventKind.RECEIPT in kinds
    assert kinds.index(EventKind.PROGRESS) < kinds.index(EventKind.RECEIPT)
    assert kinds.index(EventKind.DISPATCH) < kinds.index(EventKind.PROGRESS)
    progress = [e for e in events if e.kind == EventKind.PROGRESS]
    assert any("35" in (e.summary.message or "") or e.summary.percent == 35.0 for e in progress) or any(
        "invoices" in (e.summary.message or "") or "invoices" in str(e.summary.details)
        for e in progress
    )
    assert all(e.summary.details.get("host_id") == "lab" for e in progress)
    receipt = next(e for e in events if e.kind == EventKind.RECEIPT)
    assert "remote live done" in receipt.summary.message
    assert backend.status("r1") == TaskStatus.COMPLETED
    assert backend._remote_pids.get("r1") in {None, 4242}  # cleared after unregister
