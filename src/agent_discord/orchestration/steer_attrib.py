"""Dual-operator steer attribution + quiet conflict NOTE (Wave 6 P1a).

Live card footer shows last steer ``by:<operator_id> · <clip>``. When two
distinct operators steer the same live run within a short window without a
board claim owner, post **one** quiet NOTE (no storm). Single JobPool only —
no graph editor.
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional, Sequence

STEER_CONFLICT_WINDOW_S = 120.0
STEER_CLIP_LEN = 48


def clip_steer_text(text: str, *, limit: int = STEER_CLIP_LEN) -> str:
    body = " ".join((text or "").strip().split())
    if not body:
        return ""
    if len(body) <= limit:
        return body
    return body[: max(0, limit - 1)].rstrip() + "…"


def format_steer_footer(operator_id: str, clip: str) -> str:
    """Spoken Live footer bit: ``by:<operator_id> · <clip>``."""

    op = (operator_id or "").strip() or "?"
    tip = clip_steer_text(clip)
    if tip:
        return f"by:{op} · {tip}"
    return f"by:{op}"


def claimed_owner(task_row: Mapping[str, Any] | None) -> str:
    """Board claim owner from task metadata, if any."""

    if not task_row:
        return ""
    import json

    meta_raw = task_row.get("metadata_json") or task_row.get("metadata") or {}
    if isinstance(meta_raw, str):
        try:
            meta = json.loads(meta_raw) if meta_raw.strip() else {}
        except Exception:
            meta = {}
    elif isinstance(meta_raw, Mapping):
        meta = dict(meta_raw)
    else:
        meta = {}
    return str(meta.get("claimed_by") or "").strip()


def dual_steer_ops_in_window(
    steers: Sequence[Mapping[str, Any]],
    *,
    now: Optional[float] = None,
    window_s: float = STEER_CONFLICT_WINDOW_S,
) -> tuple[str, ...]:
    """Distinct operator ids that steered inside the conflict window."""

    t_now = float(time.time() if now is None else now)
    seen: list[str] = []
    for row in steers:
        op = str(row.get("operator_id") or "").strip()
        if not op:
            continue
        try:
            ts = float(row.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        if t_now - ts > window_s:
            continue
        if op not in seen:
            seen.append(op)
    return tuple(seen)


def should_note_dual_steer(
    steers: Sequence[Mapping[str, Any]],
    *,
    claimed_by: str = "",
    already_noted: bool = False,
    now: Optional[float] = None,
    window_s: float = STEER_CONFLICT_WINDOW_S,
) -> bool:
    """True once: two distinct operators, no claim ownership, not yet noted."""

    if already_noted:
        return False
    if (claimed_by or "").strip():
        return False
    ops = dual_steer_ops_in_window(steers, now=now, window_s=window_s)
    return len(ops) >= 2


def dual_steer_conflict_note(
    ops: Sequence[str],
    *,
    job_code: str = "",
) -> str:
    """One quiet NOTE body — no storm, no graph editor."""

    labels = [f"<@{o}>" if o.isdigit() else o for o in ops[:3] if o]
    who = " + ".join(labels) if labels else "two operators"
    code = (job_code or "").strip()
    prefix = f"{code} · " if code else ""
    return (
        f"{prefix}Dual steer ({who}) without claim — "
        "last footer wins; claim the job to own the lane."
    )


__all__ = [
    "STEER_CLIP_LEN",
    "STEER_CONFLICT_WINDOW_S",
    "claimed_owner",
    "clip_steer_text",
    "dual_steer_conflict_note",
    "dual_steer_ops_in_window",
    "format_steer_footer",
    "should_note_dual_steer",
]
