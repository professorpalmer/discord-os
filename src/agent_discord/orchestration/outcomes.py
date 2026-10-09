"""Operator reactions on a settled card become a labeled outcome for that run.

Reactions are read over REST on a throttled listen tick, not the Gateway: the
one Gateway this product opens exists so On/Off buttons work (lock 4), and a
reaction event would need a second intent and a second socket. So the host asks
Discord "who reacted to this Done card" for the runs that settled recently, and
writes one label per operator per run into SQLite.

Three labels. Thumbs up is good, thumbs down is bad, shrug is partial — a run
that answered part of the ask. Anyone who is not an operator is ignored, and so
is the bot's own reaction.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

LABEL_GOOD = "good"
LABEL_BAD = "bad"
LABEL_PARTIAL = "partial"

OUTCOME_LABELS = (LABEL_GOOD, LABEL_PARTIAL, LABEL_BAD)

# Discord reactions are the input surface here, so these are emoji by design.
OUTCOME_EMOJI: dict[str, str] = {
    "\U0001F44D": LABEL_GOOD,
    "\U0001F44E": LABEL_BAD,
    "\U0001F937": LABEL_PARTIAL,
}

OUTCOME_WINDOW_DAYS = 7
_MAX_CARDS_PER_TICK = 25


def label_for_emoji(emoji: str) -> str:
    return OUTCOME_EMOJI.get((emoji or "").strip(), "")


def collect_outcomes(
    store: Any,
    discord: Any,
    *,
    days: int = OUTCOME_WINDOW_DAYS,
    limit: int = _MAX_CARDS_PER_TICK,
    env: Optional[Mapping[str, str]] = None,
) -> list[dict[str, Any]]:
    """One pass over recently settled cards. Returns the outcomes it stored."""

    if store is None or discord is None:
        return []
    lister = getattr(store, "list_settled_cards", None)
    reader = getattr(discord, "list_reactions", None)
    writer = getattr(store, "record_run_outcome", None)
    if not callable(lister) or not callable(reader) or not callable(writer):
        return []
    try:
        cards = list(lister(days=days, limit=limit) or ())
    except Exception:
        return []
    stored: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, Mapping):
            continue
        run_id = str(card.get("run_id") or "").strip()
        channel_id = str(card.get("card_channel_id") or "").strip()
        message_id = str(card.get("card_message_id") or "").strip()
        if not run_id or not channel_id or not message_id:
            continue
        for emoji, label in OUTCOME_EMOJI.items():
            try:
                users = list(reader(channel_id, message_id, emoji) or ())
            except Exception:
                continue
            for user in users:
                operator_id = _operator_id(store, user, env=env)
                if not operator_id:
                    continue
                try:
                    changed = bool(
                        writer(run_id=run_id, operator_id=operator_id, label=label)
                    )
                except Exception:
                    continue
                if changed:
                    stored.append(
                        {"run_id": run_id, "operator_id": operator_id, "label": label}
                    )
    return stored


def _operator_id(
    store: Any,
    user: Any,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """The reacting operator's id, or empty when the reaction does not count."""

    if not isinstance(user, Mapping):
        return ""
    if bool(user.get("bot")):
        return ""
    uid = str(user.get("id") or "").strip()
    if not uid:
        return ""
    from agent_discord.orchestration.service import author_may_operate

    try:
        allowed = author_may_operate(store, uid, "outcome", env=env)
    except Exception:
        return ""
    return uid if allowed else ""


def format_outcome_tally(tally: Mapping[str, int], *, days: int = OUTCOME_WINDOW_DAYS) -> str:
    """One line for the HOST card. Empty when nothing is labeled."""

    parts = [
        f"{int(tally.get(label) or 0)} {label}"
        for label in OUTCOME_LABELS
        if int(tally.get(label) or 0) > 0
    ]
    if not parts:
        return ""
    return f"Outcomes {int(days)}d: " + ", ".join(parts)


def outcome_tally_line(
    store: Any,
    *,
    days: int = OUTCOME_WINDOW_DAYS,
) -> str:
    reader = getattr(store, "outcome_tally", None)
    if not callable(reader):
        return ""
    try:
        tally = reader(days=days) or {}
    except Exception:
        return ""
    return format_outcome_tally(tally, days=days)


def format_run_outcomes(rows: Sequence[Mapping[str, Any]]) -> str:
    """``discord-os lineage`` line: who labeled this run and how."""

    parts: list[str] = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("label") or "").strip()
        operator = str(row.get("operator_id") or "").strip()
        if not label:
            continue
        parts.append(f"{label} by {operator}" if operator else label)
    return ", ".join(parts)


__all__ = [
    "LABEL_BAD",
    "LABEL_GOOD",
    "LABEL_PARTIAL",
    "OUTCOME_EMOJI",
    "OUTCOME_LABELS",
    "OUTCOME_WINDOW_DAYS",
    "collect_outcomes",
    "format_outcome_tally",
    "format_run_outcomes",
    "label_for_emoji",
    "outcome_tally_line",
]
