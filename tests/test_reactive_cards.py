"""P2.14: parked / idle / running rows stay reactive-consistent."""

from __future__ import annotations

from agent_discord.contracts import RunReceipt, TaskStatus
from agent_discord.orchestration.cards import (
    COLOR_FAIL,
    COLOR_LIVE,
    COLOR_WORK,
    job_action_row,
    receipt_card,
    working_card,
)
from agent_discord.orchestration.reactive import (
    ACTIONS_IDLE,
    ACTIONS_PARKED,
    ACTIONS_RUNNING,
    DONE_BUTTONS,
    IDLE_BUTTONS,
    PARKED_BUTTONS,
    RUNNING_BUTTONS,
    action_labels,
    reactive_action_row,
    reactive_for_job,
    reactive_paint,
)


def _labels(row: dict) -> list[str]:
    return [str(item.get("label") or "") for item in row.get("components") or ()]


def test_parked_idle_running_rows_match_reactive_seam():
    parked = reactive_paint(TaskStatus.PENDING)
    assert parked.actions == ACTIONS_PARKED
    assert parked.accent == COLOR_WORK
    assert parked.stage == "Allow write"
    assert action_labels(parked.actions) == PARKED_BUTTONS
    assert _labels(reactive_action_row("run-park", parked)) == list(PARKED_BUTTONS)
    assert _labels(job_action_row("run-park", actions=parked.actions)) == list(
        PARKED_BUTTONS
    )
    card = working_card(
        task_label=parked.stage,
        message="Waiting for Allow to write.",
        run_id="run-park",
        actions=parked.actions,
    )
    assert card.color == parked.accent
    assert card.title == "Allow write"
    assert [item["custom_id"] for item in card.rows[0]["components"]] == [
        "discord-os:job:approve:run-park",
        "discord-os:job:always:run-park",
        "discord-os:job:deny:run-park",
    ]

    idle = reactive_paint(TaskStatus.COMPLETED, has_thread=True)
    assert idle.actions == ACTIONS_IDLE
    assert idle.accent == COLOR_LIVE
    assert idle.stage == "Done"
    assert action_labels(idle.actions) == IDLE_BUTTONS
    assert _labels(reactive_action_row("run-idle", idle)) == list(IDLE_BUTTONS)
    rec = receipt_card(
        RunReceipt(
            task_id="t",
            run_id="run-idle",
            status=TaskStatus.COMPLETED,
            summary="shipped",
        ),
        actions=idle.actions,
    )
    assert rec.color == idle.accent
    assert [item["custom_id"] for item in rec.rows[0]["components"]] == [
        "discord-os:job:continue:run-idle",
    ]

    running = reactive_paint(TaskStatus.RUNNING)
    assert running.actions == ACTIONS_RUNNING
    assert running.accent == COLOR_WORK
    assert running.stage == "Working"
    assert action_labels(running.actions) == RUNNING_BUTTONS
    assert _labels(reactive_action_row("run-live", running)) == list(RUNNING_BUTTONS)
    live = working_card(
        task_label=running.stage,
        message="editing cards",
        run_id="run-live",
        actions=running.actions,
    )
    assert live.color == running.accent
    assert [item["custom_id"] for item in live.rows[0]["components"]] == [
        "discord-os:job:cancel:run-live",
    ]


def test_reactive_for_job_matches_host_jobs_mapping():
    assert reactive_for_job({"status": "pending"}).actions == ACTIONS_PARKED
    assert (
        reactive_for_job({"status": "completed", "thread_id": "th"}).actions
        == ACTIONS_IDLE
    )
    assert reactive_for_job({"status": "running"}).actions == ACTIONS_RUNNING
    failed = reactive_for_job({"status": "failed", "thread_id": "th"})
    assert failed.actions == ACTIONS_IDLE
    assert failed.accent == COLOR_FAIL
    assert failed.stage == "Failed"
    # No thread: settled receipt, not a session Continue-only row.
    done = reactive_for_job({"status": "completed"})
    assert done.actions == "done"
    assert action_labels(done.actions) == DONE_BUTTONS
    # progress without a live-running flag still paints done (today's HOST Jobs).
    assert reactive_for_job({"status": "progress"}).actions == "done"
