"""Progress events store deltas; old progress rows of finished runs are pruned."""

from __future__ import annotations

import json
from pathlib import Path

from agent_discord.contracts import EventKind, TaskStatus
from agent_discord.orchestration.orchestrator import _stored_progress_details
from agent_discord.persistence.sqlite import SQLiteStore


def test_progress_details_store_only_what_was_added() -> None:
    """Audit C3: each event used to store the whole cumulative window."""

    seen: list[str] = []
    windows = ["Hel", "Hello", "Hello, wor", "Hello, world.", "Hello, world."]
    stored = [_stored_progress_details({"token_text": w, "token": True}, seen) for w in windows]
    assert [s.get("token_delta", "") for s in stored] == ["Hel", "lo", ", wor", "ld.", ""]
    assert all("token_text" not in s for s in stored)
    assert all(s["token"] is True for s in stored)


def test_progress_details_track_text_and_reasoning_streams() -> None:
    seen: list[str] = []
    out = [
        _stored_progress_details({"token_text": w}, seen)
        for w in ("think a", "Ans", "think a, b", "Answer")
    ]
    assert [o.get("token_delta") for o in out] == ["think a", "Ans", ", b", "wer"]


def test_progress_details_without_window_pass_through() -> None:
    assert _stored_progress_details({"stage": "x"}, []) == {"stage": "x"}


def _run(store: SQLiteStore, run_id: str, status: TaskStatus) -> None:
    store.create_task(task_id=f"t-{run_id}", workspace_id="ws", channel_id="ch", intake_text="x")
    store.create_run(run_id=run_id, task_id=f"t-{run_id}", model="m", adapter_name="a", status=status)


def _event(store: SQLiteStore, run_id: str, kind: EventKind, age_days: float) -> None:
    store.append_event(
        task_id=f"t-{run_id}", run_id=run_id, kind=kind, summary="s",
        payload={"details": {"token_delta": "x" * 100}}, source="test", provenance={},
    )
    store._connection().execute(
        "UPDATE events SET created_at = datetime('now', ?) WHERE id = (SELECT MAX(id) FROM events)",
        (f"-{age_days} days",),
    )
    store._connection().commit()


def test_compact_events_keeps_recent_live_and_non_progress(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "w.sqlite3")
    store.initialize()
    _run(store, "done", TaskStatus.COMPLETED)
    _run(store, "live", TaskStatus.RUNNING)
    for _ in range(3):
        _event(store, "done", EventKind.PROGRESS, 30)
    _event(store, "done", EventKind.PROGRESS, 1)
    _event(store, "done", EventKind.RECEIPT, 30)
    _event(store, "live", EventKind.PROGRESS, 30)
    result = store.compact_events(older_than_days=14, vacuum_min_rows=1)
    assert result == {"deleted": 3, "vacuumed": True}
    kinds = [(e["run_id"], e["kind"]) for e in store.list_events("done")] + [
        (e["run_id"], e["kind"]) for e in store.list_events("live")
    ]
    assert sorted(kinds) == [("done", "progress"), ("done", "receipt"), ("live", "progress")]
    store.close()


def test_db_compact_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    from agent_discord.cli import main

    ws = tmp_path / ".agent-discord"
    ws.mkdir()
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    _run(store, "done", TaskStatus.FAILED)
    _event(store, "done", EventKind.PROGRESS, 20)
    store.close()
    assert main(["db", "compact", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deleted"] == 1 and out["vacuumed"] is True
