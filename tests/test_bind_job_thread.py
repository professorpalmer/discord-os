"""P0.2: channel-parent asks always bind a Discord job thread."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_discord.contracts import TaskIntake, TaskStatus
from agent_discord.discord.errors import ToolInvocationError
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.orchestration.job_briefing import briefing_prefix
from agent_discord.orchestration.jobs import JobPool, drop_origin_thread, note_origin_thread
from agent_discord.orchestration.orchestrator import (
    THREAD_BIND_FAIL_SPOKEN,
    THREAD_BIND_RATE_SPOKEN,
    AgentOrchestrator,
)
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def _orch(tmp_path: Path) -> tuple[AgentOrchestrator, SQLiteStore, FakeDiscordMCPProvider]:
    store = SQLiteStore(tmp_path / "bind.sqlite3")
    store.initialize()
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    backend = FakePuppetmasterBackend()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=facade,
        post_progress_to_discord=True,
    )
    return orch, store, fake


def test_channel_ask_binds_thread_on_user_message(tmp_path: Path):
    orch, store, fake = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="ship the fix",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-msg-1",
        )
    )
    assert receipt.status == TaskStatus.COMPLETED
    assert fake.threads
    thread_id = next(iter(fake.threads))
    assert fake.threads[thread_id]["message_id"] == "ask-msg-1"
    task = store.get_task(receipt.task_id)
    assert task is not None
    assert task["thread_id"] == thread_id
    assert any(getattr(m, "thread_id", None) == thread_id for m in fake.sent)
    store.close()


def test_host_ask_posts_starter_then_binds_thread(tmp_path: Path):
    orch, store, fake = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(text="HOST Ask: summarize inbox", channel_id="ch", workspace_id="ws")
    )
    assert receipt.status == TaskStatus.COMPLETED
    assert fake.threads
    thread_id = next(iter(fake.threads))
    starter_mid = fake.threads[thread_id]["message_id"]
    assert starter_mid
    # Starter lives in the parent channel (no thread_id on the starter itself).
    starters = [
        m
        for m in fake.sent
        if m.message_id == starter_mid and not getattr(m, "thread_id", None)
    ]
    assert starters
    assert "summarize inbox" in (starters[0].content or "")
    task = store.get_task(receipt.task_id)
    assert task is not None
    assert task["thread_id"] == thread_id
    assert store.list_session_thread_ids(limit=8) == (thread_id,)
    store.close()


def test_existing_thread_steer_does_not_nest(tmp_path: Path):
    orch, store, fake = _orch(tmp_path)
    before = dict(fake.threads)
    receipt = orch.run_task(
        TaskIntake(
            text="steer me",
            channel_id="ch",
            workspace_id="ws",
            message_id="follow-9",
            thread_id="existing-thread",
        )
    )
    assert receipt.status == TaskStatus.COMPLETED
    assert "existing-thread" not in fake.threads
    assert fake.threads == before or all(
        not str(k).startswith("thread-follow") for k in fake.threads
    )
    assert any(getattr(m, "thread_id", None) == "existing-thread" for m in fake.sent)
    task = store.get_task(receipt.task_id)
    assert task is not None
    assert task["thread_id"] == "existing-thread"
    store.close()


def test_thread_create_rate_limit_is_honest_need(tmp_path: Path):
    orch, store, fake = _orch(tmp_path)

    def boom(channel_id, message_id, name):
        raise ToolInvocationError("Discord REST HTTP 429")

    fake.start_thread_from_message = boom  # type: ignore[method-assign]
    receipt = orch.run_task(
        TaskIntake(
            text="please cook",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-429",
        )
    )
    assert receipt.status == TaskStatus.FAILED
    assert THREAD_BIND_RATE_SPOKEN in (receipt.summary or "")
    run = store.get_run(receipt.run_id)
    assert run is not None
    assert run["status"] == "failed"
    task = store.get_task(receipt.task_id)
    assert task is not None
    assert task["status"] == "failed"
    assert not (task.get("thread_id") or "").strip()
    assert briefing_prefix({"status": "failed"}) == "Need"
    store.close()


def test_thread_create_failure_speaks_need_without_retry_storm(tmp_path: Path):
    orch, store, fake = _orch(tmp_path)
    calls = {"n": 0}

    def boom(channel_id, message_id, name):
        calls["n"] += 1
        raise ToolInvocationError("Discord REST HTTP 500")

    fake.start_thread_from_message = boom  # type: ignore[method-assign]
    receipt = orch.run_task(
        TaskIntake(
            text="please cook",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-500",
        )
    )
    assert receipt.status == TaskStatus.FAILED
    assert THREAD_BIND_FAIL_SPOKEN in (receipt.summary or "")
    assert calls["n"] == 1  # no retry storm
    store.close()


def test_job_pool_live_thread_ids_include_origin_bind():
    pool = JobPool(max_live=2)
    note_origin_thread("origin-th")
    try:
        assert "origin-th" in pool.live_thread_ids()
        assert pool.is_thread_live("origin-th")
    finally:
        drop_origin_thread("origin-th")
