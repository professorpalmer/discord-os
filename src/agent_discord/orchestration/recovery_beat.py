"""Human recovery beat after failed peer/Live (ParaRecover-lite).

Extends Wave 5 handoff compensation NOTE with a spoken diagnostic +
Retry/Dismiss controls hint. JobPool-only — not a ParaRecover harness.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from agent_discord.contracts import EventKind, TaskStatus


RECOVERY_ACTIONS = "failed_done"  # Continue + Retry + Dismiss


def is_failed_status(status: Any) -> bool:
    st = status.value if hasattr(status, "value") else str(status or "")
    return st.strip().lower() in {
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
        "failed",
        "cancelled",
        "canceled",
        "error",
    }


def clip_diagnostic(text: str, *, limit: int = 180) -> str:
    tip = " ".join((text or "").strip().replace("\n", " ").split())
    if len(tip) <= limit:
        return tip
    return tip[: max(0, limit - 1)].rstrip() + "…"


def format_recovery_beat(
    *,
    diagnostic: str = "",
    job_code: str = "",
    status: str = "failed",
    peer: bool = False,
) -> str:
    """Spoken recovery beat: diagnostic + Retry/Dismiss controls hint."""

    st = (status or "failed").strip().lower() or "failed"
    code = (job_code or "").strip()
    diag = clip_diagnostic(diagnostic) or "no summary"
    who = "peer/Live" if peer else "Live"
    bits = [f"Recovery ({who}): {st}"]
    if code:
        bits[0] = f"Recovery ({who}) {code}: {st}"
    bits.append(f"Diagnostic — {diag}")
    bits.append("Controls: Retry or Dismiss (JobPool-only; not ParaRecover).")
    return " · ".join(bits)


def maybe_post_recovery_beat(
    *,
    store: Any,
    discord: Any,
    intake: Any,
    task_id: str,
    run_id: str,
    status: Any,
    summary: str = "",
    job_code: str = "",
    error: str = "",
) -> Optional[str]:
    """On FAILED/CANCELLED Live (incl. peer): parent NOTE + lineage. Returns beat or None."""

    if not is_failed_status(status):
        return None
    channel_id = str(getattr(intake, "channel_id", "") or "").strip()
    if not channel_id:
        return None
    meta = dict(getattr(intake, "metadata", None) or {})
    if not isinstance(meta, dict):
        meta = {}
    peer = bool(meta.get("peer_task") or meta.get("handoff_id") or meta.get("meat_proxy_cut"))
    parent_thread = str(
        meta.get("parent_thread_id") or getattr(intake, "thread_id", None) or ""
    ).strip()
    st = status.value if hasattr(status, "value") else str(status or "failed")
    diag = (error or "").strip() or (summary or "").strip()
    beat = format_recovery_beat(
        diagnostic=diag,
        job_code=job_code,
        status=str(st),
        peer=peer,
    )
    # Discord NOTE on parent thread (or channel) — quiet, once per settle.
    try:
        send = getattr(discord, "send_message", None) if discord is not None else None
        if callable(send):
            send(channel_id, beat, thread_id=parent_thread or None)
    except Exception:
        pass
    try:
        from agent_discord.orchestration.lineage import record_node

        record_node(
            store,
            run_id=run_id,
            task_id=task_id,
            step="recovery_beat",
            body=beat,
            status="complete",
        )
    except Exception:
        pass
    try:
        appender = getattr(store, "append_event", None)
        if callable(appender):
            appender(
                task_id=task_id,
                run_id=run_id,
                kind=EventKind.STATUS,
                summary="recovery beat",
                payload={"beat": beat[:240], "peer": peer},
                source="recovery_beat",
                provenance={"task_id": task_id, "run_id": run_id},
            )
    except Exception:
        pass
    try:
        merger = getattr(store, "merge_task_metadata", None)
        if callable(merger) and task_id:
            merger(
                task_id,
                {
                    "recovery_beat": True,
                    "recovery_diagnostic": clip_diagnostic(diag, limit=200),
                },
            )
    except Exception:
        pass
    return beat


def recovery_receipt_suffix(beat: str) -> str:
    """Append-friendly receipt line (clipped)."""

    tip = clip_diagnostic(beat, limit=220)
    return tip


__all__ = [
    "RECOVERY_ACTIONS",
    "clip_diagnostic",
    "format_recovery_beat",
    "is_failed_status",
    "maybe_post_recovery_beat",
    "recovery_receipt_suffix",
]
