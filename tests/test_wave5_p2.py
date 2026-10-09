"""Wave 5 P2 stretch — compensation NOTE, brain lake bind, conflict lines."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskStatus
from agent_discord.host.memory import bind_brain_lake, build_compact_recall_pack
from agent_discord.orchestration.board_catchup import ConflictHit, format_conflict_lines
from agent_discord.orchestration.handoff_compensation import (
    compensation_note_text,
    is_handoff_peer_intake,
    maybe_post_handoff_compensation,
)
from agent_discord.persistence.sqlite import SQLiteStore


def test_bind_brain_lake_in_recall(tmp_path: Path):
    store = SQLiteStore(tmp_path / "t.sqlite3")
    store.initialize()
    out = bind_brain_lake(
        store,
        workspace_id="default",
        channel_id="111",
        transcripts_channel="tr-9",
    )
    assert out["transcripts_channel"] == "tr-9"
    pack = build_compact_recall_pack(
        store.get_binding("default", "111"),
        store=store,
        workspace_id="default",
    )
    assert "[brain-lake]" in pack
    assert "Transcripts channel: tr-9" in pack


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


def test_conflict_lines_name_both_jobs():
    hits = [
        ConflictHit(
            left_code="DOS-1",
            right_code="DOS-2",
            shared="ADR-003",
            kind="adr",
        )
    ]
    lines = format_conflict_lines(hits)
    assert lines and "DOS-1" in lines[0] and "DOS-2" in lines[0]
    assert "ADR-003" in lines[0]
