"""P0.3 parked write-gate approval timeout (auto-deny)."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskIntake, TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.orchestration.listen import drain_inbound
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.orchestration.service import (
    DEFAULT_APPROVAL_TIMEOUT_MINUTES,
    EXPIRED_WRITE_SPOKEN,
    approval_timeout_seconds,
    expire_parked_approvals,
    inbound_queue_enabled,
    set_write_gate,
)
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def _orch(tmp_path: Path):
    store = SQLiteStore(tmp_path / "gate.sqlite3")
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
    return orch, store, fake, backend


def test_approval_timeout_env_default_invalid_and_off():
    assert approval_timeout_seconds({}) == DEFAULT_APPROVAL_TIMEOUT_MINUTES * 60
    assert approval_timeout_seconds({"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": ""}) == 20 * 60
    assert approval_timeout_seconds({"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "junk"}) == 20 * 60
    assert approval_timeout_seconds({"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "0"}) == 0
    assert approval_timeout_seconds({"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "off"}) == 0
    assert approval_timeout_seconds({"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "15"}) == 15 * 60
    assert inbound_queue_enabled({}) is True
    assert inbound_queue_enabled({"DISCORD_OS_INBOUND_QUEUE": "0"}) is False
    assert inbound_queue_enabled({"DISCORD_OS_INBOUND_QUEUE": "off"}) is False


def test_stale_parked_write_expires_with_spoken(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    parked = orch.run_task(
        TaskIntake(
            text="implement the login timeout fix",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-expire",
        )
    )
    assert parked.status == TaskStatus.PENDING
    assert backend.dispatch_count == 0
    store.merge_task_metadata(parked.task_id, {"parked_at_ms": 1})
    expired = expire_parked_approvals(
        orch,
        now_ms=1 + 21 * 60 * 1000,
        env={"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "20"},
    )
    assert len(expired) == 1
    assert expired[0]["action"] == "expire"
    assert EXPIRED_WRITE_SPOKEN in expired[0]["summary"]
    run = store.get_run(parked.run_id)
    assert run["status"] == TaskStatus.FAILED.value
    assert EXPIRED_WRITE_SPOKEN in (run.get("summary") or "")
    assert backend.dispatch_count == 0
    store.close()


def test_fresh_parked_write_stays_pending(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    parked = orch.run_task(
        TaskIntake(
            text="implement the still-fresh gate",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-fresh",
        )
    )
    assert parked.status == TaskStatus.PENDING
    expired = expire_parked_approvals(
        orch,
        now_ms=int(store.task_metadata(parked.task_id)["parked_at_ms"]) + 60_000,
        env={"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "20"},
    )
    assert expired == []
    run = store.get_run(parked.run_id)
    assert run["status"] == TaskStatus.PENDING.value
    assert backend.dispatch_count == 0
    store.close()


def test_disabled_timeout_is_noop(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    parked = orch.run_task(
        TaskIntake(
            text="implement never-expire",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-off",
        )
    )
    store.merge_task_metadata(parked.task_id, {"parked_at_ms": 1})
    expired = expire_parked_approvals(
        orch,
        now_ms=10**12,
        env={"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "off"},
    )
    assert expired == []
    assert store.get_run(parked.run_id)["status"] == TaskStatus.PENDING.value
    store.close()


def test_drain_inbound_tick_expires_stale_parked(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    store.set_host_control("ch", armed=True)
    store.seed_owner_if_empty("human-1")
    set_write_gate(store, True)
    parked = orch.run_task(
        TaskIntake(
            text="implement drain expire",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-drain-expire",
        )
    )
    store.merge_task_metadata(parked.task_id, {"parked_at_ms": 1})
    drain_inbound(
        orch,
        orch.discord,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        env={"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "20"},
    )
    # drain uses wall clock; force the tick with an explicit now via expire
    expire_parked_approvals(
        orch,
        now_ms=1 + 21 * 60 * 1000,
        env={"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "20"},
    )
    run = store.get_run(parked.run_id)
    assert run["status"] == TaskStatus.FAILED.value
    assert EXPIRED_WRITE_SPOKEN in (run.get("summary") or "")
    assert backend.dispatch_count == 0
    store.close()


def test_unparsable_parked_at_fails_closed_expired(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    parked = orch.run_task(
        TaskIntake(
            text="implement ambiguous park time",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-ambig",
        )
    )
    store.merge_task_metadata(parked.task_id, {"parked_at_ms": "nope"})
    store._connection().execute(
        "UPDATE runs SET created_at='not-a-date' WHERE run_id=?",
        (parked.run_id,),
    )
    store._connection().commit()
    expired = expire_parked_approvals(
        orch,
        now_ms=1_000,
        env={"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "20"},
    )
    assert len(expired) == 1
    assert store.get_run(parked.run_id)["status"] == TaskStatus.FAILED.value
    store.close()
