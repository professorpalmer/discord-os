"""Fork from a lineage step: a sibling thread parented off that node, not the tip."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import DiscordMessage, TaskIntake, TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.orchestration import listen as listen_mod
from agent_discord.orchestration.fork import (
    FORK_OF_META,
    FORK_PARENT_META,
    FORK_STEP_META,
    fork_note,
    parse_fork_command,
    resolve_fork_parent,
)
from agent_discord.orchestration.lineage import list_nodes, list_stack, tip_key
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend

CHANNEL = "ch-1"
THREAD = "thread-1"


def test_parse_fork_command():
    asked = parse_fork_command("fork from 2: try it with the cache off")
    assert asked is not None
    assert asked.token == "2"
    assert asked.prompt == "try it with the cache off"

    keyed = parse_fork_command("Fork From a1b2c3d4: redo the diff")
    assert keyed is not None
    assert keyed.token == "a1b2c3d4"

    assert parse_fork_command("fork from 2") is None
    assert parse_fork_command("fork from 2:   ") is None
    assert parse_fork_command("what does fork from mean?") is None
    assert parse_fork_command("retry") is None


def _run_with_lineage(tmp_path: Path) -> tuple[SQLiteStore, AgentOrchestrator, str]:
    store = SQLiteStore(tmp_path / "fork.sqlite3")
    store.initialize()
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        discord=None,
        post_progress_to_discord=False,
    )
    receipt = orch.run_task(
        TaskIntake(
            text="what is Discord OS?",
            channel_id=CHANNEL,
            workspace_id="ws",
            thread_id=THREAD,
        )
    )
    assert receipt.status == TaskStatus.COMPLETED
    return store, orch, receipt.run_id


def test_lineage_step_numbers_are_execution_order(tmp_path: Path):
    """`fork from N` is only meaningful if step 1 is the first thing that happened.

    created_at is whole seconds, so a fast run's nodes share one; the store
    breaks the tie on rowid rather than on the key hash.
    """

    store, _orch, run_id = _run_with_lineage(tmp_path)
    steps = [node.step for node in list_stack(store, run_id)]
    assert steps[0] == "intake"
    assert steps[-1] == "settle"
    store.close()


def test_resolve_fork_parent_by_step_and_by_key_prefix(tmp_path: Path):
    store, _orch, run_id = _run_with_lineage(tmp_path)
    nodes = list_stack(store, run_id)
    assert len(nodes) >= 2
    assert nodes[0].step == "intake"

    node, step, refusal = resolve_fork_parent(store, run_id, "1")
    assert refusal == ""
    assert step == 1
    assert node.node_key == nodes[0].node_key

    keyed, step_keyed, refusal = resolve_fork_parent(
        store, run_id, nodes[1].node_key[:8]
    )
    assert refusal == ""
    assert step_keyed == 2
    assert keyed.node_key == nodes[1].node_key
    store.close()


def test_resolve_fork_parent_refuses_an_unknown_step(tmp_path: Path):
    store, _orch, run_id = _run_with_lineage(tmp_path)
    node, step, refusal = resolve_fork_parent(store, run_id, "99")
    assert node is None and step == 0
    assert "fork from 99" in refusal
    assert "discord-os lineage" in refusal

    node, _step, refusal = resolve_fork_parent(store, "", "1")
    assert node is None
    assert "no run in this thread" in refusal
    store.close()


def test_fork_parents_the_new_run_at_that_node_not_the_tip(tmp_path: Path):
    store, orch, run_id = _run_with_lineage(tmp_path)
    nodes = list_stack(store, run_id)
    first = nodes[0]
    assert first.step == "intake"
    tip = tip_key(list_nodes(store, run_id))
    assert tip != first.node_key

    forked = orch.run_task(
        TaskIntake(
            text="try it with the cache off",
            channel_id=CHANNEL,
            workspace_id="ws",
            metadata={
                FORK_PARENT_META: first.node_key,
                FORK_OF_META: run_id,
                FORK_STEP_META: 1,
            },
        )
    )
    assert forked.status == TaskStatus.COMPLETED
    intake_node = next(
        node for node in list_nodes(store, forked.run_id) if node.step == "intake"
    )
    assert intake_node.parent_keys == (first.node_key,)
    assert tip not in intake_node.parent_keys
    store.close()


def test_fork_note_names_the_source():
    note = fork_note(
        {FORK_PARENT_META: "abcdef1234", FORK_STEP_META: 2, "fork_of_code": "DOS-10001"}
    )
    assert note == "Forked from step 2 of DOS-10001 (node abcdef12)."
    assert fork_note({}) == ""


def _message(text: str, author: str = "op-1") -> DiscordMessage:
    return DiscordMessage(
        channel_id=CHANNEL,
        content=text,
        message_id=f"m-{abs(hash((text, author))) % 10**8}",
        thread_id=THREAD,
        author_id=author,
    )


def test_absorb_fork_opens_a_sibling_thread(tmp_path: Path):
    store = SQLiteStore(tmp_path / "absorb.sqlite3")
    store.initialize()
    store.add_operator("op-1", role="owner")
    provider = FakeDiscordMCPProvider()
    discord = DiscordFacade(provider, bot_token_fingerprint="fp")
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        discord=discord,
        post_progress_to_discord=True,
    )
    first = orch.run_task(
        TaskIntake(
            text="what is Discord OS?",
            channel_id=CHANNEL,
            workspace_id="ws",
            thread_id=THREAD,
        )
    )
    nodes = list_stack(store, first.run_id)

    handled = listen_mod._absorb_fork(
        orch,
        discord,
        store,
        None,
        message=_message("fork from 1: try it with the cache off"),
        text="fork from 1: try it with the cache off",
        channel_id=CHANNEL,
        thread_id=THREAD,
        workspace_id="ws",
        guild_id=None,
    )
    assert handled is True

    runs = [
        row
        for row in store.list_recent_jobs(CHANNEL, limit=10)
        if row["run_id"] != first.run_id
    ]
    assert len(runs) == 1
    forked = runs[0]
    assert forked["intake_text"] == "try it with the cache off"
    # A sibling thread, not the thread the fork was asked in.
    assert forked["thread_id"] and forked["thread_id"] != THREAD
    intake_node = next(
        node for node in list_nodes(store, forked["run_id"]) if node.step == "intake"
    )
    assert intake_node.parent_keys == (nodes[0].node_key,)
    # The first card in the new thread says what it forked from.
    posted = [
        msg
        for msg in provider.sent
        if msg.thread_id == forked["thread_id"] and "Forked from step 1" in msg.content
    ]
    assert posted
    store.close()


def test_absorb_fork_is_operator_only(tmp_path: Path):
    store = SQLiteStore(tmp_path / "deny.sqlite3")
    store.initialize()
    store.add_operator("op-1", role="owner")
    provider = FakeDiscordMCPProvider()
    discord = DiscordFacade(provider, bot_token_fingerprint="fp")
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        discord=None,
        post_progress_to_discord=False,
    )
    orch.run_task(
        TaskIntake(
            text="what is Discord OS?",
            channel_id=CHANNEL,
            workspace_id="ws",
            thread_id=THREAD,
        )
    )
    before = len(store.list_recent_jobs(CHANNEL, limit=10))

    handled = listen_mod._absorb_fork(
        orch,
        discord,
        store,
        None,
        message=_message("fork from 1: do it my way", author="stranger"),
        text="fork from 1: do it my way",
        channel_id=CHANNEL,
        thread_id=THREAD,
        workspace_id="ws",
        guild_id=None,
    )
    assert handled is True
    assert len(store.list_recent_jobs(CHANNEL, limit=10)) == before
    store.close()


def test_absorb_fork_ignores_ordinary_replies(tmp_path: Path):
    store = SQLiteStore(tmp_path / "plain.sqlite3")
    store.initialize()
    assert (
        listen_mod._absorb_fork(
            None,
            None,
            store,
            None,
            message=_message("keep going"),
            text="keep going",
            channel_id=CHANNEL,
            thread_id=THREAD,
            workspace_id="ws",
            guild_id=None,
        )
        is False
    )
    # Not in a thread: a parent-channel ask is never a fork.
    assert (
        listen_mod._absorb_fork(
            None,
            None,
            store,
            None,
            message=_message("fork from 1: nope"),
            text="fork from 1: nope",
            channel_id=CHANNEL,
            thread_id=None,
            workspace_id="ws",
            guild_id=None,
        )
        is False
    )
    store.close()
