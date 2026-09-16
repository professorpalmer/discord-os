"""Wave 5 P2 stretch — compensation NOTE, DRI role SOP, cross-DRI lanes."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskStatus
from agent_discord.host.brain import (
    BRAIN_ROLES,
    bind_brain,
    brain_from_binding,
    build_compact_recall_pack,
    normalize_brain_role,
)
from agent_discord.orchestration.board_catchup import ConflictHit, format_conflict_lines
from agent_discord.orchestration.handoff_compensation import (
    compensation_note_text,
    is_handoff_peer_intake,
    maybe_post_handoff_compensation,
)
from agent_discord.orchestration.job_briefing import lane_relationships
from agent_discord.persistence.sqlite import SQLiteStore


def test_normalize_brain_role():
    assert normalize_brain_role("Implementer") == "implementer"
    assert normalize_brain_role("nope") == ""
    assert BRAIN_ROLES == frozenset({"implementer", "reviewer", "planner"})


def test_bind_brain_role_in_recall(tmp_path: Path):
    store = SQLiteStore(tmp_path / "t.sqlite3")
    store.initialize()
    out = bind_brain(
        store,
        workspace_id="default",
        channel_id="111",
        dri="alex",
        role="reviewer",
    )
    assert out["brain_role"] == "reviewer"
    brain = brain_from_binding(store.get_binding("default", "111"))
    assert brain["brain_role"] == "reviewer"
    pack = build_compact_recall_pack(
        store.get_binding("default", "111"),
        store=store,
        workspace_id="default",
    )
    assert "Role SOP: reviewer" in pack
    assert "DRI: alex" in pack


def test_compensation_note_and_post(tmp_path: Path):
    store = SQLiteStore(tmp_path / "t.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t1",
        workspace_id="default",
        channel_id="chan",
        intake_text="peer work",
        metadata={"peer_task": True, "handoff_id": "h1", "parent_thread_id": "thr"},
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.RUNNING,
    )

    class _Intake:
        channel_id = "chan"
        thread_id = "thr"
        metadata = {"peer_task": True, "handoff_id": "h1", "parent_thread_id": "thr"}

    class _Discord:
        def __init__(self):
            self.msgs = []

        def send_message(self, channel_id, text, thread_id=None):
            self.msgs.append((channel_id, text, thread_id))

    d = _Discord()
    note = maybe_post_handoff_compensation(
        store=store,
        discord=d,
        intake=_Intake(),
        task_id="t1",
        run_id="r1",
        status=TaskStatus.FAILED,
        summary="boom",
        job_code="DOS-10001",
    )
    assert note and "compensation" in note and "h1" in note
    assert d.msgs and "NOTE:" in d.msgs[0][1]
    assert is_handoff_peer_intake(_Intake())
    assert "Saga-lite" in compensation_note_text(handoff_id="x", status="cancelled")


def test_cross_dri_conflict_lines():
    hits = [
        ConflictHit(
            left_code="DOS-1",
            right_code="DOS-2",
            shared="ADR-003",
            kind="adr",
        )
    ]
    lines = format_conflict_lines(
        hits, dri_by_code={"DOS-1": "alex", "DOS-2": "sam"}
    )
    assert lines and "alex" in lines[0] and "sam" in lines[0]
    assert "cross-DRI" in lines[0]
    jobs = [
        {
            "job_code": "DOS-1",
            "intake_text": "touch ADR-003",
            "brain_dri": "alex",
            "status": "running",
        },
        {
            "job_code": "DOS-2",
            "intake_text": "also ADR-003 please",
            "brain_dri": "sam",
            "status": "running",
        },
    ]
    rel = lane_relationships(jobs)
    assert any("cross-DRI" in line or "alex" in line for line in rel)


def test_wave5_p2_docs_present():
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "docs/co-work/wave5-compensation.md",
        "docs/co-work/wave5-dri-role.md",
    ):
        text = (root / rel).read_text(encoding="utf-8").lower()
        assert "graham" not in text
