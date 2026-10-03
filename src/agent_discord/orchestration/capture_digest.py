"""One card a week for the thoughts capture-first kept out of the job pool.

Captures cost nothing and make no noise, which is the point — and also why they
would be forgotten. Once a week, on the digest day at the morning hour, the
host posts the week's captures with a Cook button per line. The operator
promotes the ones that turned out to be work; the rest stay memory.

Silent when the week was quiet. The watermark is written whether or not a card
went out, so a quiet week stays quiet and a restart does not post twice.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

from agent_discord.discord.layout import STYLE_PRIMARY, action_row, button
from agent_discord.orchestration.capture import CAPTURE_SOURCE
from agent_discord.orchestration.cards import COLOR_IDLE, CardMessage, send_card
from agent_discord.orchestration.cook_button import (
    cook_custom_id,
    cook_token,
    remember_cook_prompt,
)

CAPTURE_DIGEST_DAY_ENV = "DISCORD_OS_CAPTURE_DIGEST_DAY"
DIGEST_WATERMARK_KEY = "capture_digest_week"
DEFAULT_DIGEST_DAY = "monday"
DIGEST_MAX_LINES = 5
DIGEST_WINDOW_DAYS = 7
DIGEST_LOOKUP_LIMIT = 200
LINE_CLIP = 120

DIGEST_DAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True)
class CaptureLine:
    """One captured thought, as the digest renders it."""

    text: str
    citation: str = ""

    @property
    def token(self) -> str:
        return cook_token(self.text)


def digest_day(*, env: Optional[Mapping[str, str]] = None) -> int:
    """Weekday index (Monday 0). A malformed value falls back to Monday."""

    source = os.environ if env is None else env
    raw = str(source.get(CAPTURE_DIGEST_DAY_ENV) or "").strip().lower()
    if not raw:
        raw = DEFAULT_DIGEST_DAY
    if raw in DIGEST_DAYS:
        return DIGEST_DAYS.index(raw)
    for index, name in enumerate(DIGEST_DAYS):
        if name.startswith(raw) and len(raw) >= 3:
            return index
    try:
        value = int(raw)
    except ValueError:
        return 0
    return value if 0 <= value <= 6 else 0


def week_key(moment: datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{int(week):02d}"


def digest_due(
    store: Any,
    *,
    channel_id: str,
    workspace_id: str = "default",
    env: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Once a week, on the digest day, at or after the morning hour."""

    from agent_discord.orchestration.morning import morning_at

    moment = now or datetime.now()
    if moment.weekday() != digest_day(env=env):
        return False
    hour, minute = morning_at(env=env)
    if (moment.hour, moment.minute) < (hour, minute):
        return False
    return _watermark(store, channel_id, workspace_id) != week_key(moment)


def mark_digest_posted(
    store: Any,
    *,
    channel_id: str,
    workspace_id: str = "default",
    now: Optional[datetime] = None,
) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        return
    moment = now or datetime.now()
    try:
        writer(
            workspace_id or "default",
            f"{DIGEST_WATERMARK_KEY}:{channel_id}",
            week_key(moment),
        )
    except Exception:
        return


def week_captures(
    store: Any,
    *,
    workspace_id: str = "default",
    now: Optional[datetime] = None,
    days: int = DIGEST_WINDOW_DAYS,
) -> tuple[CaptureLine, ...]:
    """Captures from the last ``days``, newest first, across every channel."""

    lister = getattr(store, "list_memory_by_source", None)
    if not callable(lister):
        return ()
    moment = (now or datetime.now()).astimezone(timezone.utc)
    since = (moment - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        rows = list(
            lister(
                workspace_id=workspace_id or "default",
                source=CAPTURE_SOURCE,
                since=since,
                limit=DIGEST_LOOKUP_LIMIT,
            )
            or ()
        )
    except Exception:
        return ()
    lines: list[CaptureLine] = []
    seen: set[str] = set()
    for row in rows:
        text = str(row.get("content") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        provenance = row.get("provenance")
        citation = ""
        if isinstance(provenance, Mapping):
            citation = str(provenance.get("citation") or "")
        lines.append(CaptureLine(text=text, citation=citation))
    return tuple(lines)


def capture_digest_card(
    lines: Sequence[CaptureLine],
    *,
    workspace_id: str = "default",
    now: Optional[datetime] = None,
) -> CardMessage:
    """At most five lines, each with its own Cook this button."""

    moment = now or datetime.now()
    shown = list(lines[:DIGEST_MAX_LINES])
    body_lines = []
    for line in shown:
        text = line.text if len(line.text) <= LINE_CLIP else line.text[: LINE_CLIP - 3] + "..."
        body_lines.append(f"- {text}" + (f" ({line.citation})" if line.citation else ""))
    extra = len(lines) - len(shown)
    if extra > 0:
        body_lines.append(f"- {extra} more in memory — discord-os recall")
    rows = tuple(
        action_row(
            [
                button(
                    f"Cook this: {line.text}"[:80],
                    cook_custom_id(workspace_id, line.token),
                    style=STYLE_PRIMARY,
                )
            ]
        )
        for line in shown
    )
    return CardMessage(
        kind="NOTE",
        title=f"Captures · week of {moment.date().isoformat()}",
        description="\n".join(body_lines),
        color=COLOR_IDLE,
        rows=rows,
    )


def tick_capture_digest(
    store: Any,
    discord: Any,
    *,
    channel_id: str,
    workspace_id: str = "default",
    env: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Called from the listen tick on the HOST channel. Silent when empty."""

    if store is None or not channel_id:
        return {"posted": False, "due": False}
    if not digest_due(
        store, channel_id=channel_id, workspace_id=workspace_id, env=env, now=now
    ):
        return {"posted": False, "due": False}
    lines = week_captures(store, workspace_id=workspace_id, now=now)
    mark_digest_posted(
        store, channel_id=channel_id, workspace_id=workspace_id, now=now
    )
    if not lines:
        return {"posted": False, "due": True, "lines": 0}
    for line in lines[:DIGEST_MAX_LINES]:
        remember_cook_prompt(store, workspace_id, line.token, line.text)
    posted = False
    if discord is not None:
        try:
            send_card(
                discord,
                channel_id,
                capture_digest_card(lines, workspace_id=workspace_id, now=now),
            )
            posted = True
        except Exception:
            posted = False
    return {"posted": posted, "due": True, "lines": len(lines)}


def _watermark(store: Any, channel_id: str, workspace_id: str) -> str:
    reader = getattr(store, "get_preference", None)
    if not callable(reader):
        return ""
    try:
        return str(
            reader(workspace_id or "default", f"{DIGEST_WATERMARK_KEY}:{channel_id}") or ""
        )
    except Exception:
        return ""


__all__ = [
    "CAPTURE_DIGEST_DAY_ENV",
    "DEFAULT_DIGEST_DAY",
    "DIGEST_DAYS",
    "DIGEST_MAX_LINES",
    "DIGEST_WINDOW_DAYS",
    "CaptureLine",
    "capture_digest_card",
    "digest_day",
    "digest_due",
    "mark_digest_posted",
    "tick_capture_digest",
    "week_captures",
    "week_key",
]
