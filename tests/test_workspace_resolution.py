"""Audit 2026-10-02 G2-4: workspace and .env never resolve against the CWD."""

from __future__ import annotations

from pathlib import Path

from agent_discord.config import (
    default_dotenv_path,
    default_workspace,
    load_config,
)
from agent_discord.host.doctor import preferred_live_workspace


def _fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AGENT_DISCORD_WORKSPACE", raising=False)
    return home


def test_default_workspace_prefers_the_live_layout(tmp_path: Path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    live = home / "discord-os" / ".agent-discord"
    live.mkdir(parents=True)
    assert default_workspace() == live
    assert default_workspace(home=home) == live


def test_default_workspace_falls_back_when_live_is_absent(tmp_path: Path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    assert default_workspace() == home / ".discord-os" / "workspace"


def test_default_dotenv_sits_beside_the_workspace(tmp_path: Path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    live = home / "discord-os" / ".agent-discord"
    live.mkdir(parents=True)
    assert default_dotenv_path(live) == home / "discord-os" / ".env"


def test_load_config_ignores_the_current_directory(tmp_path: Path, monkeypatch):
    """A checkout CWD must not become a second workspace or a second .env."""

    home = _fake_home(tmp_path, monkeypatch)
    live = home / "discord-os" / ".agent-discord"
    live.mkdir(parents=True)
    (home / "discord-os" / ".env").write_text(
        "DISCORD_BOT_TOKEN=live-token\n", encoding="utf-8"
    )
    checkout = tmp_path / "Projects" / "discord-os"
    (checkout / ".agent-discord").mkdir(parents=True)
    (checkout / ".env").write_text("DISCORD_BOT_TOKEN=checkout-token\n", encoding="utf-8")
    monkeypatch.chdir(checkout)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    cfg = load_config(env={})
    assert cfg.workspace == live.resolve()
    assert cfg.database_path == live.resolve() / "agent_discord.sqlite3"
    assert cfg.discord_bot_token == "live-token"


def test_load_config_reads_dotenv_beside_an_explicit_workspace(tmp_path: Path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    root = tmp_path / "elsewhere"
    ws = root / ".agent-discord"
    ws.mkdir(parents=True)
    (root / ".env").write_text("DISCORD_BOT_TOKEN=beside-token\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    cfg = load_config(env={}, workspace=ws)
    assert cfg.workspace == ws.resolve()
    assert cfg.discord_bot_token == "beside-token"


def test_env_var_workspace_still_wins(tmp_path: Path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / "discord-os" / ".agent-discord").mkdir(parents=True)
    chosen = tmp_path / "chosen"
    cfg = load_config(env={"AGENT_DISCORD_WORKSPACE": str(chosen)})
    assert cfg.workspace == chosen.resolve()


def test_explicit_dotenv_path_still_wins(tmp_path: Path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    (home / "discord-os" / ".agent-discord").mkdir(parents=True)
    (home / "discord-os" / ".env").write_text("DISCORD_BOT_TOKEN=live\n", encoding="utf-8")
    explicit = tmp_path / "explicit.env"
    explicit.write_text("DISCORD_BOT_TOKEN=explicit\n", encoding="utf-8")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    cfg = load_config(env={}, dotenv_path=explicit)
    assert cfg.discord_bot_token == "explicit"


def test_dotenv_may_still_name_the_workspace(tmp_path: Path, monkeypatch):
    _fake_home(tmp_path, monkeypatch)
    declared = tmp_path / "declared"
    env_file = tmp_path / "from-dotenv.env"
    env_file.write_text(f"AGENT_DISCORD_WORKSPACE={declared}\n", encoding="utf-8")
    cfg = load_config(env={}, dotenv_path=env_file)
    assert cfg.workspace == declared.resolve()


def test_doctor_preferred_workspace_tracks_the_config_default(tmp_path: Path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    assert preferred_live_workspace(home) is None
    live = home / "discord-os" / ".agent-discord"
    live.mkdir(parents=True)
    assert preferred_live_workspace(home) == live
    assert preferred_live_workspace(home) == default_workspace(home=home)
