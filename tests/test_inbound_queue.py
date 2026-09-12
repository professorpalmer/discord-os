"""P0.3 durable inbound queue while a job is RUNNING."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import DiscordMessage, TaskIntake, TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.orchestration.jobs import JobPool
from agent_discord.orchestration.listen import drain_inbound
from agent_discord.persistence.sqlite import SQLiteStore


class _FakeSteerOrch:
    def __init__(self, store):
        self.store = store
        self.workspace = None
        self.steer_calls: list[tuple[str, str]] = []
        self.jobs: list[TaskIntake] = []
        self._live: dict[str, str] = {}
        self.steer_ok = True

    def running_run_for_thread(self, thread_id: str):
        return self._live.get((thread_id or "").strip())

    def steer(self, run_id: str, text: str) -> bool:
        if not self.steer_ok:
            raise RuntimeError("steer failed")
        self.steer_calls.append((run_id, text))
        return True

    def run_task(self, intake: TaskIntake):
        self.jobs.append(intake)
        from agent_discord.contracts import RunReceipt

        return RunReceipt(
            task_id=f"task-{len(self.jobs)}",
            run_id=f"run-{len(self.jobs)}",
            status=TaskStatus.COMPLETED,
            summary="ok",
        )


def _armed_store(tmp_path: Path, name: str = "q.sqlite3"):
    store = SQLiteStore(tmp_path / name)
    store.initialize()
    store.set_host_control("ch", armed=True)
    store.seed_owner_if_empty("human-1")
    return store


def test_store_enqueue_list_apply_dedupe(tmp_path: Path):
    store = SQLiteStore(tmp_path / "qstore.sqlite3")
    store.initialize()
    qid = store.enqueue_inbound(
        message_id="m1",
        channel_id="ch",
        thread_id="th",
        text="nudge left",
        run_id="r1",
        workspace_id="ws",
        author_id="human-1",
    )
    assert qid
    assert store.enqueue_inbound(
        message_id="m1",
        channel_id="ch",
        thread_id="th",
        text="nudge left",
    ) is None
    assert store.enqueue_inbound(
        message_id="m-empty",
        channel_id="ch",
        thread_id="",
        text="no thread",
    ) is None
    rows = store.list_queued_inbound("th")
    assert len(rows) == 1
    assert rows[0]["text"] == "nudge left"
    store.mark_inbound_applied(qid)
    assert store.list_queued_inbound("th") == []
    store.close()


def test_live_thread_steer_success_marks_queue_applied(tmp_path: Path):
    store = _armed_store(tmp_path)
    orch = _FakeSteerOrch(store)
    orch._live["job-thread"] = "run-1"
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="nudge it left",
            message_id="201",
            author_id="human-1",
            thread_id="job-thread",
        )
    )
    drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        job_pool=JobPool(),
    )
    assert orch.steer_calls == [("run-1", "nudge it left")]
    assert orch.jobs == []
    assert store.list_queued_inbound("job-thread") == []
    store.close()


def test_live_thread_steer_miss_queues_instead_of_drop(tmp_path: Path):
    store = _armed_store(tmp_path, "miss.sqlite3")
    orch = _FakeSteerOrch(store)
    orch._live["job-thread"] = "run-1"
    orch.steer_ok = False
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="keep this text",
            message_id="401",
            author_id="human-1",
            thread_id="job-thread",
        )
    )
    drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        job_pool=JobPool(),
    )
    assert orch.jobs == []
    queued = store.list_queued_inbound("job-thread")
    assert len(queued) == 1
    assert queued[0]["text"] == "keep this text"
    assert any("Queued" in (m.content or "") for m in fake.sent)
    store.close()


def test_queued_text_becomes_followup_when_cook_ends(tmp_path: Path):
    store = _armed_store(tmp_path, "flush.sqlite3")
    orch = _FakeSteerOrch(store)
    orch._live["job-thread"] = "run-1"
    orch.steer_ok = False
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="apply after cook",
            message_id="501",
            author_id="human-1",
            thread_id="job-thread",
        )
    )
    drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        job_pool=JobPool(),
    )
    assert store.list_queued_inbound("job-thread")
    orch._live.clear()
    orch.steer_ok = True
    drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        job_pool=JobPool(),
    )
    assert len(orch.jobs) == 1
    assert orch.jobs[0].text == "apply after cook"
    assert orch.jobs[0].thread_id == "job-thread"
    assert store.list_queued_inbound("job-thread") == []
    store.close()


def test_parent_channel_ask_is_not_stolen_onto_live_thread(tmp_path: Path):
    store = _armed_store(tmp_path, "parent.sqlite3")
    orch = _FakeSteerOrch(store)
    orch._live["job-thread"] = "run-1"
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="a brand new ask in the channel",
            message_id="601",
            author_id="human-1",
        )
    )
    pool = JobPool()
    drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        job_pool=pool,
    )
    pool.wait(timeout=2.0)
    assert orch.steer_calls == []
    assert len(orch.jobs) == 1
    assert orch.jobs[0].text == "a brand new ask in the channel"
    assert orch.jobs[0].thread_id is None
    assert store.list_queued_inbound() == []
    store.close()


def test_queue_disabled_falls_back_to_steer_miss(tmp_path: Path):
    store = _armed_store(tmp_path, "off.sqlite3")
    orch = _FakeSteerOrch(store)
    orch._live["job-thread"] = "run-1"
    orch.steer_ok = False
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="please steer",
            message_id="701",
            author_id="human-1",
            thread_id="job-thread",
        )
    )
    drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        job_pool=JobPool(),
        env={"DISCORD_OS_INBOUND_QUEUE": "0"},
    )
    assert orch.jobs == []
    assert store.list_queued_inbound("job-thread") == []
    assert any("Could not steer" in (m.content or "") for m in fake.sent)
    store.close()
