"""Host status: liveness Need line (P0.2) + read-only status digest (P2.7)."""

from __future__ import annotations

import os
from pathlib import Path

from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.dashboard import build_status_snapshot
from agent_discord.host.service import write_host_meta
from agent_discord.host.status import (
    DIGEST_MIN_CHECK_INTERVAL_S,
    DOCTOR_FAIL,
    DOCTOR_OK,
    GATEWAY_BAD,
    PID_DEAD,
    PID_OK,
    POWER_OFF,
    POWER_OK,
    TERMINAL_JOB_STATUSES,
    HostDigest,
    compute_host_digest,
    digest_signature,
    format_status_digest,
    host_need_line,
    last_digest_from_state,
    merge_host_need_jobs,
    notify_doctor_failure,
    post_status_on_power_on,
    should_announce,
    tick_host_liveness,
    tick_status_digest,
)
from agent_discord.orchestration.job_briefing import briefing_line
from agent_discord.persistence.sqlite import SQLiteStore


def _ws(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / ".agent-discord"
    ws.mkdir(parents=True)
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-should-not-leak")
    return ws


# --- liveness ---------------------------------------------------------------


def test_digest_and_need_line_on_doctor_fail(tmp_path: Path, monkeypatch) -> None:
    ws = _ws(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.set_host_control("chan-1", armed=True)
    write_host_meta(ws, pid=1, channel_id="chan-1")  # pid 1 may or may not be alive

    digest = compute_host_digest(
        workspace=ws,
        channel_id="chan-1",
        store=store,
        doctor_lines=["OK version 0.5.30", "FAIL host.pid stale pid=99999"],
        doctor_code=1,
    )
    assert digest.doctor == DOCTOR_FAIL
    assert digest.power == POWER_OK
    line = host_need_line(digest)
    assert line is not None
    assert line.startswith("Need: HOST")
    assert "doctor FAIL" in line
    assert "test-token" not in line
    store.close()


def test_merge_host_need_ranks_first() -> None:
    digest = HostDigest(
        power=POWER_OFF,
        pid=PID_DEAD,
        doctor=DOCTOR_FAIL,
        fail_summary="host.pid dead",
    )
    jobs = [
        {
            "task_id": "t1",
            "job_code": "DOS-10001",
            "status": "completed",
            "summary": "done work",
            "attention": "",
        }
    ]
    merged = merge_host_need_jobs(jobs, digest)
    assert len(merged) == 2
    assert merged[0]["task_id"] == "host-liveness"
    assert briefing_line(merged[0]).startswith("Need:")
    healthy = HostDigest(power=POWER_OK, pid=PID_OK, doctor=DOCTOR_OK)
    assert merge_host_need_jobs(jobs, healthy) == jobs


def test_tick_never_posts_doctor_digest(tmp_path: Path, monkeypatch) -> None:
    ws = _ws(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.set_host_control("chan-1", armed=True)
    write_host_meta(ws, pid=1, channel_id="chan-1")

    provider = FakeDiscordMCPProvider(persist_dir=ws / "fake_discord")
    discord = DiscordFacade(provider)

    body = tick_host_liveness(
        discord,
        workspace=ws,
        channel_id="chan-1",
        store=store,
        force=True,
        min_interval_s=0,
        doctor_lines=["FAIL gateway_owners stale"],
        doctor_code=1,
    )
    assert body is None
    assert provider.sent == []
    cached = last_digest_from_state(ws)
    assert cached is not None
    assert cached.doctor == DOCTOR_FAIL

    fail_posted = notify_doctor_failure(
        discord,
        workspace=ws,
        channel_id="chan-1",
        store=store,
        doctor_lines=["FAIL gateway_owners stale"],
        doctor_code=1,
    )
    assert fail_posted is None
    assert provider.sent == []
    store.close()


def test_notify_doctor_failure_skips_ok_spam(tmp_path: Path, monkeypatch) -> None:
    ws = _ws(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    write_host_meta(ws, pid=1, channel_id="chan-1")
    provider = FakeDiscordMCPProvider(persist_dir=ws / "fake_discord")
    discord = DiscordFacade(provider)
    posted = notify_doctor_failure(
        discord,
        workspace=ws,
        channel_id="chan-1",
        store=store,
        doctor_lines=["OK version x", "OK workspace writable"],
        doctor_code=0,
    )
    assert posted is None
    assert provider.sent == []
    store.close()


def test_cli_exposes_doctor_notify() -> None:
    from agent_discord.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["host", "doctor", "--notify"])
    assert args.notify is True


# --- status digest ----------------------------------------------------------


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
        env=dict(os.environ),
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
    assert "$0.05" in body
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


def test_status_never_exposes_power_mutators() -> None:
    import inspect

    import agent_discord.host.status as mod

    src = inspect.getsource(mod)
    assert "set_host_control" not in src
    assert "apply_panel_action" not in src


def test_digest_interval_floor_and_terminal_vocab() -> None:
    assert DIGEST_MIN_CHECK_INTERVAL_S >= 120.0
    assert "failed" in TERMINAL_JOB_STATUSES
    assert "error" in TERMINAL_JOB_STATUSES


def test_digest_signature_ignores_terminal_jobs() -> None:
    base = {
        "host": {"armed": False, "running": True, "pid": 1},
        "spend": {"spend_usd": 0.0, "spend_known": False, "cap_usd": 10.0, "halted": False},
        "hosts": [],
    }
    with_cancelled = {
        **base,
        "jobs": [
            {"job_code": "DOS-1", "status": "cancelled"},
            {"job_code": "DOS-2", "status": "cancelled"},
        ],
    }
    with_running = {
        **base,
        "jobs": [
            {"job_code": "DOS-1", "status": "cancelled"},
            {"job_code": "DOS-9", "status": "running"},
        ],
    }
    empty = {**base, "jobs": []}
    assert digest_signature(with_cancelled) == digest_signature(empty)
    assert "DOS-9:running" in digest_signature(with_running)
    assert "DOS-1:cancelled" not in digest_signature(with_running)


def test_digest_signature_ignores_failed_jobs() -> None:
    base = {
        "host": {"armed": False, "running": True, "pid": 1},
        "spend": {"spend_usd": 0.0, "spend_known": False, "cap_usd": 10.0, "halted": False},
        "hosts": [],
    }
    with_failed = {
        **base,
        "jobs": [
            {"job_code": "DOS-1", "status": "failed"},
            {"job_code": "DOS-2", "status": "error"},
        ],
    }
    empty = {**base, "jobs": []}
    assert digest_signature(with_failed) == digest_signature(empty)


def test_gateway_bad_digest_is_a_need_line() -> None:
    digest = HostDigest(
        power=POWER_OK,
        pid=PID_OK,
        doctor=DOCTOR_OK,
        gateway=GATEWAY_BAD,
    )
    assert digest.ok is False
    line = host_need_line(digest)
    assert line is not None
    assert "gateway BAD" in line
