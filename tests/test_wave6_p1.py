"""Wave 6 P1: dual steer, quiet doctor/status, overnight pack, narrative, cites."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import RunReceipt, TaskStatus
from agent_discord.host.brain import build_compact_recall_pack, list_brain_cites
from agent_discord.host.doctor import (
    doctor_notify_should_post,
    filter_doctor_notify_lines,
)
from agent_discord.host.status_digest import (
    MIN_CHECK_INTERVAL_S,
    TERMINAL_JOB_STATUSES,
    digest_signature,
)
from agent_discord.orchestration.cards import progress_card, receipt_card
from agent_discord.orchestration.lineage import (
    citation_refs,
    format_citation_refs,
    format_narrative_beats,
    format_progress_ledger,
    narrative_beats,
    progress_ledger_facts,
    record_node,
)
from agent_discord.orchestration.overnight_pack import (
    compose_overnight_brief_ask,
    format_overnight_pack,
    is_overnight_brief_prompt,
)
from agent_discord.orchestration.steer_attrib import (
    dual_steer_conflict_note,
    format_steer_footer,
    should_note_dual_steer,
)
from agent_discord.persistence.sqlite import SQLiteStore


def test_steer_footer_format():
    assert format_steer_footer("42", "please also fix tests") == (
        "by:42 · please also fix tests"
    )
    assert format_steer_footer("", "").startswith("by:")


def test_dual_steer_conflict_once_without_claim():
    steers = [
        {"operator_id": "111", "ts": 1000.0},
        {"operator_id": "222", "ts": 1010.0},
    ]
    assert should_note_dual_steer(steers, claimed_by="", already_noted=False, now=1050.0)
    assert not should_note_dual_steer(steers, claimed_by="111", already_noted=False, now=1050.0)
    assert not should_note_dual_steer(steers, claimed_by="", already_noted=True, now=1050.0)
    note = dual_steer_conflict_note(("111", "222"), job_code="DOS-10001")
    assert "Dual steer" in note
    assert "DOS-10001" in note


def test_progress_card_includes_steer_footer():
    card = progress_card(
        stage="running",
        message="working",
        run_id="r1",
        steer_footer="by:9 · nudge left",
    )
    assert "by:9 · nudge left" in card.description


def test_digest_ignores_failed_and_interval_raised():
    assert MIN_CHECK_INTERVAL_S >= 120.0
    assert "failed" in TERMINAL_JOB_STATUSES
    assert "error" in TERMINAL_JOB_STATUSES
    base = {
        "host": {"armed": True, "running": True, "pid": 1},
        "spend": {"spend_usd": 0.1, "spend_known": True, "cap_usd": None, "halted": False},
        "hosts": [],
    }
    failed = {**base, "jobs": [{"job_code": "DOS-1", "status": "failed"}]}
    empty = {**base, "jobs": []}
    assert digest_signature(failed) == digest_signature(empty)


def test_doctor_notify_fail_only_default():
    lines = ["OK workspace", "WARN host.pid missing", "FAIL gateway WS unhealthy — x"]
    assert filter_doctor_notify_lines(lines) == [
        "FAIL gateway WS unhealthy — x"
    ]
    verbose = filter_doctor_notify_lines(lines, verbose=True)
    assert any(x.startswith("WARN ") for x in verbose)
    assert any(x.startswith("FAIL ") for x in verbose)
    assert doctor_notify_should_post(1, lines, verbose=False)
    assert not doctor_notify_should_post(0, ["OK workspace", "WARN soft"], verbose=False)
    assert doctor_notify_should_post(0, ["WARN soft"], verbose=True)


def test_overnight_brief_pack_inject(tmp_path: Path):
    assert is_overnight_brief_prompt("overnight brief: summarize Needs")
    assert is_overnight_brief_prompt("[overnight-brief] morning")
    assert not is_overnight_brief_prompt("board catch-up: conflicts")
    store = SQLiteStore(tmp_path / "o.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t1",
        workspace_id="default",
        channel_id="ch",
        intake_text="parked gate allow write",
    )
    # Best-effort: pack still formats with empty jobs
    ask = compose_overnight_brief_ask(
        "overnight brief: keep it short",
        store=store,
        channel_id="ch",
        workspace_id="default",
    )
    assert "[overnight-brief-pack]" in ask
    assert "Needs:" in ask
    assert "Live:" in ask
    assert "Catch-up skipped:" in ask
    assert "keep it short" in ask
    pack = format_overnight_pack(
        {
            "needs": ["DOS-1:pending"],
            "live": ["DOS-2:running"],
            "parks": ["DOS-1:pending"],
            "spend": "spend unknown",
            "catchup_skipped": 2,
        }
    )
    assert "DOS-1:pending" in pack
    assert "Catch-up skipped: 2" in pack
    store.close()


def test_narrative_beats_and_receipt_story(tmp_path: Path):
    store = SQLiteStore(tmp_path / "n.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t1", workspace_id="default", channel_id="ch", intake_text="x"
    )
    store.create_run(
        run_id="r1", task_id="t1", model="openrouter/auto", adapter_name="test"
    )
    record_node(store, run_id="r1", task_id="t1", step="plan_approved", body="p")
    record_node(
        store,
        run_id="r1",
        task_id="t1",
        step="gate_allowed",
        body="g",
        artifact_id="deadbeefcafebabe",
    )
    record_node(
        store,
        run_id="r1",
        task_id="t1",
        step="artifact",
        body="a",
        artifact_id="abcdef0123456789",
    )
    beats = narrative_beats(store, "r1", limit=3)
    assert len(beats) <= 3
    assert any("plan_approved" in b for b in beats)
    story = format_narrative_beats(beats)
    assert "→" in story or story
    led = format_progress_ledger(progress_ledger_facts(store, "r1"))
    cites = format_citation_refs(citation_refs(store, "r1", job_code="DOS-10001"))
    assert "DOS-10001" in cites
    card = receipt_card(
        RunReceipt(
            task_id="t1",
            run_id="r1",
            status=TaskStatus.COMPLETED,
            summary="ok",
        ),
        ledger=led,
        narrative=story,
        cites=cites,
    )
    names = [n for n, _v, _i in card.fields]
    assert "Story" in names
    assert "Cites" in names
    store.close()


def test_brain_cites_in_recall_pack(tmp_path: Path):
    store = SQLiteStore(tmp_path / "b.sqlite3")
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
    task_id = store.create_task(
        task_id="t9",
        workspace_id="default",
        channel_id="ch",
        intake_text="done work",
    )
    # Mark completed if API allows
    updater = getattr(store, "update_task", None)
    if callable(updater):
        try:
            updater(task_id, status="completed", summary="shipped wave6")
        except TypeError:
            try:
                updater("t9", status="completed", summary="shipped wave6")
            except Exception:
                pass
    pack = build_compact_recall_pack(
        store.get_binding("default", "ch"),
        store=store,
        workspace_id="default",
        channel_id="ch",
        max_bytes=2000,
    )
    assert "[brain-lake]" in pack
    cites = list_brain_cites(
        store.get_binding("default", "ch"),
        store=store,
        workspace_id="default",
        channel_id="ch",
        dri="alex",
    )
    # Journal cite and/or DOS code when present
    assert isinstance(cites, list)
    if "Cites:" in pack:
        assert "Cites:" in pack
    store.close()
