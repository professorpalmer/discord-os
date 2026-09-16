"""Wave 5 P1: recall pack, ledger, plan gallery, path conflicts, claim."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import RunReceipt, TaskStatus
from agent_discord.host.brain import (
    build_compact_recall_pack,
    clip_pack_text,
    record_plan_gallery,
)
from agent_discord.orchestration.board_catchup import scan_job_conflicts
from agent_discord.orchestration.cards import progress_card, receipt_card
from agent_discord.orchestration.lineage import (
    format_progress_ledger,
    progress_ledger_facts,
    record_node,
)
from agent_discord.orchestration.service import parse_claim_command
from agent_discord.persistence.sqlite import SQLiteStore


def test_compact_recall_pack_clips(tmp_path: Path):
    store = SQLiteStore(tmp_path / "a.sqlite3")
    store.initialize()
    store.upsert_binding(
        workspace_id="default",
        channel_id="ch",
        metadata={
            "brain": True,
            "dri": "alex",
            "strategy_docs": str(tmp_path),
            "journal": True,
        },
    )
    (tmp_path / "strategy.md").write_text("x")
    store.set_preference("default", "journal:alex:1", "note one", kind="journal")
    pack = build_compact_recall_pack(
        store.get_binding("default", "ch"),
        store=store,
        workspace_id="default",
        channel_id="ch",
        max_bytes=400,
    )
    assert "[brain-lake]" in pack
    assert "DRI: alex" in pack
    assert "strategy.md" in pack or "Docs:" in pack
    assert len(pack.encode()) <= 403
    assert clip_pack_text("a" * 5000, max_bytes=100).endswith("...")
    store.close()


def test_progress_ledger_and_card_fields(tmp_path: Path):
    store = SQLiteStore(tmp_path / "b.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t1",
        workspace_id="default",
        channel_id="ch",
        intake_text="x",
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="test",
    )
    record_node(store, run_id="r1", task_id="t1", step="plan_approved", body="p")
    record_node(
        store,
        run_id="r1",
        task_id="t1",
        step="gate_allowed",
        body="g",
        artifact_id="art-1234567890",
    )
    facts = progress_ledger_facts(store, "r1", limit=5)
    assert any("plan_approved" in f for f in facts)
    led = format_progress_ledger(facts)
    assert led.startswith("Ledger:")
    card = progress_card(stage="running", message="hi", run_id="r1", ledger=led)
    assert "Ledger:" in card.description
    receipt = receipt_card(
        RunReceipt(task_id="t1", run_id="r1", status=TaskStatus.COMPLETED, summary="ok"),
        ledger=led,
    )
    assert any(n == "Ledger" for n, _v, _i in receipt.fields)
    store.close()


def test_plan_gallery_record(tmp_path: Path):
    store = SQLiteStore(tmp_path / "c.sqlite3")
    store.initialize()
    key = record_plan_gallery(
        store,
        workspace_id="default",
        channel_id="ch",
        plan_text="1. do x\n2. do y",
    )
    assert key.startswith("plan:ch:")
    rows = store.list_preferences("default", kind="plan")
    assert rows
    store.close()


def test_write_key_path_conflicts():
    jobs = [
        {
            "job_code": "DOS-A",
            "status": "running",
            "intake_text": "touch src/foo.py",
            "metadata": {"write_key": "realm/puppetmaster"},
        },
        {
            "job_code": "DOS-B",
            "status": "failed",
            "attention": "need",
            "intake_text": "also src/foo.py",
            "metadata": {"write_key": "realm/puppetmaster"},
        },
    ]
    hits = scan_job_conflicts(jobs)
    kinds = {h.kind for h in hits}
    assert "write_key" in kinds or "path" in kinds


def test_parse_claim_command():
    assert parse_claim_command("claim DOS-A1B2") == "DOS-A1B2"
    assert parse_claim_command("claim other_job") == "other_job"
    assert parse_claim_command("handoff <@1>: x") is None
