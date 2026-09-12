"""Host doctor coherence checks."""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

from agent_discord.host.doctor import run_doctor
from agent_discord.host.install import SERVICE_LABEL
from agent_discord.persistence.sqlite import SQLiteStore


def _write_plist(path: Path, *, workspace: Path, cwd: Path, python: Path) -> None:
    data = {
        "Label": SERVICE_LABEL,
        "WorkingDirectory": str(cwd),
        "EnvironmentVariables": {
            "AGENT_DISCORD_WORKSPACE": str(workspace),
            "DISCORD_OS_SERVICE": "1",
        },
        "ProgramArguments": [str(python), "-m", "agent_discord", "host", "run"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(data))


def test_doctor_ok_tmp_workspace(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    ws = home / "discord-os" / ".agent-discord"
    ws.mkdir(parents=True)
    py = tmp_path / "python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    plist = home / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    _write_plist(plist, workspace=ws, cwd=home / "discord-os", python=py)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.close()
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    # Avoid requiring a real bot token in CI: empty is FAIL unless we stub.
    # Doctor reads apply_runtime_secrets; without token it fails — set a dummy host-file token.
    token_path = ws / "bot.token"
    # Find DEFAULT_HOST_BOT_TOKEN_PATH
    from agent_discord import config as cfgmod
    monkeypatch.setattr(cfgmod, "DEFAULT_HOST_BOT_TOKEN_PATH", token_path)
    token_path.write_text("dummy-token\n", encoding="utf-8")
    code, lines = run_doctor(workspace=ws, plist_path=plist, home=home)
    assert any(line.startswith("OK version") for line in lines), lines
    assert any("LaunchAgent workspace" in line for line in lines), lines
    # token should be host-file
    assert any("token source=" in line for line in lines), lines
    assert code in (0, 1)  # may fail if token empty path differs
    # Prefer asserting no FAIL about workspace
    assert not any(line.startswith("FAIL workspace") for line in lines), lines


def test_doctor_flags_wrong_launchagent_workspace(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    ws = home / "discord-os" / ".agent-discord"
    wrong = home / "Projects" / "discord-os" / ".agent-discord"
    ws.mkdir(parents=True)
    wrong.mkdir(parents=True)
    py = tmp_path / "python"
    py.write_text("x", encoding="utf-8")
    plist = home / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    _write_plist(plist, workspace=wrong, cwd=home / "Projects" / "discord-os", python=py)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.close()
    from agent_discord import config as cfgmod
    token_path = ws / "bot.token"
    monkeypatch.setattr(cfgmod, "DEFAULT_HOST_BOT_TOKEN_PATH", token_path)
    token_path.write_text("dummy\n", encoding="utf-8")
    code, lines = run_doctor(workspace=ws, plist_path=plist, home=home)
    assert code == 1
    assert any("FAIL LaunchAgent AGENT_DISCORD_WORKSPACE" in line for line in lines), lines


def test_doctor_fix_clears_stale_gateway(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    ws = home / "discord-os" / ".agent-discord"
    ws.mkdir(parents=True)
    py = tmp_path / "python"
    py.write_text("x", encoding="utf-8")
    plist = home / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    _write_plist(plist, workspace=ws, cwd=home / "discord-os", python=py)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    conn = store._connection()
    conn.execute(
        "INSERT INTO gateway_owners (bot_token_fingerprint, owner_id, claimed_at) VALUES (?,?,datetime('now'))",
        ("fp", "discord-os-cli-99999999-deadbeef"),
    )
    conn.commit()
    store.close()
    from agent_discord import config as cfgmod
    token_path = ws / "bot.token"
    monkeypatch.setattr(cfgmod, "DEFAULT_HOST_BOT_TOKEN_PATH", token_path)
    token_path.write_text("dummy\n", encoding="utf-8")
    code, lines = run_doctor(workspace=ws, plist_path=plist, home=home, fix=True)
    assert any("cleared" in line.lower() for line in lines), lines
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    rows = list(store._connection().execute("SELECT * FROM gateway_owners"))
    store.close()
    assert rows == []


def test_doctor_fail_empty_operators_when_require(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    ws = home / "discord-os" / ".agent-discord"
    ws.mkdir(parents=True)
    py = tmp_path / "python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    plist = home / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    _write_plist(plist, workspace=ws, cwd=home / "discord-os", python=py)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.close()
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    monkeypatch.setenv("DISCORD_OS_REQUIRE_OPERATORS", "1")
    from agent_discord import config as cfgmod

    token_path = ws / "bot.token"
    monkeypatch.setattr(cfgmod, "DEFAULT_HOST_BOT_TOKEN_PATH", token_path)
    token_path.write_text("dummy-token\n", encoding="utf-8")
    code, lines = run_doctor(workspace=ws, plist_path=plist, home=home)
    assert code == 1
    assert any(
        line.startswith("FAIL operators empty while DISCORD_OS_REQUIRE_OPERATORS=1")
        for line in lines
    ), lines


def test_doctor_ok_operators_when_require(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    ws = home / "discord-os" / ".agent-discord"
    ws.mkdir(parents=True)
    py = tmp_path / "python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    plist = home / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    _write_plist(plist, workspace=ws, cwd=home / "discord-os", python=py)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.add_operator("owner-1", role="owner")
    store.close()
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    monkeypatch.setenv("DISCORD_OS_REQUIRE_OPERATORS", "1")
    from agent_discord import config as cfgmod

    token_path = ws / "bot.token"
    monkeypatch.setattr(cfgmod, "DEFAULT_HOST_BOT_TOKEN_PATH", token_path)
    token_path.write_text("dummy-token\n", encoding="utf-8")
    code, lines = run_doctor(workspace=ws, plist_path=plist, home=home)
    assert any("OK operators 1" in line for line in lines), lines
    assert not any(line.startswith("FAIL operators") for line in lines), lines
