"""P0.1 Cancel honesty — local agentic + mocked SSH actually kill or speak unconfirmed."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from agent_discord.contracts import (
    DispatchRequest,
    TaskIntake,
    TaskStatus,
    ContextSnapshot,
)
from agent_discord.host.remote_cook import (
    SshRemoteCookBackend,
    wrap_remote_command_with_pid_echo,
)
from agent_discord.host.runners import RemoteHost
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.agentic import AgenticPuppetmasterBackend
from agent_discord.puppetmaster.cancel_honesty import (
    CANCEL_UNCONFIRMED_SPOKEN,
    cancel_receipt,
    popen_kwargs_for_killable_child,
    terminate_process_group,
)
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN


def _req(run_id: str = "r-cancel") -> DispatchRequest:
    return DispatchRequest(
        task_id="t1",
        run_id=run_id,
        prompt="sleep forever",
        model=AGENTIC_MODEL_PIN.canonical,
        context=ContextSnapshot(task_id="t1", memories=(), bindings={}, provenance={}),
        metadata={"compute_mode": "analyze"},
    )


def test_cancel_receipt_shapes() -> None:
    ok = cancel_receipt(confirmed=True, run_id="r1")
    assert ok.confirmed is True
    assert ok.cancellation_pending is False
    assert ok.status == "cancelled"
    pending = cancel_receipt(confirmed=False, run_id="r1")
    assert pending.confirmed is False
    assert pending.cancellation_pending is True
    assert pending.status == "cancellation_pending"
    assert pending.spoken == CANCEL_UNCONFIRMED_SPOKEN


def test_terminate_process_group_kills_session_child() -> None:
    if sys.platform == "win32":
        pytest.skip("posix process-group kill")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **popen_kwargs_for_killable_child(),
    )
    try:
        assert terminate_process_group(proc, grace_seconds=0.4, started_new_session=True)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_agentic_cancel_without_child_is_unconfirmed() -> None:
    backend = AgenticPuppetmasterBackend(cli="puppetmaster-missing-xyz")
    assert backend.cancel("no-such-run") is False


def test_agentic_cancel_kills_tracked_child() -> None:
    """Local agentic: Cancel terminates the tracked process group."""

    if sys.platform == "win32":
        pytest.skip("posix process-group kill")

    backend = AgenticPuppetmasterBackend(cli="puppetmaster-missing-xyz")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **popen_kwargs_for_killable_child(),
    )
    backend._register_child("run-local", proc)
    backend._statuses["run-local"] = TaskStatus.RUNNING
    try:
        assert backend.cancel("run-local") is True
        assert proc.poll() is not None
        assert backend.status("run-local") == TaskStatus.CANCELLED
        receipt = backend.cancel_receipt_for("run-local")
        assert receipt.confirmed is True
        assert receipt.cancellation_pending is False
    finally:
        if proc.poll() is None:
            proc.kill()


def test_orch_apply_cancel_unconfirmed_does_not_paint_cancelled(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "c.sqlite3")
    store.initialize()
    backend = AgenticPuppetmasterBackend(cli="missing-cli-xyz")
    orch = AgentOrchestrator(store=store, backend=backend, discord=None)
    store.create_task(
        task_id="t-unconf",
        workspace_id="ws",
        channel_id="ch",
        intake_text="hi",
    )
    store.create_run(
        run_id="r-unconf",
        task_id="t-unconf",
        model="openrouter/auto",
        adapter_name="agentic",
        status=TaskStatus.RUNNING,
    )
    result = orch.apply_job_action("cancel", "r-unconf")
    assert result["confirmed"] is False
    assert result["cancellation_pending"] is True
    assert result["spoken"] == CANCEL_UNCONFIRMED_SPOKEN
    assert result["status"] == "cancellation_pending"
    row = store.get_run("r-unconf")
    assert row["status"] == TaskStatus.RUNNING.value
    store.close()


def test_orch_apply_cancel_confirmed_paints_cancelled(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "c2.sqlite3")
    store.initialize()
    backend = FakePuppetmasterBackend()
    orch = AgentOrchestrator(store=store, backend=backend, discord=None)
    receipt = orch.run_task(TaskIntake(text="ok", channel_id="ch", workspace_id="ws"))
    store.update_run(receipt.run_id, status=TaskStatus.RUNNING)
    result = orch.apply_job_action("cancel", receipt.run_id)
    assert result["confirmed"] is True
    assert result["status"] == "cancelled"
    assert store.get_run(receipt.run_id)["status"] == TaskStatus.CANCELLED.value
    store.close()


class _Pipe:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self._idx = 0
        self._closed = threading.Event()

    def readline(self) -> str:
        if self._idx < len(self._lines):
            line = self._lines[self._idx]
            self._idx += 1
            return line
        self._closed.wait(timeout=5)
        return ""


class _FakeSshChild:
    def __init__(self) -> None:
        self.pid = 4242
        self.returncode = None
        self.stdout = _Pipe(["DISCORD_OS_REMOTE_PID=4242\n", "working\n"])
        self.stderr = _Pipe([])
        self._lock = threading.Lock()

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        with self._lock:
            if self.returncode is None:
                self.returncode = -15
        self.stdout._closed.set()
        self.stderr._closed.set()

    def kill(self) -> None:
        with self._lock:
            self.returncode = -9
        self.stdout._closed.set()
        self.stderr._closed.set()

    def wait(self, timeout=None):
        deadline = time.time() + (timeout or 2)
        while self.returncode is None and time.time() < deadline:
            time.sleep(0.05)
        return self.returncode if self.returncode is not None else -9


def test_ssh_cancel_kills_local_child_and_tries_remote(monkeypatch) -> None:
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    child = _FakeSshChild()
    remote_signals: list[tuple] = []

    def _popen(argv):
        assert argv[:3] == ["ssh", "-o", "BatchMode=yes"]
        return child

    def _remote_signal(target, pid, **kwargs):
        remote_signals.append((target, pid))
        return True

    monkeypatch.setattr(
        "agent_discord.host.remote_cook.ssh_remote_signal",
        _remote_signal,
    )
    monkeypatch.setattr(
        "agent_discord.host.remote_cook.ssh_controlmaster_exit",
        lambda *a, **k: False,
    )

    backend = SshRemoteCookBackend(
        host=host,
        probe_first=False,
        popen_fn=_popen,
        timeout_seconds=10.0,
    )

    done = threading.Event()
    result_box: list = []

    def _cook() -> None:
        result_box.append(backend.dispatch(_req("run-ssh")))
        done.set()

    thread = threading.Thread(target=_cook, daemon=True)
    thread.start()
    deadline = time.time() + 3
    while time.time() < deadline and "run-ssh" not in backend._children:
        time.sleep(0.05)
    while time.time() < deadline and not backend._remote_pids.get("run-ssh"):
        time.sleep(0.05)
    assert backend._remote_pids.get("run-ssh") == 4242
    assert backend.cancel("run-ssh") is True
    assert done.wait(timeout=5)
    assert child.returncode is not None
    assert backend.status("run-ssh") == TaskStatus.CANCELLED
    assert remote_signals and remote_signals[0] == ("cary@lab.local", 4242)
    assert result_box[0].status == TaskStatus.CANCELLED


def test_ssh_cancel_without_child_unconfirmed() -> None:
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    backend = SshRemoteCookBackend(host=host, probe_first=False)
    assert backend.cancel("missing") is False
    receipt = backend.cancel_receipt_for("missing")
    assert receipt.cancellation_pending is True
    assert receipt.spoken == CANCEL_UNCONFIRMED_SPOKEN


def test_wrap_remote_pid_echo_has_no_secrets() -> None:
    wrapped = wrap_remote_command_with_pid_echo(
        ["puppetmaster", "agentic", "hello", "--provider", "openrouter"]
    )
    blob = " ".join(wrapped)
    assert "DISCORD_OS_REMOTE_PID=$$" in blob
    assert "OPENROUTER" not in blob
    assert "token=" not in blob
