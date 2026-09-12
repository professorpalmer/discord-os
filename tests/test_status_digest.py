"""P2.7 Discord RO status digest from dashboard data."""

from __future__ import annotations

from pathlib import Path

from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.dashboard import build_status_snapshot
from agent_discord.host.service import write_host_meta
from agent_discord.host.status_digest import (
    digest_signature,
    format_status_digest,
    post_status_on_power_on,
    should_announce,
    tick_status_digest,
)
from agent_discord.persistence.sqlite import SQLiteStore


def _ws(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / ".agent-discord"
    ws.mkdir(parents=True)
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-should-not-leak")
    return ws


def test_format_reuses_snapshot_fields_no_secrets(tmp_path: Path, monkeypatch) -> None:
    ws = _ws(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.set_host_control("chan-1", armed=True)
    store.create_task(
        task_id="t1",
        workspace_id="default",
        channel_id="chan-1",
        intake_text="password=supersecret",
    )
    store.create_run(run_id="r1", task_id="t1", model="fake", adapter_name="fake")
    write_host_meta(ws, pid=1, channel_id="chan-1")
    monkeypatch.setenv(
        "DISCORD_OS_HOSTS",
        '[{"id":"lab","label":"Lab","ssh":"cary@lab.local"}]',
    )
    snap = build_status_snapshot(
        workspace=ws,
        store=store,
        include_doctor=False,
        env=dict(**{k: v for k, v in __import__("os").environ.items()}),
    )
    body = format_status_digest(snap)
    assert "Discord OS status" in body
    assert "power on" in body
    assert "spend" in body
    assert "lab" in body
    assert "cary@lab.local" not in body
    assert "supersecret" not in body
    assert "test-token" not in body
    assert " · Discord OS" in body
    sig = digest_signature(snap)
    assert "p=on" in sig
    assert "lab" in sig
    store.close()


def test_should_announce_debounces() -> None:
    assert should_announce("a", "") is False  # first quiet
    assert should_announce("a", "a") is False
    assert should_announce("b", "a") is True
    assert should_announce("a", "a", force=True) is True


def test_tick_posts_on_change_not_repeat(tmp_path: Path, monkeypatch) -> None:
    ws = _ws(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.set_host_control("chan-1", armed=True)
    write_host_meta(ws, pid=1, channel_id="chan-1")
    provider = FakeDiscordMCPProvider(persist_dir=ws / "fake_discord")
    discord = DiscordFacade(provider)

    snap = {
        "readonly": True,
        "version": "0.5.35",
        "host": {"armed": True, "running": True, "pid": 1},
        "spend": {"spend_usd": 0.01, "cap_usd": 1.0, "halted": False},
        "jobs": [{"job_code": "DOS-1", "status": "running"}],
        "hosts": [{"id": "lab", "label": "Lab", "kind": "ssh"}],
    }
    # Seed baseline quietly
    first = tick_status_digest(
        discord,
        workspace=ws,
        channel_id="chan-1",
        store=store,
        force=False,
        min_interval_s=0,
        snapshot=snap,
    )
    assert first is None
    assert provider.sent == []

    # Change spend → post
    snap2 = dict(snap)
    snap2["spend"] = {"spend_usd": 0.05, "cap_usd": 1.0, "halted": False}
    body = tick_status_digest(
        discord,
        workspace=ws,
        channel_id="chan-1",
        store=store,
        force=False,
        min_interval_s=0,
        snapshot=snap2,
    )
    assert body is not None
    assert "0.0500" in body
    assert len(provider.sent) == 1

    # Same signature → no spam
    again = tick_status_digest(
        discord,
        workspace=ws,
        channel_id="chan-1",
        store=store,
        force=False,
        min_interval_s=0,
        snapshot=snap2,
    )
    assert again is None
    assert len(provider.sent) == 1
    store.close()


def test_force_on_and_status_posts(tmp_path: Path, monkeypatch) -> None:
    ws = _ws(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.set_host_control("chan-1", armed=True)
    write_host_meta(ws, pid=1, channel_id="chan-1")
    provider = FakeDiscordMCPProvider(persist_dir=ws / "fake_discord")
    discord = DiscordFacade(provider)
    body = post_status_on_power_on(
        discord,
        workspace=ws,
        channel_id="chan-1",
        store=store,
    )
    assert body is not None
    assert "Discord OS status" in body
    assert "power on" in body
    assert provider.sent
    store.close()


def test_readonly_fail_closed_skips_writable_payload(tmp_path: Path, monkeypatch) -> None:
    ws = _ws(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    provider = FakeDiscordMCPProvider(persist_dir=ws / "fake_discord")
    discord = DiscordFacade(provider)
    bad = {
        "readonly": False,
        "host": {"armed": True, "running": True},
        "spend": {"spend_usd": 0, "cap_usd": None, "halted": False},
        "jobs": [],
        "hosts": [],
    }
    assert (
        tick_status_digest(
            discord,
            workspace=ws,
            channel_id="chan-1",
            store=store,
            force=True,
            min_interval_s=0,
            snapshot=bad,
        )
        is None
    )
    assert provider.sent == []
    store.close()


def test_digest_never_exposes_power_mutators() -> None:
    import inspect

    import agent_discord.host.status_digest as mod

    src = inspect.getsource(mod)
    assert "set_host_control" not in src
    assert "apply_panel_action" not in src
