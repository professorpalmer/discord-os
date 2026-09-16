"""Overnight brief structured pack (Wave 6 P1c).

Schedule prompts tagged ``overnight brief:`` / recipe inject open Needs (≤5),
Live (≤5), gate parks, spend snapshot, Catch-up skipped count — then **one**
JobPool ask. Off → still one Catch-up (existing listen path), no storm.
No mailbox / CRHQ fleet.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

_OVERNIGHT_PREFIXES = (
    "overnight brief:",
    "overnight brief",
    "[overnight-brief]",
    "overnight-brief:",
)


def is_overnight_brief_prompt(prompt: str) -> bool:
    raw = (prompt or "").strip().lower()
    if not raw:
        return False
    return any(raw.startswith(p) or p in raw[:48] for p in _OVERNIGHT_PREFIXES)


def _job_code(row: Mapping[str, Any]) -> str:
    return str(row.get("job_code") or row.get("task_id") or "").strip() or "?"


def _status(row: Mapping[str, Any]) -> str:
    return str(row.get("status") or "").strip().lower()


def _clip(text: str, limit: int = 72) -> str:
    body = " ".join((text or "").strip().split())
    if len(body) <= limit:
        return body
    return body[: max(0, limit - 1)].rstrip() + "…"


def _list_jobs(store: Any, channel_id: str, *, limit: int = 40) -> list[dict[str, Any]]:
    if store is None:
        return []
    lister = getattr(store, "list_recent_jobs", None)
    if not callable(lister):
        return []
    try:
        rows = list(lister(channel_id or "", limit=limit) or [])
    except Exception:
        return []
    return [r for r in rows if isinstance(r, Mapping)]


_NEED_STATUSES = frozenset(
    {
        "pending",
        "parked",
        "waiting",
        "waiting_approval",
        "failed",
        "need",
    }
)
_LIVE_STATUSES = frozenset({"running", "progress", "queued"})
_PARK_HINTS = ("gate", "allow", "deny", "park", "approval", "write")


def collect_overnight_facts(
    store: Any,
    *,
    channel_id: str = "",
    workspace_id: str = "default",
    needs_limit: int = 5,
    live_limit: int = 5,
) -> dict[str, Any]:
    """Structured context for the overnight brief inject."""

    jobs = _list_jobs(store, channel_id)
    needs: list[str] = []
    live: list[str] = []
    parks: list[str] = []
    for row in jobs:
        st = _status(row)
        code = _job_code(row)
        summary = _clip(str(row.get("summary") or row.get("intake_text") or ""))
        line = f"{code}:{st}" + (f" {_clip(summary, 40)}" if summary else "")
        if st in _NEED_STATUSES and len(needs) < needs_limit:
            needs.append(line)
        if st in _LIVE_STATUSES and len(live) < live_limit:
            live.append(line)
        blob = f"{summary} {row.get('attention') or ''} {st}".lower()
        if any(h in blob for h in _PARK_HINTS) and st in _NEED_STATUSES:
            if line not in parks and len(parks) < 5:
                parks.append(line)

    spend = _spend_snapshot(store, workspace_id=workspace_id)
    skipped = _catchup_skipped_count(store, workspace_id=workspace_id, channel_id=channel_id)
    return {
        "needs": needs,
        "live": live,
        "parks": parks,
        "spend": spend,
        "catchup_skipped": skipped,
    }


def _spend_snapshot(store: Any, *, workspace_id: str) -> str:
    if store is None:
        return "spend unknown"
    try:
        from agent_discord.orchestration.receipts import format_spend

        # Prefer host spend helpers when present.
    except Exception:
        format_spend = None  # type: ignore
    reader = getattr(store, "get_preference", None)
    spent = None
    known = False
    halted = False
    if callable(reader):
        for key in ("spend_usd", "session_spend_usd", "openrouter_spend_usd"):
            try:
                raw = reader(workspace_id or "default", key)
            except Exception:
                raw = None
            if raw is None:
                continue
            try:
                spent = float(raw)
                known = True
                break
            except (TypeError, ValueError):
                continue
        try:
            halted = bool(reader(workspace_id or "default", "spend_halted"))
        except Exception:
            halted = False
    # Fallback: dashboard-ish spend via optional helper
    if not known:
        snapper = getattr(store, "spend_snapshot", None)
        if callable(snapper):
            try:
                snap = snapper(workspace_id) or {}
                if isinstance(snap, Mapping):
                    if snap.get("spend_known"):
                        known = True
                        spent = snap.get("spend_usd")
                    halted = bool(snap.get("halted"))
            except Exception:
                pass
    if not known:
        base = "spend unknown"
    else:
        try:
            base = f"spend ${float(spent):.4f}"
        except (TypeError, ValueError):
            base = "spend unknown"
    if halted:
        base += " · halted"
    return base


def _catchup_skipped_count(
    store: Any, *, workspace_id: str, channel_id: str
) -> int:
    if store is None:
        return 0
    reader = getattr(store, "get_preference", None)
    if not callable(reader):
        return 0
    for key in (
        f"catchup_skipped:{channel_id}",
        "catchup_skipped_count",
        "skipped_while_disarmed_count",
    ):
        try:
            raw = reader(workspace_id or "default", key)
        except Exception:
            raw = None
        if raw is None:
            continue
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            continue
    # Count enabled schedules that look overdue markers if exposed.
    lister = getattr(store, "list_schedules", None)
    if callable(lister):
        try:
            rows = list(lister(channel_id=channel_id) or lister() or [])
        except TypeError:
            try:
                rows = list(lister() or [])
            except Exception:
                rows = []
        except Exception:
            rows = []
        n = 0
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if str(row.get("channel_id") or "") not in {"", channel_id}:
                if channel_id and str(row.get("channel_id") or "") != channel_id:
                    continue
            if row.get("skipped_while_disarmed"):
                n += 1
        return n
    return 0


def format_overnight_pack(facts: Mapping[str, Any]) -> str:
    """Spoken structured inject block."""

    lines = ["[overnight-brief-pack]"]
    needs = list(facts.get("needs") or [])
    live = list(facts.get("live") or [])
    parks = list(facts.get("parks") or [])
    lines.append("Needs:" + (" none" if not needs else ""))
    for item in needs:
        lines.append(f"- {item}")
    lines.append("Live:" + (" none" if not live else ""))
    for item in live:
        lines.append(f"- {item}")
    lines.append("Gate parks:" + (" none" if not parks else ""))
    for item in parks:
        lines.append(f"- {item}")
    lines.append(str(facts.get("spend") or "spend unknown"))
    skipped = int(facts.get("catchup_skipped") or 0)
    lines.append(f"Catch-up skipped: {skipped}")
    lines.append(
        "Honest limit: one JobPool ask — Off still one Catch-up, no storm."
    )
    return "\n".join(lines)


def compose_overnight_brief_ask(
    prompt: str,
    *,
    store: Any = None,
    channel_id: str = "",
    workspace_id: str = "default",
) -> str:
    """Inject structured pack, then keep the human/schedule ask as one cook."""

    facts = collect_overnight_facts(
        store, channel_id=channel_id, workspace_id=workspace_id
    )
    pack = format_overnight_pack(facts)
    body = (prompt or "").strip()
    return f"{pack}\n\n{body}".strip()


__all__ = [
    "collect_overnight_facts",
    "compose_overnight_brief_ask",
    "format_overnight_pack",
    "is_overnight_brief_prompt",
]
