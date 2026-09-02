"""SQLite execution lineage DAG. Not Temporal. Not chat-as-state."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskIntake, TaskStatus
from agent_discord.orchestration.cards import receipt_card
from agent_discord.orchestration.lineage import (
    LINEAGE_STEPS,
    descendants_to_replay,
    input_sha256,
    list_nodes,
    mark_stale,
    node_key,
    record_node,
    tip_key,
)
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def test_node_key_is_stable():
    assert "intake" in LINEAGE_STEPS
    digest = input_sha256("hello")
    first = node_key("intake", digest, ())
    second = node_key("intake", digest, ())
    assert first == second
    assert first != node_key("settle", digest, ())


def test_descendants_to_replay_skips_unrelated(tmp_path: Path):
    store = SQLiteStore(tmp_path / "lin.sqlite3")
    store.initialize()
    a = record_node(store, run_id="r", task_id="t", step="intake", body="ask")
    b = record_node(
        store, run_id="r", task_id="t", step="dispatch", body="prompt", parent_keys=(a,)
    )
    c = record_node(
        store, run_id="r", task_id="t", step="settle", body="done", parent_keys=(b,)
    )
    nodes = list_nodes(store, "r")
    assert tip_key(nodes) == c
    replay = descendants_to_replay(nodes, a)
    assert b in replay
    assert c in replay
    assert a not in replay
    store.close()


def test_mark_stale_then_tip_skips_them(tmp_path: Path):
    store = SQLiteStore(tmp_path / "stale.sqlite3")
    store.initialize()
    a = record_node(store, run_id="r", task_id="t", step="intake", body="ask")
    b = record_node(store, run_id="r", task_id="t", step="dispatch", body="prompt")
    assert mark_stale(store, [b]) == 1
    nodes = list_nodes(store, "r")
    assert tip_key(nodes) == a
    store.close()


def test_run_task_records_lineage_and_cites_sha256(tmp_path: Path):
    store = SQLiteStore(tmp_path / "run.sqlite3")
    store.initialize()
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        post_progress_to_discord=False,
    )
    receipt = orch.run_task(
        TaskIntake(text="what is Discord OS?", channel_id="ch", workspace_id="ws")
    )
    assert receipt.status == TaskStatus.COMPLETED
    nodes = list_nodes(store, receipt.run_id)
    steps = [node.step for node in nodes]
    assert steps.count("intake") == 1
    assert "dispatch" in steps
    assert "settle" in steps
    assert any(art.kind == "settle" and art.sha256 for art in receipt.artifacts)
    digest = next(art.sha256[:12] for art in receipt.artifacts if art.kind == "settle")
    card = receipt_card(receipt)
    assert digest in card.text
    store.close()


def test_retry_parents_new_run_at_previous_tip(tmp_path: Path):
    store = SQLiteStore(tmp_path / "retry.sqlite3")
    store.initialize()
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        post_progress_to_discord=False,
    )
    first = orch.run_task(
        TaskIntake(text="what is Discord OS?", channel_id="ch", workspace_id="ws")
    )
    result = orch.apply_job_action("retry", first.run_id)
    assert result["replay_of"] == first.run_id
    assert result["intake_text"] == "what is Discord OS?"
    second = orch.run_task(
        TaskIntake(
            text=result["intake_text"],
            channel_id="ch",
            workspace_id="ws",
            metadata={"replay_of": result["replay_of"]},
        )
    )
    nodes = list_nodes(store, second.run_id)
    assert any(node.step == "replay" for node in nodes)
    replay = next(node for node in nodes if node.step == "replay")
    prev_tip = tip_key(list_nodes(store, first.run_id))
    assert prev_tip in replay.parent_keys
    store.close()


def test_steer_appends_lineage_node(tmp_path: Path):
    store = SQLiteStore(tmp_path / "steer.sqlite3")
    store.initialize()
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        post_progress_to_discord=False,
    )
    store.create_task(
        task_id="t1",
        workspace_id="ws",
        channel_id="ch",
        intake_text="ask",
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="cursor/grok-4-5",
        adapter_name="grok-4.5",
        status=TaskStatus.RUNNING,
    )
    orch._run_status["r1"] = TaskStatus.RUNNING
    orch._live_threads["th"] = "r1"
    assert orch.steer("r1", "nudge left")
    nodes = list_nodes(store, "r1")
    assert any(node.step == "steer" for node in nodes)
    assert any(node.input_sha256 == input_sha256("nudge left") for node in nodes)
    store.close()


def test_cli_lineage_json(monkeypatch, tmp_path: Path, capsys):
    import json

    from agent_discord.cli import main

    db = tmp_path / "agent_discord.sqlite3"
    store = SQLiteStore(db)
    store.initialize()
    record_node(store, run_id="r9", task_id="t", step="intake", body="ask")
    store.close()
    fake = type("Cfg", (), {"database_path": db})()
    monkeypatch.setattr("agent_discord.cli.load_config", lambda: fake)
    monkeypatch.setattr("agent_discord.cli.apply_runtime_secrets", lambda cfg: cfg)
    assert main(["lineage", "r9", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "r9"
    assert payload["nodes"][0]["step"] == "intake"
