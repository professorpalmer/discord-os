"""Listen intake correctness: thread history, pagination, durable claims, seeding."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Sequence

from agent_discord.contracts import DiscordMessage, TaskIntake
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.orchestration.cards import CARD_PREFIX
from agent_discord.orchestration.listen import (
    DISCORD_EPOCH_MS,
    drain_inbound,
    replay_pending_intakes,
)
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def _snowflake_at(created_ms: int) -> str:
    return str((int(created_ms) - DISCORD_EPOCH_MS) << 22)


class NewestFirstProvider(FakeDiscordMCPProvider):
    """Mirror Discord REST: one page, newest message first."""

    def read_messages(
        self,
        channel_id: str,
        *,
        limit: int = 20,
        thread_id: Optional[str] = None,
        after: Optional[str] = None,
    ) -> Sequence[DiscordMessage]:
        page = super().read_messages(
            channel_id, limit=limit, thread_id=thread_id, after=after
        )
        return list(reversed(list(page)))


def _orch(tmp_path: Path, provider: FakeDiscordMCPProvider):
    store = SQLiteStore(tmp_path / "listen.sqlite3")
    store.initialize()
    facade = DiscordFacade(provider, bot_token_fingerprint="fp", owner_id="test")
    backend = FakePuppetmasterBackend()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=facade,
        workspace=tmp_path,
    )
    return orch, store, facade, backend


# --- B3: thread history order and attribution ---


def test_thread_history_keeps_newest_lines_in_order_with_authors(tmp_path: Path):
    provider = NewestFirstProvider()
    now_ms = 1_750_000_000_000
    for index in range(8):
        provider.inbox.append(
            DiscordMessage(
                channel_id="ch",
                content=f"line-{index}",
                message_id=_snowflake_at(now_ms + index * 1_000),
                thread_id="th1",
                author_id="human-1",
                metadata={"author_name": f"op{index}"},
            )
        )
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content=f"{CARD_PREFIX} LIVE job cooking",
            message_id=_snowflake_at(now_ms + 9_000),
            thread_id="th1",
            author_id="bot-1",
            metadata={"author_bot": True},
        )
    )
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="Queued. Will apply when this cook can take it.",
            message_id=_snowflake_at(now_ms + 10_000),
            thread_id="th1",
            author_id="bot-1",
            metadata={"author_bot": True},
        )
    )
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="now do the thing",
            message_id=_snowflake_at(now_ms + 11_000),
            thread_id="th1",
            author_id="human-1",
            metadata={"author_name": "cary"},
        )
    )
    orch, store, facade, backend = _orch(tmp_path, provider)
    receipts = drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        thread_id="th1",
        since_ms=0,
    )
    assert receipts
    prompt = backend.last_request.prompt
    block = prompt.split("Conversation context", 1)[1]
    lines = [line for line in block.splitlines() if ": " in line]
    assert lines[-1] == "cary: now do the thing"
    # Newest-first transport must not cost us the two newest lines.
    assert "Discord OS: Queued. Will apply when this cook can take it." in lines
    # Host card is harness chrome, never conversation context.
    assert all(CARD_PREFIX not in line for line in lines)
    # Oldest-first within the kept window, newest six only.
    assert len(lines) == 6
    texts = [line.split(": ", 1)[1] for line in lines]
    assert texts[:4] == ["line-4", "line-5", "line-6", "line-7"]
    assert lines[0] == "op4: line-4"
    assert "line-0" not in prompt
    store.close()


# --- B4: paginate the backlog instead of reading one page ---


def test_burst_larger_than_one_page_is_not_lost(tmp_path: Path):
    provider = NewestFirstProvider()
    now_ms = 1_750_000_000_000
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="first ask",
            message_id=_snowflake_at(now_ms),
            author_id="human-1",
        )
    )
    orch, store, facade, _backend = _orch(tmp_path, provider)
    first = drain_inbound(
        orch, facade, channel_id="ch", workspace_id="ws", limit=5, since_ms=0
    )
    assert len(first) == 1
    for index in range(25):
        provider.inbox.append(
            DiscordMessage(
                channel_id="ch",
                content=f"burst ask {index}",
                message_id=_snowflake_at(now_ms + 10_000 + index),
                author_id="human-1",
            )
        )
    receipts = drain_inbound(
        orch, facade, channel_id="ch", workspace_id="ws", limit=5, since_ms=0
    )
    summaries = " ".join(r.summary or "" for r in receipts)
    assert len(receipts) == 25
    assert "burst ask 0" in summaries
    assert "burst ask 24" in summaries
    store.close()


def test_pagination_stops_and_keeps_watermark_semantics(tmp_path: Path):
    provider = NewestFirstProvider()
    now_ms = 1_750_000_000_000
    reads: list[dict] = []
    inner = provider.read_messages

    def recording(channel_id, **kwargs):
        reads.append(dict(kwargs))
        return inner(channel_id, **kwargs)

    provider.read_messages = recording  # type: ignore[assignment]
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="only ask",
            message_id=_snowflake_at(now_ms),
            author_id="human-1",
        )
    )
    orch, store, facade, _backend = _orch(tmp_path, provider)
    assert len(drain_inbound(
        orch, facade, channel_id="ch", workspace_id="ws", limit=5, since_ms=0
    )) == 1
    reads.clear()
    # Nothing new: one anchored page, no loop, no re-dispatch.
    assert drain_inbound(
        orch, facade, channel_id="ch", workspace_id="ws", limit=5, since_ms=0
    ) == []
    anchored = [r for r in reads if r.get("after")]
    assert len(anchored) == 1
    assert anchored[0]["after"] == _snowflake_at(now_ms)
    watermark = store.get_listen_watermark("ch")
    assert watermark["last_message_id"] == _snowflake_at(now_ms)
    store.close()


# --- B7: a claimed ask survives a crash before its task row ---


class LostJobPool:
    """Accepts submits and never runs them, like a process killed mid-queue."""

    def __init__(self) -> None:
        self.submitted: list[TaskIntake] = []

    def submit(self, runner, intake, *, write_key: str = "") -> str:
        self.submitted.append(intake)
        return f"job-{len(self.submitted)}"


def test_claimed_ask_is_replayed_after_a_restart(tmp_path: Path):
    provider = FakeDiscordMCPProvider()
    now_ms = 1_750_000_000_000
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="ship the thing",
            message_id=_snowflake_at(now_ms),
            author_id="human-1",
        )
    )
    orch, store, facade, backend = _orch(tmp_path, provider)
    pool = LostJobPool()
    assert drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        job_pool=pool,
    ) == []
    assert len(pool.submitted) == 1
    # Claimed, so a second poll will never offer it again.
    assert store.get_inbound_message(_snowflake_at(now_ms)) is not None
    assert drain_inbound(
        orch, facade, channel_id="ch", workspace_id="ws", since_ms=0, job_pool=pool
    ) == []
    assert len(pool.submitted) == 1
    pending = store.list_pending_intake()
    assert [row["text"] for row in pending] == ["ship the thing"]

    receipts = replay_pending_intakes(orch)
    assert len(receipts) == 1
    assert "ship the thing" in (receipts[0].summary or "")
    assert store.list_pending_intake() == []
    store.close()


def test_pending_intake_clears_once_the_task_row_exists(tmp_path: Path):
    provider = FakeDiscordMCPProvider()
    now_ms = 1_750_000_000_000
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="run the tests",
            message_id=_snowflake_at(now_ms),
            author_id="human-1",
        )
    )
    orch, store, facade, _backend = _orch(tmp_path, provider)
    receipts = drain_inbound(
        orch, facade, channel_id="ch", workspace_id="ws", since_ms=0
    )
    assert len(receipts) == 1
    assert store.list_pending_intake() == []
    assert replay_pending_intakes(orch) == []
    store.close()


def test_poisoned_pending_intake_stops_replaying(tmp_path: Path):
    provider = FakeDiscordMCPProvider()
    orch, store, _facade, _backend = _orch(tmp_path, provider)
    store.record_pending_intake(
        message_id="m-poison",
        channel_id="ch",
        text="boom",
        workspace_id="ws",
    )

    def explode(_intake):
        raise RuntimeError("worker refuses")

    orch.run_task = explode  # type: ignore[assignment]
    for _attempt in range(3):
        assert replay_pending_intakes(orch) == []
    assert store.list_pending_intake() != []
    assert replay_pending_intakes(orch) == []
    assert store.list_pending_intake() == []
    store.close()


# --- B10: schedules and whisper leave the listen thread ---


class RecordingJobPool(LostJobPool):
    """Runs submits inline, but records the write key the pool would hold."""

    def __init__(self) -> None:
        super().__init__()
        self.write_keys: list[str] = []

    def submit(self, runner, intake, *, write_key: str = "") -> str:
        self.submitted.append(intake)
        self.write_keys.append(write_key)
        runner(intake)
        return f"job-{len(self.submitted)}"


def test_due_schedule_goes_through_the_job_pool(tmp_path: Path):
    provider = FakeDiscordMCPProvider()
    orch, store, facade, _backend = _orch(tmp_path, provider)
    store.set_host_control("ch", armed=True)
    store.add_schedule(
        channel_id="ch",
        workspace_id="ws",
        prompt="nightly audit",
        every_s=3600,
        created_by="",
        next_ms=1,
    )
    pool = RecordingJobPool()
    receipts = drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        job_pool=pool,
    )
    # Submitted, not cooked inline on the listen thread.
    assert receipts == []
    assert [i.text for i in pool.submitted] == ["nightly audit"]
    assert pool.submitted[0].metadata.get("scheduled") is True
    assert pool.write_keys[0]
    store.close()


def test_voice_transcription_does_not_block_the_drain(tmp_path: Path, monkeypatch):
    from agent_discord.contracts import DiscordAttachment
    from agent_discord.discord import voice as voice_mod
    from agent_discord.orchestration import listen as listen_mod

    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()

    def slow_transcribe(message, discord=None):
        started.set()
        release.wait(timeout=10)
        finished.set()
        return "run the tests"

    monkeypatch.setattr(voice_mod, "materialize_voice_intake", slow_transcribe)
    provider = FakeDiscordMCPProvider()
    now_ms = 1_750_000_000_000
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="",
            message_id=_snowflake_at(now_ms),
            author_id="human-1",
            attachments=(
                DiscordAttachment(
                    attachment_id="att-1",
                    filename="voice-message.ogg",
                    size=10,
                    content_type="audio/ogg",
                ),
            ),
        )
    )
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="also do this",
            message_id=_snowflake_at(now_ms + 1_000),
            author_id="human-1",
        )
    )
    orch, store, facade, _backend = _orch(tmp_path, provider)
    store.set_host_control("ch", armed=True)
    pool = RecordingJobPool()
    drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        job_pool=pool,
    )
    # The drain returned while whisper is still running, and the text message
    # behind the memo was dispatched instead of waiting a minute for it.
    assert started.wait(timeout=10)
    assert not finished.is_set()
    assert [i.text for i in pool.submitted] == ["also do this"]
    release.set()
    listen_mod.join_voice_workers(timeout=10)
    # The transcript is routed by the next drain, like typed text.
    assert "run the tests" not in [i.text for i in pool.submitted]
    drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=0, job_pool=pool)
    assert [i.text for i in pool.submitted].count("run the tests") == 1
    # Replayed once, never twice.
    drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=0, job_pool=pool)
    assert [i.text for i in pool.submitted].count("run the tests") == 1
    store.close()


def _voice_memo(now_ms: int):
    from agent_discord.contracts import DiscordAttachment

    return DiscordMessage(
        channel_id="ch",
        content="",
        message_id=_snowflake_at(now_ms),
        author_id="human-1",
        attachments=(
            DiscordAttachment(
                attachment_id="att-1",
                filename="voice-message.ogg",
                size=10,
                content_type="audio/ogg",
            ),
        ),
    )


def _drain_spoken(tmp_path: Path, monkeypatch, spoken: str, *, capture: bool = False):
    from agent_discord.discord import voice as voice_mod
    from agent_discord.orchestration import listen as listen_mod

    monkeypatch.setattr(voice_mod, "materialize_voice_intake", lambda m, d=None: spoken)
    provider = FakeDiscordMCPProvider()
    provider.inbox.append(_voice_memo(1_750_000_000_000))
    orch, store, facade, _backend = _orch(tmp_path, provider)
    store.set_host_control("ch", armed=True)
    if capture:
        from agent_discord.host.features import set_feature

        set_feature(store, "capture", True, channel_id="ch", workspace_id="ws")
    pool = RecordingJobPool()
    for _ in range(2):
        drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=0, job_pool=pool)
        listen_mod.join_voice_workers(timeout=10)
    return store, pool


def test_spoken_schedule_becomes_a_schedule_not_an_ask(tmp_path: Path, monkeypatch):
    store, pool = _drain_spoken(tmp_path, monkeypatch, "schedule every 1h: run tests")
    assert pool.submitted == []
    schedules = store.list_schedules("ch")
    assert [row["prompt"] for row in schedules] == ["run tests"]
    store.close()


def test_spoken_thought_in_a_capture_channel_is_captured(tmp_path: Path, monkeypatch):
    store, pool = _drain_spoken(
        tmp_path, monkeypatch, "PM routing should prefer the cheap lane", capture=True
    )
    assert pool.submitted == []
    store.close()


# --- B11: seed a destination when it is first polled ---


def test_listen_cli_seeds_at_poll_time_not_process_start(
    tmp_path: Path, monkeypatch, capsys
):
    from agent_discord import cli as cli_mod

    monkeypatch.chdir(tmp_path)
    ws = tmp_path / ".agent-discord"
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("PUPPETMASTER_MODEL", "openrouter/auto")
    seen: list[object] = []
    real = cli_mod.drain_inbound

    def spy(*args, **kwargs):
        seen.append(kwargs.get("since_ms", "missing"))
        return real(*args, **kwargs)

    monkeypatch.setattr(cli_mod, "drain_inbound", spy)
    assert cli_mod.main(["listen", "--channel-id", "99", "--fake", "--once"]) == 0
    capsys.readouterr()
    # A process-start constant would replay everything since boot in a thread
    # discovered hours later; None makes drain_inbound seed at poll time.
    assert seen
    assert all(value is None for value in seen)


def test_late_destination_seeds_at_its_own_first_poll(tmp_path: Path, monkeypatch):
    from agent_discord.orchestration import listen as listen_mod

    provider = FakeDiscordMCPProvider()
    boot_ms = 1_750_000_000_000
    late_ms = boot_ms + 4 * 3_600_000
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch-early",
            content="first ask",
            message_id=_snowflake_at(boot_ms + 1_000),
            author_id="human-1",
        )
    )
    provider.inbox.append(
        DiscordMessage(
            channel_id="ch-late",
            content="chatter from an hour ago",
            message_id=_snowflake_at(boot_ms + 3_600_000),
            author_id="human-1",
        )
    )
    orch, store, facade, _backend = _orch(tmp_path, provider)
    monkeypatch.setattr(listen_mod, "default_listen_since_ms", lambda: boot_ms)
    assert len(
        drain_inbound(orch, facade, channel_id="ch-early", workspace_id="ws")
    ) == 1
    monkeypatch.setattr(listen_mod, "default_listen_since_ms", lambda: late_ms)
    assert drain_inbound(orch, facade, channel_id="ch-late", workspace_id="ws") == []
    assert store.get_listen_watermark("ch-late")["last_created_ms"] == late_ms
    store.close()
