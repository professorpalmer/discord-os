"""Reactive job-card paint: state → button set, accent, stage.

Spike (P2.14). Not a widget framework. Callers that already know
``actions=`` still pass it to card builders. This module is the named
seam when a SQLite job row must become that mode plus accent and stage.

Write-gate Allow / Always allow / Deny and Jobs Continue live here.
Discord Activities and a full client UI do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Union

from agent_discord.contracts import TaskStatus
from agent_discord.orchestration.cards import (
    COLOR_FAIL,
    COLOR_IDLE,
    COLOR_LIVE,
    COLOR_WORK,
    job_action_row,
)
from agent_discord.orchestration.job_briefing import is_idle_job

ACTIONS_PARKED = "parked"
ACTIONS_RUNNING = "running"
ACTIONS_IDLE = "idle"
ACTIONS_DONE = "done"

# Labels the write-gate and Continue rows must keep. Styles stay in cards.py.
PARKED_BUTTONS = ("Allow", "Always allow", "Deny")
RUNNING_BUTTONS = ("Cancel",)
IDLE_BUTTONS = ("Continue",)
DONE_BUTTONS = ("Continue", "Retry")

_STAGE_CHROME: dict[TaskStatus, tuple[str, int]] = {
    TaskStatus.COMPLETED: ("Done", COLOR_LIVE),
    TaskStatus.FAILED: ("Failed", COLOR_FAIL),
    TaskStatus.CANCELLED: ("Cancelled", COLOR_IDLE),
    TaskStatus.RUNNING: ("Working", COLOR_WORK),
    TaskStatus.PROGRESS: ("Working", COLOR_WORK),
    TaskStatus.PENDING: ("Allow write", COLOR_WORK),
}


@dataclass(frozen=True)
class ReactivePaint:
    """One paint: button mode, accent, spoken stage."""

    actions: str
    accent: int
    stage: str


def reactive_paint(
    status: Union[str, TaskStatus, None] = None,
    *,
    awaiting_approval: bool = False,
    has_thread: bool = False,
) -> ReactivePaint:
    """Map a job row to the button set / accent / stage the card will show.

    Matches HOST Jobs + write-gate park today:

    - pending (or explicit awaiting_approval) → parked Allow / Always / Deny
    - completed / failed / cancelled with a thread → idle Continue
    - running → Cancel
    - otherwise → done Continue + Retry (receipt chrome)
    """

    state = _as_status(status)
    if awaiting_approval or state is TaskStatus.PENDING:
        return ReactivePaint(
            actions=ACTIONS_PARKED,
            accent=COLOR_WORK,
            stage="Allow write",
        )
    if state is not None and is_idle_job({"status": state.value}) and has_thread:
        stage, accent = _STAGE_CHROME[state]
        return ReactivePaint(actions=ACTIONS_IDLE, accent=accent, stage=stage)
    if state is TaskStatus.RUNNING:
        return ReactivePaint(
            actions=ACTIONS_RUNNING,
            accent=COLOR_WORK,
            stage="Working",
        )
    stage, accent = _STAGE_CHROME.get(state, ("Receipt", COLOR_IDLE))
    return ReactivePaint(actions=ACTIONS_DONE, accent=accent, stage=stage)


def reactive_for_job(job: Mapping[str, Any]) -> ReactivePaint:
    """HOST / briefing path: one SQLite-ish row → paint."""

    return reactive_paint(
        job.get("status"),
        awaiting_approval=bool(job.get("awaiting_approval")),
        has_thread=bool(str(job.get("thread_id") or "").strip()),
    )


def reactive_action_row(run_id: str, paint: ReactivePaint) -> dict[str, Any]:
    """Same action row ``job_action_row`` would emit for ``paint.actions``."""

    return job_action_row(run_id, actions=paint.actions)


def action_labels(actions: str) -> tuple[str, ...]:
    mode = (actions or "").strip().lower()
    if mode == ACTIONS_RUNNING:
        return RUNNING_BUTTONS
    if mode == ACTIONS_IDLE:
        return IDLE_BUTTONS
    if mode == ACTIONS_DONE:
        return DONE_BUTTONS
    return PARKED_BUTTONS


def _as_status(status: Union[str, TaskStatus, None]) -> Optional[TaskStatus]:
    if isinstance(status, TaskStatus):
        return status
    raw = str(status or "").strip().lower()
    if not raw:
        return None
    try:
        return TaskStatus(raw)
    except ValueError:
        return None
