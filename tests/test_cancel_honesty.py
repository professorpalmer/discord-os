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
    assert "DISCORD_OS_REMOTE_PID=" in blob
    assert "$$" in blob
    assert "printf" in blob
    assert "OPENROUTER" not in blob
    assert "token=" not in blob


def test_resolve_ssh_control_path_from_env(monkeypatch) -> None:
    from agent_discord.puppetmaster.cancel_honesty import resolve_ssh_control_path

    monkeypatch.setenv("DISCORD_OS_SSH_CONTROL_PATH", "/tmp/dos-%r@%h:%p")
    assert resolve_ssh_control_path() == "/tmp/dos-%r@%h:%p"
    assert resolve_ssh_control_path(explicit="/explicit") == "/explicit"


def test_host_runner_argv_adds_controlmaster_when_path_set() -> None:
    from agent_discord.host.runners import RemoteHost, host_runner_argv

    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    argv = host_runner_argv(
        host,
        ["true"],
        control_path="/tmp/dos-cm-%r@%h:%p",
    )
    joined = " ".join(argv)
    assert "ControlMaster=auto" in joined
    assert "ControlPath=/tmp/dos-cm-%r@%h:%p" in joined
    assert "BatchMode=yes" in joined
    assert "OPENROUTER" not in joined


def test_orchestrator_cancel_uses_path_a_cook_backend(tmp_path) -> None:
    """Path A Cancel must call the SSH cook backend, not only local agentic."""

    from agent_discord.orchestration.orchestrator import AgentOrchestrator
    from agent_discord.persistence.sqlite import SQLiteStore
    from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN

    class _Local:
        pin = AGENTIC_MODEL_PIN
        cancelled = False

        def resolve_model(self, requested: str):
            return self.pin

        def cancel(self, run_id: str) -> bool:
            self.cancelled = True
            return False

        def status(self, run_id: str):
            from agent_discord.contracts import TaskStatus

            return TaskStatus.RUNNING

    class _Ssh:
        cancelled_ids: list[str] = []

        def cancel(self, run_id: str) -> bool:
            self.cancelled_ids.append(run_id)
            return True

        def status(self, run_id: str):
            from agent_discord.contracts import TaskStatus

            return TaskStatus.CANCELLED

    store = SQLiteStore(tmp_path / "cancel-path-a.sqlite3")
    store.initialize()
    local = _Local()
    ssh = _Ssh()
    orch = AgentOrchestrator(store=store, backend=local, post_progress_to_discord=False)
    orch._cook_backends["run-ssh"] = ssh
    store.create_task(
        task_id="t1",
        workspace_id="ws",
        channel_id="ch",
        intake_text="cook",
    )
    from agent_discord.contracts import TaskStatus as TS
    store.create_run(run_id="run-ssh", task_id="t1", model="m", adapter_name="a", status=TS.RUNNING)
    out = orch._cancel_live_cook("run-ssh")
    assert out["confirmed"] is True
    assert ssh.cancelled_ids == ["run-ssh"]
    assert local.cancelled is False


def test_wrap_remote_pid_echo_has_orphan_watchdog() -> None:
    wrapped = wrap_remote_command_with_pid_echo(
        ["puppetmaster", "agentic", "hello", "--provider", "openrouter"]
    )
    blob = " ".join(wrapped)
    assert "trap" in blob
    assert "HUP" in blob
    assert "oppid" in blob
    assert "exec " not in blob
    assert "OPENROUTER_API_KEY" not in blob


def test_ssh_controlmaster_fresh_clears_stale(monkeypatch, tmp_path: Path) -> None:
    from agent_discord.puppetmaster.cancel_honesty import (
        ensure_ssh_controlmaster_fresh,
        ssh_controlmaster_check,
    )

    sock = tmp_path / "cm.sock"
    sock.write_text("stale", encoding="utf-8")
    calls: list[str] = []

    class _Proc:
        def __init__(self, code: int) -> None:
            self.returncode = code

    def _exec(argv, timeout_seconds=5.0):
        joined = " ".join(argv)
        calls.append(joined)
        if "-O check" in joined:
            return _Proc(1)  # stale / missing master
        if "-O exit" in joined:
            return _Proc(0)
        return _Proc(1)

    assert (
        ensure_ssh_controlmaster_fresh(
            "cary@lab.local", control_path=str(sock), exec_fn=_exec
        )
        is True
    )
    assert any("-O check" in c for c in calls)
    assert any("-O exit" in c for c in calls)
    assert not sock.exists()
    assert ssh_controlmaster_check("", control_path=str(sock)) is False


def test_remote_pid_sidecar_reap_orphans(tmp_path: Path) -> None:
    import json
    import time

    from agent_discord.puppetmaster.cancel_honesty import (
        clear_remote_pid_sidecar,
        persist_remote_pid_sidecar,
        reap_orphaned_remote_pids,
    )

    path = persist_remote_pid_sidecar(
        run_id="run-orphan",
        remote_pid=4242,
        host_target="cary@lab.local",
        host_id="lab",
        gate_root=tmp_path,
    )
    assert path
    # Fresh sidecar (<30s) must not reap a live cook.
    assert reap_orphaned_remote_pids(gate_root=tmp_path) == []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["created_at_ms"] = int(time.time() * 1000) - 90_000
    Path(path).write_text(json.dumps(data), encoding="utf-8")
    signals: list[tuple] = []

    class _Proc:
        returncode = 0

    def _exec(argv, timeout_seconds=8.0):
        # argv: ssh … target remote-kill-cmd
        signals.append((argv[-2], argv[-1]))
        return _Proc()

    out = reap_orphaned_remote_pids(gate_root=tmp_path, exec_fn=_exec)
    assert len(out) == 1
    assert out[0]["signaled"] is True
    assert out[0]["remote_pid"] == 4242
    assert signals and "4242" in signals[0][1]
    assert not Path(path).exists()
    clear_remote_pid_sidecar("missing", gate_root=tmp_path)


def test_orch_settle_honors_cancel_over_completed(tmp_path: Path) -> None:
    """Settle-vs-Cancel: Cancel mid-stream must not be overwritten by Completed."""

    from agent_discord.contracts import (
        DispatchEvent,
        DispatchRequest,
        DispatchResult,
        EventKind,
        ProgressSummary,
        TaskIntake,
        TaskStatus,
    )
    from agent_discord.orchestration.orchestrator import AgentOrchestrator
    from agent_discord.persistence.sqlite import SQLiteStore
    from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN

    class _StreamBackend:
        pin = AGENTIC_MODEL_PIN

        def resolve_model(self, requested: str):
            return self.pin

        def available(self) -> bool:
            return True

        def status(self, run_id: str):
            return TaskStatus.CANCELLED

        def cancel(self, run_id: str) -> bool:
            return True

        def stream(self, request: DispatchRequest):
            yield DispatchEvent(
                kind=EventKind.RECEIPT,
                summary=ProgressSummary(stage="done", message="late answer", percent=100.0),
                payload={"summary": "late answer"},
            )

        def dispatch(self, request: DispatchRequest) -> DispatchResult:
            return DispatchResult(
                run_id=request.run_id,
                status=TaskStatus.COMPLETED,
                events=tuple(self.stream(request)),
                final_summary="late answer",
            )

    store = SQLiteStore(tmp_path / "settle-cancel.sqlite3")
    store.initialize()
    backend = _StreamBackend()
    orch = AgentOrchestrator(
        store=store, backend=backend, post_progress_to_discord=False
    )

    # Pre-mark cancel so settle guard sees CANCELLED while stream yields RECEIPT.
    original_stream = backend.stream

    def _stream_then_cancel(request: DispatchRequest):
        orch._run_status[request.run_id] = TaskStatus.CANCELLED
        yield from original_stream(request)

    backend.stream = _stream_then_cancel  # type: ignore[method-assign]
    receipt = orch.run_task(
        TaskIntake(text="what is Discord OS?", channel_id="ch", workspace_id="ws")
    )
    assert receipt.status == TaskStatus.CANCELLED
    assert store.get_run(receipt.run_id)["status"] == TaskStatus.CANCELLED.value
    store.close()
