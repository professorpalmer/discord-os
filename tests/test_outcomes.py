"""Recorded outcomes: an operator reaction on a settled card labels that run."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.orchestration.outcomes import (
    LABEL_BAD,
    LABEL_GOOD,
    LABEL_PARTIAL,
    collect_outcomes,
    format_outcome_tally,
    label_for_emoji,
)
from agent_discord.persistence.sqlite import SQLiteStore

THUMBS_UP = "\U0001F44D"
THUMBS_DOWN = "\U0001F44E"
SHRUG = "\U0001F937"
CARD_CHANNEL = "chan-1"
CARD_MESSAGE = "msg-1"


def _settled_run(store: SQLiteStore, *, task_id: str, run_id: str, text: str = "ask") -> None:
    store.create_task(
        task_id=task_id,
        workspace_id="ws",
        channel_id=CARD_CHANNEL,
        intake_text=text,
        metadata={
            "card_message_id": CARD_MESSAGE,
            "card_channel_id": CARD_CHANNEL,
        },
    )
    store.create_run(
        run_id=run_id,
        task_id=task_id,
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.RUNNING,
    )
    store.update_run(run_id, status=TaskStatus.COMPLETED, summary="done")


def _facade(**users) -> DiscordFacade:
    provider = FakeDiscordMCPProvider()
    for emoji, rows in users.items():
        provider.reaction_users[(CARD_CHANNEL, CARD_MESSAGE, emoji)] = list(rows)
    return DiscordFacade(provider, bot_token_fingerprint="fp")


def test_emoji_map_is_three_labels():
    assert label_for_emoji(THUMBS_UP) == LABEL_GOOD
    assert label_for_emoji(THUMBS_DOWN) == LABEL_BAD
    assert label_for_emoji(SHRUG) == LABEL_PARTIAL
    assert label_for_emoji("\U0001F680") == ""


def test_operator_reaction_stores_one_outcome(tmp_path: Path):
    store = SQLiteStore(tmp_path / "out.sqlite3")
    store.initialize()
    store.add_operator("op-1", role="owner")
    _settled_run(store, task_id="t1", run_id="r1")
    discord = _facade(**{THUMBS_UP: [{"id": "op-1"}]})

    first = collect_outcomes(store, discord)
    assert first == [{"run_id": "r1", "operator_id": "op-1", "label": LABEL_GOOD}]
    # Polling again re-reads the same reaction and must not store it twice.
    assert collect_outcomes(store, discord) == []
    rows = store.list_run_outcomes("r1")
    assert [(row["operator_id"], row["label"]) for row in rows] == [("op-1", LABEL_GOOD)]
    store.close()


def test_non_operator_reactions_are_ignored(tmp_path: Path):
    store = SQLiteStore(tmp_path / "deny.sqlite3")
    store.initialize()
    store.add_operator("op-1", role="owner")
    _settled_run(store, task_id="t1", run_id="r1")
    discord = _facade(
        **{THUMBS_DOWN: [{"id": "stranger"}, {"id": "bot-1", "bot": True}]}
    )

    assert collect_outcomes(store, discord) == []
    assert store.list_run_outcomes("r1") == []
    store.close()


def test_changing_the_reaction_replaces_the_label(tmp_path: Path):
    store = SQLiteStore(tmp_path / "flip.sqlite3")
    store.initialize()
    store.add_operator("op-1", role="owner")
    _settled_run(store, task_id="t1", run_id="r1")

    collect_outcomes(store, _facade(**{THUMBS_UP: [{"id": "op-1"}]}))
    collect_outcomes(store, _facade(**{SHRUG: [{"id": "op-1"}]}))
    rows = store.list_run_outcomes("r1")
    assert [(row["operator_id"], row["label"]) for row in rows] == [("op-1", LABEL_PARTIAL)]
    store.close()


def test_running_run_has_no_card_to_read(tmp_path: Path):
    store = SQLiteStore(tmp_path / "live.sqlite3")
    store.initialize()
    store.add_operator("op-1", role="owner")
    store.create_task(
        task_id="t1",
        workspace_id="ws",
        channel_id=CARD_CHANNEL,
        intake_text="ask",
        metadata={"card_message_id": CARD_MESSAGE, "card_channel_id": CARD_CHANNEL},
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.RUNNING,
    )
    assert store.list_settled_cards() == []
    assert collect_outcomes(store, _facade(**{THUMBS_UP: [{"id": "op-1"}]})) == []
    store.close()


def test_tally_line_and_host_card(tmp_path: Path):
    from agent_discord.orchestration.cards import host_card

    store = SQLiteStore(tmp_path / "tally.sqlite3")
    store.initialize()
    for index in range(5):
        store.record_run_outcome(
            run_id=f"r{index}", operator_id="op-1", label=LABEL_GOOD
        )
    store.record_run_outcome(run_id="rb", operator_id="op-1", label=LABEL_BAD)
    tally = store.outcome_tally(days=7)
    assert tally == {LABEL_GOOD: 5, LABEL_BAD: 1}
    line = format_outcome_tally(tally)
    assert line == "Outcomes 7d: 5 good, 1 bad"

    card = host_card(armed=True, paired=True, last_job="DOS-1 · done", outcomes=line)
    assert line in (card.description or "")
    assert format_outcome_tally({}) == ""
    assert "Outcomes" not in (
        host_card(armed=True, paired=True, last_job="DOS-1 · done").description or ""
    )
    store.close()


def test_outcome_tick_is_throttled(tmp_path: Path, monkeypatch):
    from agent_discord.orchestration import listen as listen_mod

    store = SQLiteStore(tmp_path / "throttle.sqlite3")
    store.initialize()
    calls: list[int] = []
    monkeypatch.setattr(
        "agent_discord.orchestration.outcomes.collect_outcomes",
        lambda *a, **k: calls.append(1) or [],
    )
    for _ in range(3):
        listen_mod._tick_outcomes_best_effort(object(), store, env={})
    assert calls == [1]
    store.close()


def test_reaction_read_hits_the_discord_endpoint():
    from agent_discord.discord.rest import list_message_reactions

    seen: list[str] = []

    def opener(request, timeout=0):  # noqa: ANN001 - urllib opener shape
        seen.append(request.full_url)

        class _Resp:
            headers = {}

            def read(self):
                return b'[{"id": "op-1"}]'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _Resp()

    users = list_message_reactions(
        token="t",
        channel_id="c1",
        message_id="m1",
        emoji=THUMBS_UP,
        opener=opener,
    )
    assert users == ({"id": "op-1"},)
    assert seen == [
        "https://discord.com/api/v10/channels/c1/messages/m1/reactions/"
        "%F0%9F%91%8D?limit=100"
    ]


def test_lineage_cli_prints_outcomes(tmp_path: Path, monkeypatch, capsys):
    import argparse

    from agent_discord import cli as cli_mod
    from agent_discord.orchestration.lineage import record_node

    store = SQLiteStore(tmp_path / "lin.sqlite3")
    store.initialize()
    _settled_run(store, task_id="t1", run_id="r1")
    record_node(store, run_id="r1", task_id="t1", step="intake", body="ask")
    store.record_run_outcome(run_id="r1", operator_id="op-1", label=LABEL_GOOD)
    store.close()

    config = cli_mod.load_config()
    object.__setattr__(config, "database_path", tmp_path / "lin.sqlite3")
    monkeypatch.setattr(cli_mod, "load_config", lambda: config)
    monkeypatch.setattr(cli_mod, "apply_runtime_secrets", lambda cfg: cfg)

    code = cli_mod.cmd_lineage(argparse.Namespace(run_id="r1", json=False))
    text = capsys.readouterr().out
    assert code == 0
    assert "outcomes: good by op-1" in text
    assert "  1  intake" in text
