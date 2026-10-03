"""Listen intake correctness: thread history, pagination, durable claims, seeding."""

from __future__ import annotations

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
