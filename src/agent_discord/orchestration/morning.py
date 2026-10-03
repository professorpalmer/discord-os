"""One card on the HOST channel, once per local day, at a fixed time.

Zero setup: no schedule to write, no recipe to pick. The lines are built
deterministically from what the host already knows — overnight settles, open
Needs, the overnight pack, and the bound realms' PR / CI state from
``host.repo_status``. No model runs to produce this card.

Silent when there is nothing to report. The watermark is written whether or
not a card went out, so a quiet morning stays a quiet day and a restart at
08:00 does not post a second summary.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Sequence

from agent_discord.discord.layout import STYLE_PRIMARY, action_row, button
from agent_discord.orchestration.cards import COLOR_IDLE, CardMessage, send_card
from agent_discord.orchestration.cook_button import (
    cook_custom_id,
    cook_token,
    remember_cook_prompt,
)
from agent_discord.orchestration.overnight_pack import collect_overnight_facts

MORNING_ENV = "DISCORD_OS_MORNING"
MORNING_AT_ENV = "DISCORD_OS_MORNING_AT"
DEFAULT_MORNING_AT = "07:30"
MAX_LINES = 5
WINDOW_HOURS = 16.0
WATERMARK_KEY = "morning_posted_on"
_MAX_REPOS = 3


@dataclass(frozen=True)
class MorningLine:
    """One summary line, optionally with the obvious ask behind a button."""

    text: str
    ask: str = ""

    @property
    def token(self) -> str:
        return cook_token(self.ask)


def morning_enabled(*, env: Optional[Mapping[str, str]] = None) -> bool:
    source = os.environ if env is None else env
    raw = str(source.get(MORNING_ENV) or "").strip().lower()
    return raw not in {"0", "off", "false", "no"}


def morning_at(*, env: Optional[Mapping[str, str]] = None) -> tuple[int, int]:
    """``HH:MM`` local. A malformed value falls back to the default."""

    source = os.environ if env is None else env
    raw = str(source.get(MORNING_AT_ENV) or "").strip() or DEFAULT_MORNING_AT
    hour, _, minute = raw.partition(":")
    try:
        hh = int(hour)
        mm = int(minute or 0)
    except ValueError:
        hh, mm = 7, 30
    if not 0 <= hh <= 23 or not 0 <= mm <= 59:
        hh, mm = 7, 30
    return hh, mm


def morning_due(
    store: Any,
    *,
    channel_id: str,
    workspace_id: str = "default",
    env: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
) -> bool:
    moment = now or datetime.now()
    hour, minute = morning_at(env=env)
    if (moment.hour, moment.minute) < (hour, minute):
        return False
    return _watermark(store, channel_id, workspace_id) != moment.date().isoformat()


def mark_morning_posted(
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
            f"{WATERMARK_KEY}:{channel_id}",
            moment.date().isoformat(),
        )
    except Exception:
        return


def build_morning_lines(
    store: Any,
    *,
    channel_id: str = "",
    workspace_id: str = "default",
    repos: Sequence[Any] = (),
    repo_status: Optional[Callable[..., Any]] = None,
) -> tuple[MorningLine, ...]:
    """Red CI first, then Needs, then the quieter counts. At most five."""

    lines: list[MorningLine] = []
    for name, status in _realm_status(
        store, workspace_id=workspace_id, repos=repos, repo_status=repo_status
    ):
        lines.extend(_repo_lines(name, status))
    facts = collect_overnight_facts(
        store, channel_id="", workspace_id=workspace_id
    )
    settled = _settled(store)
    failed = int(settled.get("failed") or 0)
    done = int(settled.get("completed") or 0)
    if failed:
        lines.append(MorningLine(text=f"{failed} job(s) failed overnight"))
    needs = list(facts.get("needs") or [])
    if needs:
        lines.append(MorningLine(text=f"Needs open: {len(needs)} — {needs[0]}"))
    parks = list(facts.get("parks") or [])
    if parks:
        lines.append(MorningLine(text=f"Gate parks: {len(parks)}"))
    if done:
        lines.append(MorningLine(text=f"{done} job(s) finished overnight"))
    skipped = int(facts.get("catchup_skipped") or 0)
    if skipped:
        lines.append(MorningLine(text=f"Catch-up skipped while off: {skipped}"))
    spend = str(facts.get("spend") or "")
    if spend and spend != "spend unknown":
        lines.append(MorningLine(text=spend))
    return tuple(lines[:MAX_LINES])


def morning_card(
    lines: Sequence[MorningLine],
    *,
    workspace_id: str = "default",
    now: Optional[datetime] = None,
) -> CardMessage:
    moment = now or datetime.now()
    body = "\n".join(f"- {line.text}" for line in lines)
    rows = tuple(
        action_row(
            [
                button(
                    f"Cook: {line.text}"[:80],
                    cook_custom_id(workspace_id, line.token),
                    style=STYLE_PRIMARY,
                )
            ]
        )
        for line in lines
        if line.ask
    )
    return CardMessage(
        kind="NOTE",
        title=f"Morning · {moment.date().isoformat()}",
        description=body,
        color=COLOR_IDLE,
        rows=rows,
    )


def tick_morning_summary(
    store: Any,
    discord: Any,
    *,
    channel_id: str,
    workspace_id: str = "default",
    repos: Sequence[Any] = (),
    env: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
    repo_status: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """Called from the listen tick. Returns what it did, for tests and logs."""

    if store is None or not channel_id or not morning_enabled(env=env):
        return {"posted": False, "due": False}
    armed = getattr(store, "host_is_armed", None)
    if callable(armed):
        try:
            if not armed(channel_id):
                return {"posted": False, "due": False}
        except Exception:
            return {"posted": False, "due": False}
    if not morning_due(
        store, channel_id=channel_id, workspace_id=workspace_id, env=env, now=now
    ):
        return {"posted": False, "due": False}
    lines = build_morning_lines(
        store,
        channel_id=channel_id,
        workspace_id=workspace_id,
        repos=repos,
        repo_status=repo_status,
    )
    mark_morning_posted(
        store, channel_id=channel_id, workspace_id=workspace_id, now=now
    )
    if not lines:
        return {"posted": False, "due": True, "lines": 0}
    for line in lines:
        if line.ask:
            remember_cook_prompt(store, workspace_id, line.token, line.ask)
    posted = False
    if discord is not None:
        try:
            send_card(
                discord,
                channel_id,
                morning_card(lines, workspace_id=workspace_id, now=now),
            )
            posted = True
        except Exception:
            posted = False
    return {"posted": posted, "due": True, "lines": len(lines)}


def _repo_lines(name: str, status: Any) -> list[MorningLine]:
    from agent_discord.host.repo_status import CHECKS_RED

    out: list[MorningLine] = []
    branch = str(getattr(status, "default_branch", "") or "")
    if str(getattr(status, "default_ci", "") or "") == CHECKS_RED and branch:
        out.append(
            MorningLine(
                text=f"CI red on {name} ({branch})",
                ask=_fix_ci_ask(name, branch=branch),
            )
        )
    for row in getattr(status, "open_prs", ()) or ():
        if str(getattr(row, "checks", "") or "") != CHECKS_RED:
            continue
        out.append(
            MorningLine(
                text=f"{name}: PR #{row.number} checks red",
                ask=_fix_ci_ask(name, number=int(row.number)),
            )
        )
    prs = len(getattr(status, "open_prs", ()) or ())
    issues = int(getattr(status, "open_issue_count", 0) or 0)
    if prs or issues:
        out.append(
            MorningLine(text=f"{name}: {prs} open PR(s), {issues} open issue(s)")
        )
    return out


def _fix_ci_ask(name: str, *, branch: str = "", number: int = 0) -> str:
    where = f"PR #{number}" if number else f"the {branch} branch"
    return (
        f"Fix CI on {name}. {where} is red. Reproduce the failure locally first, "
        "fix the root cause, and keep the rest of the suite green. Do not "
        "disable or skip the check."
    )


def _realm_status(
    store: Any,
    *,
    workspace_id: str,
    repos: Sequence[Any],
    repo_status: Optional[Callable[..., Any]],
) -> list[tuple[str, Any]]:
    if repo_status is None:
        return []
    from agent_discord.host.realms import realm_for_channel

    lister = getattr(store, "list_bindings", None)
    if not callable(lister):
        return []
    try:
        rows = list(lister(workspace_id) or ())
    except Exception:
        return []
    out: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        channel = str(row.get("channel_id") or "")
        if not channel:
            continue
        try:
            realm = realm_for_channel(
                store, channel, workspace_id=workspace_id, repos=tuple(repos)
            )
        except Exception:
            realm = None
        if realm is None or realm.name in seen:
            continue
        seen.add(realm.name)
        try:
            status = repo_status(realm.path, name=realm.name)
        except Exception:
            continue
        if status is not None:
            out.append((realm.name, status))
        if len(out) >= _MAX_REPOS:
            break
    return out


def _settled(store: Any) -> dict[str, int]:
    counter = getattr(store, "count_settled_since", None)
    if not callable(counter):
        return {}
    try:
        return dict(counter(hours=WINDOW_HOURS) or {})
    except Exception:
        return {}


def _watermark(store: Any, channel_id: str, workspace_id: str) -> str:
    reader = getattr(store, "get_preference", None)
    if not callable(reader):
        return ""
    try:
        return str(reader(workspace_id or "default", f"{WATERMARK_KEY}:{channel_id}") or "")
    except Exception:
        return ""


__all__ = [
    "DEFAULT_MORNING_AT",
    "MAX_LINES",
    "MORNING_AT_ENV",
    "MORNING_ENV",
    "MorningLine",
    "build_morning_lines",
    "mark_morning_posted",
    "morning_at",
    "morning_card",
    "morning_due",
    "morning_enabled",
    "tick_morning_summary",
]
