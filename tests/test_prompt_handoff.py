"""P0.4 ARG_MAX stdin/file handoff for oversized agentic prompts."""

from __future__ import annotations

import errno
from pathlib import Path
from typing import Any

import pytest

from agent_discord.contracts import (
    ContextSnapshot,
    DispatchRequest,
    EventKind,
    TaskStatus,
)
from agent_discord.host.remote_cook import (
    SshRemoteCookBackend,
    build_remote_agentic_handoff,
    build_remote_agentic_argv,
)
from agent_discord.host.runners import RemoteHost, host_runner_argv
from agent_discord.puppetmaster.agentic import AgenticPuppetmasterBackend
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN
from agent_discord.puppetmaster.prompt_handoff import (
    AGENTIC_FILE_BRIDGE,
    estimate_argv_bytes,
    is_arg_max_oserror,
    needs_prompt_handoff,
    plan_local_agentic_handoff,
    plan_ssh_agentic_handoff,
    spoken_arg_max_denied,
)


def _req(prompt: str, **meta) -> DispatchRequest:
    return DispatchRequest(
        task_id="t1",
        run_id="r1",
        prompt=prompt,
        model=AGENTIC_MODEL_PIN.canonical,
        context=ContextSnapshot(task_id="t1", memories=(), bindings={}, provenance={}),
        metadata=meta or {"compute_mode": "analyze"},
    )


def test_estimate_and_budget_triggers_handoff() -> None:
    small = ["puppetmaster", "agentic", "hi", "--provider", "openrouter"]
    assert needs_prompt_handoff(small, budget=10_000) is False
    huge = ["puppetmaster", "agentic", "x" * 50_000, "--provider", "openrouter"]
    assert needs_prompt_handoff(huge, budget=10_000) is True
    assert estimate_argv_bytes(huge) > 50_000


def test_local_plan_small_keeps_prompt_on_argv() -> None:
    handoff = plan_local_agentic_handoff(
        cli="puppetmaster",
        prompt="hello world",
        flags=["--provider", "openrouter", "--model", "openrouter/auto"],
        budget=10_000,
    )
    assert handoff.mode == "argv"
    assert handoff.argv[0] == "puppetmaster"
    assert handoff.argv[1] == "agentic"
    assert handoff.argv[2] == "hello world"
    assert handoff.stdin_data is None
    assert handoff.prompt_file is None


def test_local_plan_oversized_uses_file_bridge(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_OS_ARGV_MAX", "8000")
    # Fake a puppetmaster console script so resolve_puppetmaster_python works.
    pm = tmp_path / "puppetmaster"
    py = tmp_path / "pm-python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    # Avoid literal triple-quote in this test file's source: build pipx exec line.
    exec_marker = "'" * 3 + "exec'"
    pm.write_text(
        "#!/bin/sh\n"
        + exec_marker
        + f" '{py}' \"$0\" \"$@\"\n"
        + "' '''\n",
        encoding="utf-8",
    )
    pm.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + ":" + __import__("os").environ.get("PATH", ""))

    big = "OVERSIZED-" + ("body" * 5000)
    handoff = plan_local_agentic_handoff(
        cli="puppetmaster",
        prompt=big,
        flags=["--provider", "openrouter", "--mode", "analyze"],
        budget=8000,
    )
    try:
        assert handoff.mode == "file"
        assert handoff.argv, "expected bridge argv"
        assert big not in " ".join(handoff.argv)
        assert "-c" in handoff.argv
        assert AGENTIC_FILE_BRIDGE in handoff.argv
        assert handoff.prompt_file is not None
        assert handoff.prompt_file.read_text(encoding="utf-8") == big
        assert needs_prompt_handoff(handoff.argv, budget=8000) is False
    finally:
        handoff.cleanup()


def test_ssh_plan_oversized_puts_prompt_on_stdin_not_argv() -> None:
    big = "REMOTE-" + ("payload" * 8000)
    handoff = plan_ssh_agentic_handoff(
        cli="puppetmaster",
        prompt=big,
        flags=["--provider", "openrouter", "--mode", "analyze"],
        remote_cwd="/tmp/work",
        budget=8000,
    )
    assert handoff.mode == "stdin"
    assert handoff.stdin_data == big
    assert handoff.argv[0] == "bash"
    joined = " ".join(handoff.argv)
    assert big not in joined
    assert "mktemp" in joined or "PROMPT_FILE" in joined
    # host_runner_argv must stay short too
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    wrapped = ["bash", "-lc", "echo DISCORD_OS_REMOTE_PID=$$; exec " + " ".join(
        __import__("shlex").quote(p) for p in handoff.argv
    )]
    # simpler: just the handoff argv through host_runner
    ssh_argv = host_runner_argv(host, handoff.argv)
    assert big not in " ".join(ssh_argv)
    assert needs_prompt_handoff(ssh_argv, budget=8000) is False


def test_build_remote_oversized_via_env(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_OS_ARGV_MAX", "6000")
    req = _req("Z" * 20_000, compute_mode="analyze", host_workdir="/tmp/w")
    handoff = build_remote_agentic_handoff(req)
    assert handoff.mode == "stdin"
    assert handoff.stdin_data and handoff.stdin_data.startswith("Z")
    argv = build_remote_agentic_argv(req)
    assert "Z" * 100 not in " ".join(argv)


def test_spoken_and_e2big() -> None:
    assert spoken_arg_max_denied().startswith("Denied.")
    assert "ARG_MAX" in spoken_arg_max_denied()
    err = OSError(errno.E2BIG, "Argument list too long")
    assert is_arg_max_oserror(err) is True
    assert is_arg_max_oserror(OSError("other")) is False


def test_agentic_backend_oversized_uses_file_not_prompt_argv(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DISCORD_OS_ARGV_MAX", "8000")
    pm = tmp_path / "puppetmaster"
    py = tmp_path / "pm-python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    exec_marker = "'" * 3 + "exec'"
    pm.write_text(
        "#!/bin/sh\n" + exec_marker + f" '{py}' \"$0\" \"$@\"\n' '''\n",
        encoding="utf-8",
    )
    pm.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + ":" + __import__("os").environ.get("PATH", ""))
    monkeypatch.setattr(
        "agent_discord.puppetmaster.agentic.shutil.which",
        lambda _: str(pm),
    )

    calls: list[dict[str, Any]] = []

    def fake_popen(cmd, **kwargs):
        calls.append({"cmd": list(cmd), "env": kwargs.get("env")})

        class Proc:
            returncode = 0

            def communicate(self, timeout=None):
                return ("job_id: j-big\nsummary: oversized ok\n", "")

        return Proc()

    monkeypatch.setattr(
        "agent_discord.puppetmaster.agentic.subprocess.Popen", fake_popen
    )

    big = "PROMPT-" + ("x" * 12_000)
    backend = AgenticPuppetmasterBackend(
        cli="puppetmaster",
        pin=AGENTIC_MODEL_PIN,
        cwd=tmp_path,
        env={},
    )
    result = backend.dispatch(_req(big, compute_mode="analyze"))
    assert result.status == TaskStatus.COMPLETED
    assert calls
    cmd = calls[0]["cmd"]
    assert big not in " ".join(cmd)
    assert "-c" in cmd
    assert AGENTIC_FILE_BRIDGE in cmd
    # Key never on argv
    assert "OPENROUTER" not in " ".join(cmd)


def test_ssh_backend_oversized_stdin_handoff(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_OS_ARGV_MAX", "6000")
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    seen: list[dict[str, Any]] = []

    class _Child:
        def __init__(self, argv, stdin_data=None):
            seen.append({"argv": list(argv), "stdin": stdin_data})
            self.pid = 1
            self.returncode = 0
            self.stdout = None
            self.stderr = None

        def communicate(self, timeout=None):
            import json

            return (json.dumps({"summary": "remote big ok"}) + "\n", "")

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    def _popen(argv, stdin_data=None):
        return _Child(argv, stdin_data=stdin_data)

    def _ok(argv, *, timeout_seconds=0):
        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    backend = SshRemoteCookBackend(
        host=host, exec_fn=_ok, popen_fn=_popen, probe_first=True
    )
    big = "SSHPROMPT-" + ("y" * 15_000)
    result = backend.dispatch(
        _req(big, compute_mode="analyze", host_id="lab", host_kind="ssh")
    )
    assert result.status == TaskStatus.COMPLETED
    assert seen
    # Safe dispatch may wrap the user prompt; body must ride stdin, not argv.
    assert seen[0]["stdin"] and big in seen[0]["stdin"]
    assert big not in " ".join(seen[0]["argv"])
    assert seen[0]["argv"][:3] == ["ssh", "-o", "BatchMode=yes"]
