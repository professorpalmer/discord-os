"""P0.2 phone-visible host liveness / status Need."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.discord.facade import DiscordFacade
from agent_discord.host.liveness import (
    DOCTOR_FAIL,
    DOCTOR_OK,
    GATEWAY_BAD,
    PID_DEAD,
    PID_OK,
    POWER_OFF,
    POWER_OK,
    HostDigest,
    compute_host_digest,
    digest_spoken_message,
    host_need_line,
    last_digest_from_state,
    merge_host_need_jobs,
    notify_doctor_failure,
    should_announce,
    tick_host_liveness,
)
from agent_discord.host.service import write_host_meta
from agent_discord.orchestration.job_briefing import briefing_line
from agent_discord.persistence.sqlite import SQLiteStore


def _ws(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / ".agent-discord"
    ws.mkdir(parents=True)
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-should-not-leak")
    return ws


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
    spoken = digest_spoken_message(digest)
    assert "Discord OS host" in spoken
    assert "doctor FAIL" in spoken
    assert "test-token" not in spoken
    assert " · Discord OS" in spoken
    store.close()


def test_should_announce_never_posts() -> None:
    ok = HostDigest(power=POWER_OK, pid=PID_OK, doctor=DOCTOR_OK)
    fail = HostDigest(
        power=POWER_OK,
        pid=PID_DEAD,
        doctor=DOCTOR_FAIL,
        fail_summary="host.pid dead",
        gateway=GATEWAY_BAD,
    )
    assert should_announce(ok, "") is False
    assert should_announce(fail, "", force=True) is False
    assert should_announce(fail, "", gateway_bad_streak=99) is False
    assert should_announce(ok, fail.signature, gateway_bad_posted=True) is False


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
