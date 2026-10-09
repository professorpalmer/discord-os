"""Weekly capture digest: one card a week, silent when empty. Fakes only."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.panel import handle_gateway_interaction
from agent_discord.orchestration.capture import record_capture
from agent_discord.orchestration.capture_digest import (
    DIGEST_DAYS,
    capture_digest_card,
    digest_day,
    digest_due,
    tick_capture_digest,
    week_captures,
)
from agent_discord.orchestration.cook_button import cook_custom_id, cook_token
from agent_discord.persistence.sqlite import SQLiteStore

CHANNEL = "ch-capture"
HOST = "host-ch"


def _store(tmp_path: Path) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "digest.sqlite3")
    store.initialize()
    return store


def _digest_clock() -> tuple[dict[str, str], datetime]:
    """Env + ``now`` that land on the digest day at the morning hour, today.

    A capture's ``created_at`` is real wall time, so the digest window has to
    be anchored to the real date instead of a frozen calendar.
    """

    real = datetime.now()
    env = {"DISCORD_OS_CAPTURE_DIGEST_DAY": DIGEST_DAYS[real.weekday()]}
    return env, real.replace(hour=9, minute=0, second=0, microsecond=0)


def test_digest_day_defaults_to_monday_and_parses_names():
    assert digest_day(env={}) == 0
    assert digest_day(env={"DISCORD_OS_CAPTURE_DIGEST_DAY": "friday"}) == 4
    assert digest_day(env={"DISCORD_OS_CAPTURE_DIGEST_DAY": "sun"}) == 6
    assert digest_day(env={"DISCORD_OS_CAPTURE_DIGEST_DAY": "nonsense"}) == 0


def test_digest_is_silent_when_there_were_no_captures(tmp_path: Path):
    provider = FakeDiscordMCPProvider()
    store = _store(tmp_path)
    facade = DiscordFacade(provider, bot_token_fingerprint="fp", owner_id="test")
    env, now = _digest_clock()
    quiet = tick_capture_digest(
        store, facade, channel_id=HOST, workspace_id="default", env=env, now=now
    )
    assert quiet == {"posted": False, "due": True, "lines": 0}
    assert provider.sent == []
    store.close()


def test_digest_posts_one_card_per_week(tmp_path: Path):
    provider = FakeDiscordMCPProvider()
    store = _store(tmp_path)
    facade = DiscordFacade(provider, bot_token_fingerprint="fp", owner_id="test")
    env, now = _digest_clock()
    record_capture(
        store,
        workspace_id="default",
        channel_id=CHANNEL,
        text="PM routing should prefer X",
        author_id="human-1",
        message_id="42",
        guild_id="guild-1",
    )
    posted = tick_capture_digest(
        store, facade, channel_id=HOST, workspace_id="default", env=env, now=now
    )
    assert posted["posted"] and posted["lines"] == 1
    assert len(provider.sent) == 1
    for later in (now.replace(hour=11), now + timedelta(days=1)):
        assert tick_capture_digest(
            store, facade, channel_id=HOST, workspace_id="default", env=env, now=later
        ) == {"posted": False, "due": False}
    assert len(provider.sent) == 1
    assert digest_due(
        store,
        channel_id=HOST,
        workspace_id="default",
        env=env,
        now=now + timedelta(days=7),
    )
    store.close()


def test_digest_not_due_off_day_or_before_the_morning_hour(tmp_path: Path):
    store = _store(tmp_path)
    env, now = _digest_clock()
    assert digest_due(store, channel_id=HOST, workspace_id="default", env=env, now=now)
    assert not digest_due(
        store, channel_id=HOST, workspace_id="default", env=env, now=now.replace(hour=6)
    )
    assert not digest_due(
        store,
        channel_id=HOST,
        workspace_id="default",
        env=env,
        now=now + timedelta(days=3),
    )
    store.close()


def test_week_captures_ignores_other_memory_sources(tmp_path: Path):
    store = _store(tmp_path)
    store.remember(
        workspace_id="default",
        channel_id=CHANNEL,
        content="a think-tank note",
        source="think-tank",
        provenance={},
    )
    record_capture(
        store,
        workspace_id="default",
        channel_id=CHANNEL,
        text="Freese FAQ still waits",
        message_id="7",
    )
    lines = week_captures(store, workspace_id="default")
    assert [line.text for line in lines] == ["Freese FAQ still waits"]
    store.close()


def test_cook_this_is_operator_only_and_lands_in_jobpool(tmp_path: Path):
    store = _store(tmp_path)
    store.add_operator("owner-1", role="owner")
    record_capture(
        store,
        workspace_id="default",
        channel_id=CHANNEL,
        text="PM routing should prefer X",
        message_id="42",
    )
    env, now = _digest_clock()
    lines = week_captures(store, workspace_id="default", now=now)
    card = capture_digest_card(lines, workspace_id="default", now=now)
    buttons = [
        item
        for row in card.rows
        for item in row.get("components") or ()
        if isinstance(item, dict)
    ]
    assert [item["label"] for item in buttons] == [
        "Cook this: PM routing should prefer X"
    ]

    tick_capture_digest(
        store, None, channel_id=HOST, workspace_id="default", env=env, now=now
    )
    custom_id = cook_custom_id("default", cook_token("PM routing should prefer X"))

    denied: list[str] = []
    result = handle_gateway_interaction(
        store,
        HOST,
        {
            "id": "ix-1",
            "token": "tok",
            "channel_id": HOST,
            "member": {"user": {"id": "stranger"}},
            "data": {"custom_id": custom_id},
        },
        on_ask=lambda text, uid: denied.append(text),
    )
    assert result == "denied"
    assert denied == []

    asks: list[str] = []
    result = handle_gateway_interaction(
        store,
        HOST,
        {
            "id": "ix-2",
            "token": "tok",
            "channel_id": HOST,
            "member": {"user": {"id": "owner-1"}},
            "data": {"custom_id": custom_id},
        },
        on_ask=lambda text, uid: asks.append(text),
    )
    assert result == "cook"
    assert asks == ["PM routing should prefer X"]
    store.close()
