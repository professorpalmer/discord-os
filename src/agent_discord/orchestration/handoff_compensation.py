"""SagaLLM-lite compensation NOTE for failed/cancelled handoff peers.

JobPool-only honesty: parent-thread NOTE + lineage edge. Not distributed ACID.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from agent_discord.contracts import EventKind, TaskStatus


def is_handoff_peer_intake(intake: Any) -> bool:
    meta = getattr(intake, "metadata", None) or {}
    if not isinstance(meta, Mapping):
        return False
    return bool(meta.get("peer_task") or meta.get("handoff_id") or meta.get("meat_proxy_cut"))


def compensation_note_text(
    *,
    handoff_id: str,
    status: str,
    summary: str = "",
    job_code: str = "",
) -> str:
    hid = (handoff_id or "").strip() or "?"
    st = (status or "").strip().lower() or "failed"
    code = (job_code or "").strip()
    tip = (summary or "").strip().replace("\n", " ")
    if len(tip) > 160:
        tip = tip[:157] + "..."
    bits = [f"NOTE: handoff compensation id={hid} status={st}"]
    if code:
        bits.append(f"job={code}")
    if tip:
        bits.append(tip)
    bits.append("(Saga-lite — parent notified; not a distributed saga.)")
    return " — ".join(bits)


def maybe_post_handoff_compensation(
    *,
    store: Any,
    discord: Any,
    intake: Any,
    task_id: str,
    run_id: str,
    status: Any,
    summary: str = "",
    job_code: str = "",
) -> Optional[str]:
    """On FAILED/CANCELLED peer handoff: parent NOTE + lineage. Returns note or None."""

    if not is_handoff_peer_intake(intake):
        return None
    st = status.value if hasattr(status, "value") else str(status or "")
    st_l = st.strip().lower()
    if st_l not in {
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
        "failed",
        "cancelled",
        "canceled",
    }:
        return None
    meta = dict(getattr(intake, "metadata", None) or {})
    hid = str(meta.get("handoff_id") or "").strip()
    parent_thread = str(
        meta.get("parent_thread_id") or getattr(intake, "thread_id", None) or ""
    ).strip()
    channel_id = str(getattr(intake, "channel_id", "") or "").strip()
    if not channel_id:
        return None
    note = compensation_note_text(
        handoff_id=hid,
        status=st_l,
        summary=summary,
        job_code=job_code,
    )
    # Discord NOTE on parent thread (or channel)
    try:
        send = getattr(discord, "send_message", None) if discord is not None else None
        if callable(send):
            send(channel_id, note, thread_id=parent_thread or None)
    except Exception:
        pass
    # Lineage edge
    try:
        from agent_discord.orchestration.lineage import record_node

        record_node(
            store,
            run_id=run_id,
            task_id=task_id,
            step="handoff_compensation",
            body=note,
            status="complete",
        )
    except Exception:
        pass
    # Event for ledger
    try:
        appender = getattr(store, "append_event", None)
        if callable(appender):
            appender(
                task_id=task_id,
                run_id=run_id,
                kind=EventKind.STATUS,
                summary="handoff compensation NOTE",
                payload={"handoff_id": hid, "status": st_l, "note": note[:240]},
                source="handoff_compensation",
                provenance={"task_id": task_id, "run_id": run_id},
            )
    except Exception:
        pass
    # Mark metadata
    try:
        merger = getattr(store, "merge_task_metadata", None)
        if callable(merger) and task_id:
            merger(task_id, {"handoff_compensation": True, "compensation_note": note[:240]})
    except Exception:
        pass
    return note
