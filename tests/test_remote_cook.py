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
    SSH_REMOTE_CLI_MISSING,
    SSH_REMOTE_OPENROUTER_MISSING,
    SshProbeResult,
    SshRemoteCookBackend,
    assert_ssh_remote_cook_ready,
    build_remote_agentic_argv,
    probe_ssh_host,
    probe_ssh_remote_ready,
    run_ssh_remote_cook,
    ssh_cook_enabled,
    spoken_ssh_probe_deny,
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


def _ready_stdout(cli: str = "puppetmaster", openrouter: str = "env") -> str:
    return f"DISCORD_OS_SSH_PROBE cli={cli} openrouter={openrouter}\n"


def _is_probe_argv(argv: list[str]) -> bool:
    return "bash" in argv and any("DISCORD_OS_SSH_PROBE" in str(part) for part in argv)


def test_probe_and_run_mock_ssh() -> None:
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    calls: list[list[str]] = []

    def _exec(argv, *, timeout_seconds=0):
        calls.append(list(argv))
        if _is_probe_argv(argv):
            return _Proc(0, stdout=_ready_stdout())
        return _Proc(0, stdout=json.dumps({"summary": "ok from lab"}))

    ok, detail = probe_ssh_host(host, exec_fn=_exec)
    assert ok and SSH_COOK_CAPABLE in detail
    assert "cli=puppetmaster" in detail
    assert "openrouter=env" in detail

    remote = build_remote_agentic_argv(_req())
    proc = run_ssh_remote_cook(host, remote, exec_fn=_exec)
    assert proc.returncode == 0
    assert all(c[:3] == ["ssh", "-o", "BatchMode=yes"] for c in calls)
    blob = " ".join(" ".join(c) for c in calls)
    assert "token=" not in blob
    # Probe script may mention the env *name*; cook argv must not carry a secret value.
    cook_blobs = [" ".join(c) for c in calls if not _is_probe_argv(c)]
    assert cook_blobs
    assert all("sk-or-" not in b and "token=" not in b for b in cook_blobs)


def test_probe_reports_missing_cli_and_openrouter() -> None:
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")

    def _no_cli(argv, *, timeout_seconds=0):
        return _Proc(11, stdout=_ready_stdout(cli="missing", openrouter="env"))

    result = probe_ssh_remote_ready(host, exec_fn=_no_cli)
    assert result.ok is False
    assert result.reason == SSH_REMOTE_CLI_MISSING
    spoken = spoken_ssh_probe_deny("lab", result)
    assert "Denied" in spoken and "CLI missing" in spoken
    assert "sk-or" not in spoken

    def _no_or(argv, *, timeout_seconds=0):
        return _Proc(12, stdout=_ready_stdout(cli="puppetmaster", openrouter="missing"))

    result = probe_ssh_remote_ready(host, exec_fn=_no_or)
    assert result.ok is False
    assert result.reason == SSH_REMOTE_OPENROUTER_MISSING
    spoken = spoken_ssh_probe_deny("lab", result)
    assert "OpenRouter" in spoken
    assert "sk-or" not in spoken


def test_backend_dispatch_success_and_unreachable() -> None:
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")

    def _ok(argv, *, timeout_seconds=0):
        if _is_probe_argv(argv):
            return _Proc(0, stdout=_ready_stdout())
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

    def _no_or(argv, *, timeout_seconds=0):
        return _Proc(12, stdout=_ready_stdout(cli="puppetmaster", openrouter="missing"))

    with pytest.raises(HostAllowlistError) as exc:
        assert_ssh_remote_cook_ready(host, exec_fn=_no_or)
    assert "openrouter" in str(exc.value.spoken).lower()

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


def test_ssh_gates_need_and_wrap(monkeypatch):
    from agent_discord.host.remote_cook import spoken_ssh_gates_need
    from agent_discord.orchestration.ssh_gate import (
        remote_gate_inject_script,
        ssh_gates_cross,
        spoken_ssh_gates_need as need,
        wrap_remote_argv_with_ssh_gate,
    )

    assert "gates do not cross SSH" in need("box-1")
    assert "gates do not cross SSH" in spoken_ssh_gates_need("box-1")
    assert ssh_gates_cross() is False
    monkeypatch.delenv("DISCORD_OS_SSH_GATES", raising=False)
    plain = ["puppetmaster", "agentic", "hi"]
    assert wrap_remote_argv_with_ssh_gate(plain, enabled=False) == plain
    wrapped = wrap_remote_argv_with_ssh_gate(plain, enabled=True)
    assert wrapped[0] == "bash"
    assert "DISCORD_OS_SSH_WRITE_GATE=1" in wrapped[-1]
    assert "AgenticAdapter" in remote_gate_inject_script()
    assert "_execute_tool" in remote_gate_inject_script()


def test_ssh_stream_emits_gates_need(monkeypatch):
    """Write-gate on + SSH → PROGRESS Need before cook (honest gap)."""

    from agent_discord.contracts import EventKind
    from agent_discord.host.remote_cook import SshRemoteCookBackend
    from agent_discord.host.runners import RemoteHost

    host = RemoteHost(id="lab", kind="ssh", target="lab.example", label="lab")
    backend = SshRemoteCookBackend(host=host, probe_first=False)

    class _Child:
        stdout = None
        stderr = None
        returncode = 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def communicate(self, timeout=None):
            return ('{"type":"result","result":"ok"}\n', "")

    backend.popen_fn = lambda argv, stdin_data=None: _Child()
    monkeypatch.setattr(
        backend,
        "_preflight_deny",
        lambda: None,
    )
    req = _req(ssh_write_gate=True, compute_mode="analyze")
    events = list(backend.stream(req))
    need_msgs = [
        e.summary.message
        for e in events
        if getattr(e, "kind", None) == EventKind.PROGRESS
        and "gates" in (e.summary.message or "")
    ]
    assert need_msgs, f"expected Need progress, got {[getattr(e.summary,'message',e) for e in events]}"


def test_ssh_gates_bridge_wrap_and_parse(monkeypatch, tmp_path):
    from agent_discord.orchestration.ssh_gate import (
        encode_gate_pending_line,
        mirror_gate_pending_to_local,
        parse_gate_pending_line,
        remote_gate_bridge_inject_script,
        ssh_gates_cross,
        ssh_write_gate_result,
        wrap_remote_argv_with_ssh_gate_bridge,
    )
    from agent_discord.orchestration.gate_hook import list_pending, complete_request, GateHoldResult

    monkeypatch.setenv("DISCORD_OS_SSH_GATES", "bridge")
    assert ssh_gates_cross() is True
    monkeypatch.delenv("DISCORD_OS_SSH_GATES", raising=False)
    assert ssh_gates_cross() is False

    assert wrap_remote_argv_with_ssh_gate_bridge([], run_id="r1") == []
    assert wrap_remote_argv_with_ssh_gate_bridge(["pm"], run_id="") == []
    wrapped = wrap_remote_argv_with_ssh_gate_bridge(
        ["puppetmaster", "agentic", "hi"],
        run_id="run-bridge-1",
        remote_gate_dir="/tmp/discord-os-ssh-gate-run-bridge-1",
        timeout_seconds=30,
    )
    assert wrapped[0] == "bash"
    script = wrapped[-1]
    assert "DISCORD_OS_SSH_GATE_BRIDGE=1" in script
    assert "DISCORD_OS_RUN_ID=run-bridge-1" in script
    assert "DISCORD_OS_SSH_GATE_DIR=" in script
    assert "sitecustomize.py" in script
    assert "DISCORD_OS_GATE_PENDING" in remote_gate_bridge_inject_script()

    payload = {
        "v": 1,
        "request_id": "abc123",
        "run_id": "run-bridge-1",
        "tool_name": "write_file",
        "tool_class": "write_file",
        "detail": "src/x.py",
        "kind": "tool_class",
        "question": "",
        "options": [],
        "allow_multiple": False,
        "created_at_ms": 1,
        "remote_gate_dir": "/tmp/discord-os-ssh-gate-run-bridge-1",
        "ssh_bridge": True,
    }
    line = encode_gate_pending_line(payload)
    assert line.startswith("DISCORD_OS_GATE_PENDING=")
    parsed = parse_gate_pending_line(line + "\n")
    assert parsed is not None
    assert parsed["request_id"] == "abc123"
    assert parse_gate_pending_line("noise") is None

    mirrored = mirror_gate_pending_to_local(payload, gate_root=tmp_path / "gates")
    assert mirrored is not None
    pending = list_pending(tmp_path / "gates" / "run-bridge-1")
    assert len(pending) == 1
    assert pending[0].tool_name == "write_file"

    writes: list[list[str]] = []

    class _Proc:
        returncode = 0

    def _exec(argv, timeout_seconds=15.0):
        writes.append(list(argv))
        return _Proc()

    ok = ssh_write_gate_result(
        "lab.example",
        "/tmp/discord-os-ssh-gate-run-bridge-1",
        {"request_id": "abc123", "decision": "allow", "gate_result": "allow"},
        exec_fn=_exec,
    )
    assert ok is True
    assert writes and writes[0][0] == "ssh"
    assert "BatchMode=yes" in writes[0]
    assert "lab.example" in writes[0]
    assert "abc123.json" in writes[0][-1]


def test_ssh_stream_bridge_mirrors_pending_and_writeback(monkeypatch, tmp_path):
    """Bridge on → GATE_PENDING mirrored locally; Allow result SSH-written back."""

    import threading
    import time

    from agent_discord.contracts import EventKind
    from agent_discord.host.remote_cook import SshRemoteCookBackend
    from agent_discord.host.runners import RemoteHost
    from agent_discord.orchestration.gate_hook import (
        GateHoldResult,
        complete_request,
        ensure_run_gate_dir,
        run_gate_dir,
    )
    from agent_discord.orchestration.ssh_gate import encode_gate_pending_line

    monkeypatch.setenv("DISCORD_OS_SSH_GATES", "bridge")
    host = RemoteHost(id="lab", kind="ssh", target="lab.example", label="lab")
    gate_root = tmp_path / "gates"
    backend = SshRemoteCookBackend(
        host=host, probe_first=False, gate_root=gate_root, timeout_seconds=5.0
    )

    payload = {
        "v": 1,
        "request_id": "req99",
        "run_id": "r-bridge",
        "tool_name": "run_terminal",
        "tool_class": "run_terminal",
        "detail": "ls",
        "kind": "tool_class",
        "question": "",
        "options": [],
        "allow_multiple": False,
        "created_at_ms": 1,
        "remote_gate_dir": "/tmp/discord-os-ssh-gate-r-bridge",
        "ssh_bridge": True,
    }

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
            self._closed.wait(timeout=2)
            return ""

    class _Child:
        def __init__(self) -> None:
            self.returncode = None
            self.stdout = _Pipe(
                [
                    "DISCORD_OS_REMOTE_PID=4242\n",
                    encode_gate_pending_line(payload) + "\n",
                    '{"type":"result","result":"remote ok"}\n',
                ]
            )
            self.stderr = _Pipe([])
            self._done = threading.Event()
            threading.Thread(target=self._finish, daemon=True).start()

        def _finish(self) -> None:
            time.sleep(0.25)
            self.returncode = 0
            self.stdout._closed.set()
            self.stderr._closed.set()
            self._done.set()

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self._done.wait(timeout=timeout or 2)
            return self.returncode if self.returncode is not None else 0

        def communicate(self, timeout=None):
            self.wait(timeout=timeout)
            return ("", "")

        def terminate(self) -> None:
            self.returncode = -15
            self.stdout._closed.set()
            self.stderr._closed.set()

        def kill(self) -> None:
            self.terminate()

    writes: list[str] = []

    class _ExecProc:
        returncode = 0

    def _exec(argv, timeout_seconds=15.0):
        writes.append(" ".join(argv))
        return _ExecProc()

    run_dir = ensure_run_gate_dir(run_gate_dir(gate_root, "r-bridge"))

    def _auto_allow_on_pending(run_id, line):
        event = SshRemoteCookBackend._note_bridge_pending(backend, run_id, line)
        if event is not None and "req99" in str(getattr(event.summary, "details", {})):
            complete_request(
                run_dir,
                GateHoldResult(
                    request_id="req99",
                    decision="allow",
                    reason="test allow",
                    tool_class="shell",
                ),
            )
        return event

    backend.exec_fn = _exec
    backend.popen_fn = lambda argv, stdin_data=None: _Child()
    monkeypatch.setattr(backend, "_preflight_deny", lambda: None)
    monkeypatch.setattr(backend, "_note_bridge_pending", _auto_allow_on_pending)

    req = DispatchRequest(
        task_id="t1",
        run_id="r-bridge",
        prompt="implement bridge hold",
        model=AGENTIC_MODEL_PIN.canonical,
        context=ContextSnapshot(task_id="t1", memories=(), bindings={}, provenance={}),
        metadata={"compute_mode": "implement"},
    )
    events = list(backend.stream(req))
    bridge_msgs = [
        e.summary.message
        for e in events
        if e.kind == EventKind.PROGRESS
        and (e.summary.details or {}).get("ssh_gates") == "bridge"
    ]
    assert bridge_msgs, (
        f"expected bridge progress, got {[(e.kind, e.summary.message) for e in events]}"
    )
    assert any(
        "bridge armed" in (m or "").lower() or "Waiting for Allow" in (m or "")
        for m in bridge_msgs
    )
    assert any("req99.json" in w for w in writes), writes


def test_ssh_stream_bridge_fail_closed_missing_run_id(monkeypatch):
    from agent_discord.contracts import EventKind
    from agent_discord.host.remote_cook import SshRemoteCookBackend
    from agent_discord.host.runners import RemoteHost
    from agent_discord.contracts import DispatchRequest

    monkeypatch.setenv("DISCORD_OS_SSH_GATES", "bridge")
    host = RemoteHost(id="lab", kind="ssh", target="lab.example", label="lab")
    backend = SshRemoteCookBackend(host=host, probe_first=False)
    monkeypatch.setattr(backend, "_preflight_deny", lambda: None)
    backend.popen_fn = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not spawn"))

    req = DispatchRequest(
        task_id="t1",
        run_id="",
        prompt="hi",
        model=AGENTIC_MODEL_PIN.canonical,
        context=ContextSnapshot(task_id="t1", memories=(), bindings={}, provenance={}),
        metadata={"compute_mode": "analyze"},
    )
    # empty run_id on request — bridge must Deny before spawn
    # Some code paths use request.run_id from _req; force empty via object
    events = list(backend.stream(req))
    assert any(e.kind == EventKind.ERROR for e in events)
    assert any("bridge cannot arm" in (e.summary.message or "").lower() or "Fail closed" in (e.summary.message or "") for e in events)


def test_ssh_cancel_skips_allow_writeback_and_denies_pending(monkeypatch, tmp_path):
    """Gate-bridge writeback race: Cancel must not SSH-write Allow; Deny pending."""

    import threading
    import time

    from agent_discord.contracts import EventKind
    from agent_discord.host.remote_cook import SshRemoteCookBackend
    from agent_discord.host.runners import RemoteHost
    from agent_discord.orchestration.gate_hook import (
        GateHoldResult,
        complete_request,
        ensure_run_gate_dir,
        read_result,
        run_gate_dir,
    )
    from agent_discord.orchestration.ssh_gate import encode_gate_pending_line

    monkeypatch.setenv("DISCORD_OS_SSH_GATES", "bridge")
    host = RemoteHost(id="lab", kind="ssh", target="lab.example", label="lab")
    gate_root = tmp_path / "gates"
    backend = SshRemoteCookBackend(
        host=host, probe_first=False, gate_root=gate_root, timeout_seconds=5.0
    )

    payload = {
        "v": 1,
        "request_id": "req-cancel",
        "run_id": "r-cancel-bridge",
        "tool_name": "write_file",
        "tool_class": "write",
        "detail": "x",
        "kind": "tool_class",
        "question": "",
        "options": [],
        "allow_multiple": False,
        "created_at_ms": 1,
        "remote_gate_dir": "/tmp/discord-os-ssh-gate-r-cancel-bridge",
        "ssh_bridge": True,
    }

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
            self._closed.wait(timeout=3)
            return ""

    class _Child:
        def __init__(self) -> None:
            self.pid = 7777
            self.returncode = None
            self.stdout = _Pipe(
                [
                    "DISCORD_OS_REMOTE_PID=7777\n",
                    encode_gate_pending_line(payload) + "\n",
                ]
            )
            self.stderr = _Pipe([])

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            time.sleep(0.05)
            return self.returncode if self.returncode is not None else -9

        def terminate(self) -> None:
            self.returncode = -15
            self.stdout._closed.set()
            self.stderr._closed.set()

        def kill(self) -> None:
            self.terminate()

    writes: list[str] = []

    class _ExecProc:
        returncode = 0

    def _exec(argv, timeout_seconds=15.0):
        writes.append(" ".join(argv))
        return _ExecProc()

    run_dir = ensure_run_gate_dir(run_gate_dir(gate_root, "r-cancel-bridge"))
    backend.exec_fn = _exec
    backend.popen_fn = lambda argv, stdin_data=None: _Child()
    monkeypatch.setattr(backend, "_preflight_deny", lambda: None)
    monkeypatch.setattr(
        "agent_discord.host.remote_cook.ssh_remote_signal", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "agent_discord.host.remote_cook.ssh_controlmaster_exit", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "agent_discord.host.remote_cook.ensure_ssh_controlmaster_fresh",
        lambda *a, **k: True,
    )

    events: list = []
    done = threading.Event()

    def _cook() -> None:
        try:
            events.extend(backend.stream(
                DispatchRequest(
                    task_id="t1",
                    run_id="r-cancel-bridge",
                    prompt="implement",
                    model=AGENTIC_MODEL_PIN.canonical,
                    context=ContextSnapshot(
                        task_id="t1", memories=(), bindings={}, provenance={}
                    ),
                    metadata={"compute_mode": "implement"},
                )
            ))
        finally:
            done.set()

    thread = threading.Thread(target=_cook, daemon=True)
    thread.start()
    deadline = time.time() + 3
    while time.time() < deadline and "req-cancel" not in backend._bridge_pending:
        time.sleep(0.05)
    assert "req-cancel" in backend._bridge_pending
    # Phone Allow would race Cancel — Cancel must Deny instead.
    complete_request(
        run_dir,
        GateHoldResult(
            request_id="req-cancel",
            decision="allow",
            reason="too late",
            tool_class="write",
        ),
    )
    assert backend.cancel("r-cancel-bridge") is True
    assert done.wait(timeout=5)
    held = read_result(run_dir, "req-cancel")
    assert held is not None
    assert held.decision == "deny"
    # Flush after cancel must not push the prior Allow.
    assert backend.status("r-cancel-bridge") == TaskStatus.CANCELLED
    assert any(
        e.kind == EventKind.CANCEL_REQUESTED for e in events
    ) or backend.status("r-cancel-bridge") == TaskStatus.CANCELLED
