"""Local agentic workers run inside an OS sandbox and a Discord OS model registry."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_discord.contracts import ContextSnapshot, DispatchRequest, TaskStatus
from agent_discord.keys.vault import KeyVault
from agent_discord.puppetmaster import sandbox as sandbox_mod
from agent_discord.puppetmaster.agentic import AgenticPuppetmasterBackend
from agent_discord.puppetmaster.backend import ensure_worker_registry
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN
from agent_discord.puppetmaster.sandbox import (
    SANDBOX_EXEC,
    build_profile,
    sandbox_available,
    worker_profile,
    wrap_argv,
)


def _request() -> DispatchRequest:
    return DispatchRequest(
        task_id="t1",
        run_id="r1",
        prompt="hello world",
        model=AGENTIC_MODEL_PIN.canonical,
        context=ContextSnapshot(task_id="t1", memories=[], bindings={}),
        metadata={"channel_id": "99"},
    )


def _dispatch(monkeypatch, tmp_path: Path, env: dict[str, str]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []

    def fake_popen(cmd, **kwargs):
        calls.append({"cmd": list(cmd), "env": kwargs.get("env")})

        class Proc:
            returncode = 0

            def communicate(self, timeout=None):
                return ("job_id: j9\nsummary: done\n", "")

        return Proc()

    monkeypatch.setattr(
        "agent_discord.puppetmaster.agentic.shutil.which", lambda _: "/usr/bin/puppetmaster"
    )
    monkeypatch.setattr("agent_discord.puppetmaster.agentic.subprocess.Popen", fake_popen)
    monkeypatch.setattr(sandbox_mod, "sandbox_available", lambda: True)
    vault = KeyVault(tmp_path / "keys")
    vault.put("openrouter", "sk-or-v1-" + "a" * 40, "env")
    checkout = tmp_path / "repo"
    (checkout / ".git").mkdir(parents=True)
    backend = AgenticPuppetmasterBackend(
        cli="puppetmaster",
        pin=AGENTIC_MODEL_PIN,
        cwd=checkout,
        vault=vault,
        env={"AGENT_DISCORD_WORKSPACE": str(tmp_path / "ws"), **env},
    )
    result = backend.dispatch(_request())
    assert result.status == TaskStatus.COMPLETED
    return calls[0]


def test_worker_spawn_is_wrapped_in_the_sandbox(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DISCORD_OS_SANDBOX")
    call = _dispatch(monkeypatch, tmp_path, {})
    cmd = call["cmd"]
    assert cmd[:2] == [SANDBOX_EXEC, "-p"]
    assert cmd[3] == "puppetmaster" and cmd[4] == "agentic"
    profile = cmd[2]
    ws = str((tmp_path / "ws").resolve())
    assert f'(subpath "{ws}")' in profile
    assert "(deny file-read-data file-write*" in profile
    assert str((tmp_path / "repo").resolve()) in profile
    # The state dir is made by the host: the worker cannot create it.
    assert Path(call["env"]["PUPPETMASTER_STATE_DIR"]).is_dir()


def test_sandbox_off_switch_reaches_the_spawn(monkeypatch, tmp_path: Path) -> None:
    call = _dispatch(monkeypatch, tmp_path, {"DISCORD_OS_SANDBOX": "0"})
    assert call["cmd"][0] == "puppetmaster"


def test_worker_gets_a_discord_os_registry_for_its_pin(monkeypatch, tmp_path: Path) -> None:
    call = _dispatch(monkeypatch, tmp_path, {})
    path = Path(call["env"]["PUPPETMASTER_MODELS_PATH"])
    assert path.parent == Path(call["env"]["PUPPETMASTER_STATE_DIR"])
    data = json.loads(path.read_text(encoding="utf-8"))
    (entry,) = data["models"]
    name = AGENTIC_MODEL_PIN.adapter_name or AGENTIC_MODEL_PIN.canonical
    assert data["schema_version"] == 1
    assert entry["id"] == f"agentic/{name}"
    assert entry["adapter"] == "agentic" and entry["enabled"] is True


def test_operator_registry_wins(monkeypatch, tmp_path: Path) -> None:
    mine = str(tmp_path / "operator-models.json")
    call = _dispatch(monkeypatch, tmp_path, {"PUPPETMASTER_MODELS_PATH": mine})
    assert call["env"]["PUPPETMASTER_MODELS_PATH"] == mine


def test_registry_write_is_idempotent(tmp_path: Path) -> None:
    first = ensure_worker_registry(tmp_path / "pm", "openrouter/auto")
    stamp = Path(first).stat().st_mtime_ns
    assert ensure_worker_registry(tmp_path / "pm", "openrouter/auto") == first
    assert Path(first).stat().st_mtime_ns == stamp
    ensure_worker_registry(tmp_path / "pm", "deepseek/deepseek-v4-flash")
    assert "deepseek" in Path(first).read_text(encoding="utf-8")


def test_profile_quotes_paths_and_orders_rules() -> None:
    profile = build_profile(
        write_roots=['/tmp/a "b'],
        deny_read=["/secret"],
        allow_back=["/secret/ok"],
        read_only_within=["/tmp/a/.git/hooks"],
    )
    assert '\\"b' in profile
    order = [
        profile.index("(deny file-write*)"),
        profile.index("(deny file-read-data"),
        profile.index("(allow file-read* file-read-data"),
        profile.rindex("(deny file-write*"),
    ]
    assert order == sorted(order)


@pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")
def test_real_sandbox_hides_secrets_and_confines_writes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    secrets = home / ".ssh"
    secrets.mkdir(parents=True)
    (secrets / "id_test").write_text("SECRET", encoding="utf-8")
    ws = tmp_path / "ws"
    (ws / "puppetmaster").mkdir(parents=True)
    (ws / "canary.txt").write_text("CANARY", encoding="utf-8")
    checkout = tmp_path / "repo"
    (checkout / ".git" / "hooks").mkdir(parents=True)
    # Temp is a write root, so the outside probe lives in the real home.
    import shutil
    import uuid

    outside = Path.home() / f".discord-os-sandbox-test-{uuid.uuid4().hex[:8]}"
    outside.mkdir()
    profile = worker_profile(
        workdir=checkout,
        child_env={"PUPPETMASTER_STATE_DIR": str(ws / "puppetmaster")},
        runtime_dirs=[ws],
        home=home,
    )

    def sh(cmd: str) -> int:
        return subprocess.run(
            wrap_argv(["/bin/sh", "-c", cmd], profile), cwd=checkout, capture_output=True
        ).returncode

    try:
        assert sh(f"cat {secrets}/id_test") != 0
        assert sh(f"cat {ws}/canary.txt") != 0
        assert sh(f"ls {ws}") != 0
        assert sh(f"echo x > {outside}/f") != 0
        assert sh("echo x > .git/hooks/pre-commit") != 0
        assert sh("echo x > f.txt && cat f.txt") == 0
        assert sh(f"echo x > {ws}/puppetmaster/s && cat {ws}/puppetmaster/s") == 0
        assert not (outside / "f").exists()
        assert not (checkout / ".git" / "hooks" / "pre-commit").exists()
    finally:
        shutil.rmtree(outside, ignore_errors=True)
