"""Capture-first intake: a thought is not a job. Fakes only."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import DiscordMessage
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.orchestration.capture import (
    CAPTURE_CHANNELS_ENV,
    CAPTURE_ENV,
    CAPTURE_REACTION,
    CAPTURE_SOURCE,
    capture_first_enabled,
    classify_intake,
    enable_capture_channel,
    record_capture,
)
from agent_discord.orchestration.listen import DISCORD_EPOCH_MS, drain_inbound
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend

CHANNEL = "ch-capture"
FIRST_MS = 1_750_000_000_000


def _snowflake_at(created_ms: int) -> str:
    return str((int(created_ms) - DISCORD_EPOCH_MS) << 22)


def _bookmarks(provider: FakeDiscordMCPProvider) -> list[dict[str, str]]:
    """Cooks leave their own progress reactions; only the bookmark is a capture."""

    return [row for row in provider.reactions if row["emoji"] == CAPTURE_REACTION]


def _store(tmp_path: Path) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "capture.sqlite3")
    store.initialize()
    return store


def _orch(tmp_path: Path, provider: FakeDiscordMCPProvider):
    store = _store(tmp_path)
    store.set_host_control(CHANNEL, armed=True)
    facade = DiscordFacade(provider, bot_token_fingerprint="fp", owner_id="test")
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        discord=facade,
        workspace=tmp_path,
    )
    return orch, store, facade


def _captures(store: SQLiteStore, query: str = "") -> list[dict]:
    return [
        dict(row)
        for row in store.recall(
            workspace_id="default", channel_id=CHANNEL, query=query, limit=16
        )
        if row["source"] == CAPTURE_SOURCE
    ]


# --- classifier table ---


def test_classifier_table_splits_thoughts_from_work():
    captures = [
        "PM routing should prefer X",
        "Freese FAQ still waits",
        "the morning card feels noisy on weekends",
        "capture-first is probably the right default eventually",
        "is the swarm tracker supposed to show degraded?",
    ]
    cooks = [
        "fix the morning card spacing",
        "do: PM routing should prefer X",
        "cook: Freese FAQ still waits",
        "please add a capture digest",
        "can you review the listen tick",
        "/ask what is the state of discord-os",
        "!status",
        "bind puppetmaster",
        "schedule every 1h: run tests",
        "connect openrouter",
        "/connect openrouter",
        "status of discord-os",
        "any open prs?",
        "repo status",
        (
            "Refactor the listen loop so the capture branch, the live-thread "
            "branch, and the schedule branch all read from one decision object "
            "instead of three separate predicates spread over the drain body."
        ),
    ]
    for text in captures:
        decision = classify_intake(text, capture_first=True)
        assert decision.capture, f"expected capture: {text!r} ({decision.reason})"
    for text in cooks:
        decision = classify_intake(text, capture_first=True)
        assert not decision.capture, f"expected cook: {text!r} ({decision.reason})"


def test_cook_prefix_strips_and_forces_a_cook():
    decision = classify_intake("do: PM routing should prefer X", capture_first=True)
    assert (decision.capture, decision.text) == (False, "PM routing should prefer X")
    decision = classify_intake("cook:  Freese FAQ still waits", capture_first=True)
    assert (decision.capture, decision.text) == (False, "Freese FAQ still waits")


def test_job_thread_reply_is_never_a_capture():
    decision = classify_intake(
        "that looks wrong", capture_first=True, in_job_thread=True
    )
    assert not decision.capture
    assert decision.reason == "job-thread"


def test_capture_first_off_by_default_classifies_everything_as_cook():
    decision = classify_intake("PM routing should prefer X", capture_first=False)
    assert not decision.capture
    assert decision.reason == "off"


def test_enable_is_env_global_env_channel_or_binding(tmp_path: Path):
    store = _store(tmp_path)
    assert not capture_first_enabled(store, CHANNEL, env={})
    assert capture_first_enabled(store, CHANNEL, env={CAPTURE_ENV: "1"})
    assert capture_first_enabled(
        store, CHANNEL, env={CAPTURE_CHANNELS_ENV: f"other,{CHANNEL}"}
    )
    assert not capture_first_enabled(store, CHANNEL, env={CAPTURE_CHANNELS_ENV: "other"})
    enable_capture_channel(store, workspace_id="default", channel_id=CHANNEL)
    assert capture_first_enabled(store, CHANNEL, env={})
    assert not capture_first_enabled(store, "elsewhere", env={})
    store.close()


# --- the capture itself ---


def test_capture_writes_redacted_memory_reacts_and_dispatches_nothing(tmp_path: Path):
    provider = FakeDiscordMCPProvider()
    orch, store, _facade = _orch(tmp_path, provider)
    enable_capture_channel(store, workspace_id="default", channel_id=CHANNEL)
    provider.inbox.append(
        DiscordMessage(
            channel_id=CHANNEL,
            content="PM routing should prefer X <thinking>secret</thinking>",
            message_id=_snowflake_at(FIRST_MS),
            author_id="human-1",
        )
    )
    receipts = drain_inbound(
        orch,
        orch.discord,
        channel_id=CHANNEL,
        workspace_id="default",
        guild_id="guild-1",
        since_ms=FIRST_MS - 10_000_000,
        env={},
    )
    assert list(receipts) == []
    assert provider.sent == []
    assert provider.reactions == [
        {
            "channel_id": CHANNEL,
            "message_id": _snowflake_at(FIRST_MS),
            "emoji": CAPTURE_REACTION,
        }
    ]
    rows = _captures(store, "PM routing")
    assert len(rows) == 1
    assert "secret" not in rows[0]["content"]
    assert rows[0]["content"].startswith("PM routing should prefer X")
    provenance = rows[0]["provenance"]
    assert provenance["author"] == "human-1"
    assert provenance["channel_id"] == CHANNEL
    assert provenance["citation"].startswith("https://discord.com/channels/guild-1/")
    store.close()


def test_short_thought_still_cooks_while_capture_first_is_off(tmp_path: Path):
    provider = FakeDiscordMCPProvider()
    orch, store, _facade = _orch(tmp_path, provider)
    provider.inbox.append(
        DiscordMessage(
            channel_id=CHANNEL,
            content="PM routing should prefer X",
            message_id=_snowflake_at(FIRST_MS),
            author_id="human-1",
        )
    )
    receipts = drain_inbound(
        orch,
        orch.discord,
        channel_id=CHANNEL,
        workspace_id="default",
        since_ms=FIRST_MS - 10_000_000,
        env={},
    )
    assert len(list(receipts)) == 1
    assert not _bookmarks(provider)
    assert _captures(store) == []
    store.close()


def test_do_prefix_cooks_the_stripped_text_on_a_capture_channel(tmp_path: Path):
    provider = FakeDiscordMCPProvider()
    orch, store, _facade = _orch(tmp_path, provider)
    enable_capture_channel(store, workspace_id="default", channel_id=CHANNEL)
    provider.inbox.append(
        DiscordMessage(
            channel_id=CHANNEL,
            content="do: PM routing should prefer X",
            message_id=_snowflake_at(FIRST_MS),
            author_id="human-1",
        )
    )
    receipts = list(
        drain_inbound(
            orch,
            orch.discord,
            channel_id=CHANNEL,
            workspace_id="default",
            since_ms=FIRST_MS - 10_000_000,
            env={},
        )
    )
    assert len(receipts) == 1
    assert not _bookmarks(provider)
    task = store.get_task(receipts[0].task_id)
    assert task["intake_text"] == "PM routing should prefer X"
    store.close()


def test_add_capture_arms_the_channel_and_writes_the_env(tmp_path: Path):
    from agent_discord.host.add import add_capture, list_added, read_dotenv

    store = _store(tmp_path)
    env_file = tmp_path / ".env"
    payload = add_capture(
        store,
        channel_id=CHANNEL,
        workspace_id="default",
        env_file=env_file,
    )
    assert payload["kind"] == "capture"
    assert read_dotenv(env_file)[CAPTURE_CHANNELS_ENV] == CHANNEL
    assert capture_first_enabled(store, CHANNEL, env={})
    listing = list_added(store, workspace_id="default", env_file=env_file)
    assert listing["capture"] == [CHANNEL]
    store.close()


def test_capture_is_recallable_as_context(tmp_path: Path):
    store = _store(tmp_path)
    record_capture(
        store,
        workspace_id="default",
        channel_id=CHANNEL,
        text="PM routing should prefer X",
        author_id="human-1",
        message_id="42",
        guild_id="guild-1",
    )
    hits = list(
        store.recall(
            workspace_id="default",
            channel_id=CHANNEL,
            query="PM routing",
            limit=8,
        )
    )
    assert [row["source"] for row in hits] == [CAPTURE_SOURCE]
    store.close()
