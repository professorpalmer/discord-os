"""Puppetmaster job inbox — work the operator started elsewhere finds the phone.

Marionette, Claude Code MCP, and a bare ``puppetmaster`` shell all start jobs on
this Mac that Discord never hears about. This module observes them, posts one
live card per job into an opt-in inbox channel, and edits that same card as the
status moves.

Observe is read-only: Discord OS never cooks an observed job, so the JobPool and
HARD lock 3 are not in this path. The only writes are the three Puppetmaster
verbs an operator can ask for from the card or its thread — ``approve``,
``reject``, ``steer``. Puppetmaster 1.27.39 has no cancel verb, so there is no
Cancel button.

OFF unless a channel is named: ``discord-os add pm-inbox --channel-id ID`` or
``DISCORD_OS_PM_INBOX_CHANNEL``. See ``docs/jobs/pm-inbox.md``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from agent_discord.config import resolve_puppetmaster_cli
from agent_discord.orchestration.cards import (
    COLOR_FAIL,
    COLOR_IDLE,
    COLOR_LIVE,
    COLOR_WORK,
    CardMessage,
    edit_card,
    send_card,
)
from agent_discord.orchestration.service import HOST_PREFS_WORKSPACE
from agent_discord.puppetmaster.backend import resolved_state_dir, worker_env
from agent_discord.redaction import redact_text_markers

PM_INBOX_CHANNEL_ENV = "DISCORD_OS_PM_INBOX_CHANNEL"
# Operators whose Puppetmaster state dirs live outside the projects root.
PM_INBOX_STATE_DIRS_ENV = "DISCORD_OS_PM_INBOX_STATE_DIRS"
PM_INBOX_CHANNEL_PREF = "pm_inbox_channel"
PM_INBOX_ENABLED_PREF = "pm_inbox_enabled_ms"
PM_INBOX_TICK_PREF = "pm_inbox_tick_ms"

PM_INBOX_TICK_SECONDS = 20.0
PM_INBOX_JOB_LIMIT = 25
PM_INBOX_THREAD_READ_LIMIT = 20
GOAL_PREVIEW_MAX = 220
STEER_TEXT_MAX = 1500
CLI_TIMEOUT_SECONDS = 30

PM_INBOX_ID_PREFIX = "discord-os:pm-inbox:"
PM_INBOX_VERBS = frozenset({"approve", "reject"})

# Statuses where Puppetmaster is holding the job for a human decision.
PARKED_STATUSES = frozenset(
    {
        "parked",
        "waiting",
        "waiting_approval",
        "awaiting_approval",
        "needs_approval",
        "pending_approval",
        "blocked",
    }
)
_STATUS_COLORS = {
    "complete": COLOR_LIVE,
    "completed": COLOR_LIVE,
    "failed": COLOR_FAIL,
    "error": COLOR_FAIL,
    "running": COLOR_WORK,
}

CommandRunner = Callable[..., Any]


@dataclass(frozen=True)
class PmJob:
    """One ``job-summaries`` item, plus the state dir it was read from."""

    job_id: str
    state_dir: str
    status: str = ""
    revision: int = 0
    task_count: int = 0
    goal_preview: str = ""
    delivery: str = ""
    label: str = ""


@dataclass(frozen=True)
class PmInboxAction:
    """A parsed inbox button tap. Does not itself call Puppetmaster."""

    action: str
    job_id: str


# --- opt-in configuration -------------------------------------------------


def pm_inbox_channel_id(
    store: Any = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """The inbox channel, or "" when the feature is off."""

    source = os.environ if env is None else env
    configured = str(source.get(PM_INBOX_CHANNEL_ENV) or "").strip()
    if configured:
        return configured
    reader = getattr(store, "get_preference", None)
    if not callable(reader):
        return ""
    try:
        return str(reader(HOST_PREFS_WORKSPACE, PM_INBOX_CHANNEL_PREF) or "").strip()
    except Exception:
        return ""


def pm_inbox_enabled(
    store: Any = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    return bool(pm_inbox_channel_id(store, env=env))


def enable_pm_inbox(store: Any, channel_id: str, *, now_ms: Optional[int] = None) -> int:
    """Record the channel and the moment the inbox opened. Returns that moment.

    Jobs older than this are never carded: opening the inbox is not a request to
    replay every job this Mac has ever run.
    """

    cid = (channel_id or "").strip()
    if not cid:
        raise ValueError("pm-inbox needs a channel id")
    stamp = int(now_ms if now_ms is not None else time.time() * 1000)
    writer = getattr(store, "set_preference", None)
    if callable(writer):
        writer(HOST_PREFS_WORKSPACE, PM_INBOX_CHANNEL_PREF, cid)
        writer(HOST_PREFS_WORKSPACE, PM_INBOX_ENABLED_PREF, str(stamp))
    return stamp


def pm_inbox_enabled_ms(store: Any, *, now_ms: Optional[int] = None) -> int:
    """The enable moment, seeding it on first read (the env-only opt-in path)."""

    reader = getattr(store, "get_preference", None)
    raw = ""
    if callable(reader):
        try:
            raw = str(reader(HOST_PREFS_WORKSPACE, PM_INBOX_ENABLED_PREF) or "").strip()
        except Exception:
            raw = ""
    try:
        return int(raw)
    except ValueError:
        pass
    stamp = int(now_ms if now_ms is not None else time.time() * 1000)
    writer = getattr(store, "set_preference", None)
    if callable(writer):
        try:
            writer(HOST_PREFS_WORKSPACE, PM_INBOX_ENABLED_PREF, str(stamp))
        except Exception:
            pass
    return stamp


# --- discovery ------------------------------------------------------------


def projects_root(env: Optional[Mapping[str, str]] = None) -> Path:
    source = os.environ if env is None else env
    home = Path(str(source.get("HOME") or Path.home())).expanduser()
    return home / "Library" / "Application Support" / "puppetmaster" / "projects"


def candidate_state_dirs(
    *,
    env: Optional[Mapping[str, str]] = None,
    own_state_dir: str = "",
) -> tuple[str, ...]:
    """Puppetmaster state dirs other tools on this Mac write to.

    Marionette and the Claude Code MCP server each get a per-project dir under
    ``~/Library/Application Support/puppetmaster/projects``; a bare CLI run uses
    ``~/.puppetmaster``. Those two roots are what we walk. A state dir anywhere
    else has to be named in ``DISCORD_OS_PM_INBOX_STATE_DIRS`` — we do not scan
    the disk looking for one.

    Discord OS's own state dir is dropped: those jobs already have job cards.
    """

    source = os.environ if env is None else env
    mine = _real(own_state_dir or resolved_state_dir(source))
    found: list[str] = []
    seen: set[str] = set()

    def offer(path: Path) -> None:
        if not path.is_dir():
            return
        real = _real(str(path))
        if not real or real == mine or real in seen:
            return
        seen.add(real)
        found.append(str(path))

    for raw in str(source.get(PM_INBOX_STATE_DIRS_ENV) or "").split(","):
        text = raw.strip()
        if text:
            offer(Path(text).expanduser())
    home = Path(str(source.get("HOME") or Path.home())).expanduser()
    offer(home / ".puppetmaster")
    root = projects_root(source)
    if root.is_dir():
        try:
            children = sorted(root.iterdir())
        except OSError:
            children = []
        for child in children:
            offer(child)
    return tuple(found)


def _real(path: str) -> str:
    text = (path or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except OSError:
        return str(Path(text).expanduser())


def read_pm_jobs(
    state_dir: str,
    *,
    runner: Optional[CommandRunner] = None,
    env: Optional[Mapping[str, str]] = None,
    limit: int = PM_INBOX_JOB_LIMIT,
) -> tuple[PmJob, ...]:
    """``puppetmaster --state-dir DIR job-summaries --json``. Never raises.

    A dir Puppetmaster rejects just yields nothing, so a wrong guess about the
    layout is quiet rather than fatal.
    """

    payload = _pm_json(
        ["job-summaries", "--json", "--limit", str(int(limit))],
        state_dir=state_dir,
        runner=runner,
        env=env,
    )
    if not isinstance(payload, dict):
        return ()
    items = payload.get("items")
    jobs: list[PmJob] = []
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        job_id = str(item.get("id") or "").strip()
        if not job_id:
            continue
        jobs.append(
            PmJob(
                job_id=job_id,
                state_dir=state_dir,
                status=str(item.get("status") or "").strip(),
                revision=_as_int(item.get("revision")),
                task_count=_as_int(item.get("task_count")),
                goal_preview=str(item.get("goal_preview") or ""),
                delivery=str(item.get("delivery") or "").strip(),
            )
        )
    return tuple(jobs)


def pm_job_detail(
    job_id: str,
    *,
    state_dir: str,
    runner: Optional[CommandRunner] = None,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """``puppetmaster status <job_id> --compact``. ``{}`` when unreadable.

    ``job-summaries`` has no created_at, so this is how a job is dated against
    the moment the inbox opened. It also carries the human label.
    """

    payload = _pm_json(
        ["status", job_id, "--compact"],
        state_dir=state_dir,
        runner=runner,
        env=env,
    )
    if not isinstance(payload, dict):
        return {}
    job = payload.get("job")
    return dict(job) if isinstance(job, dict) else {}


def created_ms_from_detail(detail: Mapping[str, Any]) -> Optional[int]:
    """Epoch ms for a job's ``created_at``, or None when it cannot be read."""

    raw = str((detail or {}).get("created_at") or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            return int(float(raw) * 1000)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _pm_json(
    argv: Sequence[str],
    *,
    state_dir: str,
    runner: Optional[CommandRunner],
    env: Optional[Mapping[str, str]],
) -> Any:
    proc = _pm_run(argv, state_dir=state_dir, runner=runner, env=env)
    if proc is None:
        return None
    try:
        return json.loads(getattr(proc, "stdout", "") or "")
    except (json.JSONDecodeError, TypeError):
        return None


def _pm_run(
    argv: Sequence[str],
    *,
    state_dir: str,
    runner: Optional[CommandRunner],
    env: Optional[Mapping[str, str]],
) -> Any:
    """One PM subprocess. Returns the completed process, or None on any failure."""

    cli = resolve_puppetmaster_cli()
    command = [cli]
    if (state_dir or "").strip():
        # Global flags go before the verb in 1.27.39.
        command.extend(["--state-dir", str(state_dir)])
    command.extend(str(part) for part in argv)
    run = runner
    if run is None:
        import subprocess

        run = subprocess.run
    try:
        proc = run(
            command,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_SECONDS,
            env=worker_env(env),
        )
    except Exception:
        return None
    if getattr(proc, "returncode", 1) not in {0, None}:
        return None
    return proc


def run_pm_verb(
    verb: str,
    job_id: str,
    *,
    state_dir: str,
    message: str = "",
    runner: Optional[CommandRunner] = None,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """``approve`` / ``reject`` / ``steer`` one observed job. Never raises."""

    action = (verb or "").strip().lower()
    jid = (job_id or "").strip()
    if not jid:
        return False
    if action == "steer":
        body = (message or "").strip()[:STEER_TEXT_MAX]
        if not body:
            return False
        argv = ["steer", jid, body]
    elif action == "reject":
        argv = ["reject", jid]
    elif action == "approve":
        argv = ["approve", jid]
    else:
        return False
    return _pm_run(argv, state_dir=state_dir, runner=runner, env=env) is not None


# --- card -----------------------------------------------------------------


def job_is_parked(status: str) -> bool:
    return (status or "").strip().lower() in PARKED_STATUSES


def pm_inbox_custom_id(action: str, job_id: str) -> str:
    from agent_discord.discord.layout import CUSTOM_ID_MAX

    verb = (action or "").strip().lower()
    prefix = f"{PM_INBOX_ID_PREFIX}{verb}:"
    budget = max(0, CUSTOM_ID_MAX - len(prefix))
    return prefix + (job_id or "").strip()[:budget]


def pm_inbox_action_from_custom_id(custom_id: str) -> Optional[PmInboxAction]:
    raw = (custom_id or "").strip()
    if not raw.startswith(PM_INBOX_ID_PREFIX):
        return None
    verb, sep, job_id = raw[len(PM_INBOX_ID_PREFIX) :].partition(":")
    verb = verb.strip().lower()
    job_id = job_id.strip()
    if not sep or verb not in PM_INBOX_VERBS or not job_id:
        return None
    return PmInboxAction(action=verb, job_id=job_id)


def pm_job_card(job: PmJob) -> CardMessage:
    """One live card for one observed job. Edited in place on every change."""

    status = (job.status or "unknown").strip() or "unknown"
    label = redact_text_markers((job.label or "").strip())[:120]
    goal = redact_text_markers(" ".join((job.goal_preview or "").split()))
    if len(goal) > GOAL_PREVIEW_MAX:
        goal = goal[: GOAL_PREVIEW_MAX - 3] + "..."
    fields: list[tuple[str, str, bool]] = [
        ("Status", status, True),
        ("Tasks", str(job.task_count), True),
    ]
    if job.delivery:
        fields.append(("Delivery", job.delivery, True))
    fields.append(("Job", f"`{job.job_id}`", False))
    return CardMessage(
        kind="NOTE",
        title=label or f"Puppetmaster {job.job_id}",
        description=goal or "No goal preview.",
        color=_STATUS_COLORS.get(status.lower(), COLOR_IDLE),
        fields=tuple(fields),
        chrome="Need" if job_is_parked(status) else "",
    )


def pm_job_rows(job: PmJob) -> list[dict[str, Any]]:
    """Approve / Reject while parked. No Cancel — Puppetmaster has no such verb."""

    if not job_is_parked(job.status):
        return []
    from agent_discord.discord.layout import (
        STYLE_DANGER,
        STYLE_SUCCESS,
        action_row,
        button,
    )

    return [
        action_row(
            [
                button(
                    "Approve",
                    pm_inbox_custom_id("approve", job.job_id),
                    style=STYLE_SUCCESS,
                ),
                button(
                    "Reject",
                    pm_inbox_custom_id("reject", job.job_id),
                    style=STYLE_DANGER,
                ),
            ]
        )
    ]


# --- observe tick ---------------------------------------------------------


def tick_pm_inbox(
    discord: Any,
    store: Any,
    *,
    env: Optional[Mapping[str, str]] = None,
    runner: Optional[CommandRunner] = None,
    now: Optional[float] = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """One rate-limited observe pass. Best-effort: never raises into the loop.

    Returns one dict per card touched, for tests and logs.
    """

    try:
        return _tick(
            discord, store, env=env, runner=runner, now=now, force=force
        )
    except Exception:
        return []


def _tick(
    discord: Any,
    store: Any,
    *,
    env: Optional[Mapping[str, str]],
    runner: Optional[CommandRunner],
    now: Optional[float],
    force: bool,
) -> list[dict[str, Any]]:
    channel_id = pm_inbox_channel_id(store, env=env)
    if not channel_id or store is None or discord is None:
        return []
    now_ms = int((now if now is not None else time.time()) * 1000)
    if not force and not _claim_tick(store, now_ms):
        return []
    enabled_ms = pm_inbox_enabled_ms(store, now_ms=now_ms)
    touched: list[dict[str, Any]] = []
    for state_dir in candidate_state_dirs(env=env):
        for job in read_pm_jobs(state_dir, runner=runner, env=env):
            result = _apply_job(
                discord,
                store,
                job,
                channel_id=channel_id,
                enabled_ms=enabled_ms,
                runner=runner,
                env=env,
            )
            if result is not None:
                touched.append(result)
    touched.extend(
        _drain_job_threads(discord, store, runner=runner, env=env)
    )
    return touched


def _claim_tick(store: Any, now_ms: int) -> bool:
    reader = getattr(store, "get_preference", None)
    writer = getattr(store, "set_preference", None)
    if not callable(reader) or not callable(writer):
        return True
    try:
        last = int(str(reader(HOST_PREFS_WORKSPACE, PM_INBOX_TICK_PREF) or "0") or 0)
    except (TypeError, ValueError):
        last = 0
    if now_ms - last < int(PM_INBOX_TICK_SECONDS * 1000):
        return False
    try:
        writer(HOST_PREFS_WORKSPACE, PM_INBOX_TICK_PREF, str(now_ms))
    except Exception:
        return True
    return True


def _apply_job(
    discord: Any,
    store: Any,
    job: PmJob,
    *,
    channel_id: str,
    enabled_ms: int,
    runner: Optional[CommandRunner],
    env: Optional[Mapping[str, str]],
) -> Optional[dict[str, Any]]:
    known = store.get_pm_inbox_job(job.job_id)
    if known is None:
        detail = pm_job_detail(
            job.job_id, state_dir=job.state_dir, runner=runner, env=env
        )
        created_ms = created_ms_from_detail(detail)
        if created_ms is not None and created_ms < enabled_ms:
            return None
        return _post_job(
            discord,
            store,
            PmJob(
                job_id=job.job_id,
                state_dir=job.state_dir,
                status=str(detail.get("status") or job.status),
                revision=job.revision,
                task_count=job.task_count,
                goal_preview=job.goal_preview,
                delivery=job.delivery,
                label=str(detail.get("label") or ""),
            ),
            channel_id=channel_id,
        )
    if str(known.get("status") or "") == job.status and int(
        known.get("revision") or 0
    ) == job.revision:
        return None
    return _edit_job(discord, store, job, known=known)


def _post_job(
    discord: Any,
    store: Any,
    job: PmJob,
    *,
    channel_id: str,
) -> Optional[dict[str, Any]]:
    card = pm_job_card(job)
    try:
        posted = send_card(discord, channel_id, card, components=pm_job_rows(job))
    except Exception:
        return None
    message_id = _posted_message_id(posted)
    if not message_id:
        return None
    thread_id = _open_thread(discord, channel_id, message_id, card.title)
    store.record_pm_inbox_job(
        job.job_id,
        state_dir=job.state_dir,
        channel_id=channel_id,
        thread_id=thread_id,
        message_id=message_id,
        status=job.status,
        revision=job.revision,
        task_count=job.task_count,
        label=job.label,
        goal_preview=job.goal_preview,
        # The card is the thread's starter, so every reply sorts after it. An
        # anchor from creation is what keeps the first reply steerable.
        steer_after=message_id,
    )
    return {
        "job_id": job.job_id,
        "action": "posted",
        "message_id": message_id,
        "thread_id": thread_id,
    }


def _edit_job(
    discord: Any,
    store: Any,
    job: PmJob,
    *,
    known: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    channel_id = str(known.get("channel_id") or "")
    message_id = str(known.get("message_id") or "")
    thread_id = str(known.get("thread_id") or "")
    # The card lives in the thread's starter message, so edits go to the thread.
    dest = thread_id or channel_id
    label = str(known.get("label") or "")
    live = PmJob(
        job_id=job.job_id,
        state_dir=job.state_dir or str(known.get("state_dir") or ""),
        status=job.status,
        revision=job.revision,
        task_count=job.task_count,
        goal_preview=job.goal_preview or str(known.get("goal_preview") or ""),
        delivery=job.delivery,
        label=label,
    )
    card = pm_job_card(live)
    edited = False
    if dest and message_id:
        try:
            edit_card(
                discord,
                channel_id or dest,
                message_id,
                card,
                components=pm_job_rows(live),
            )
            edited = True
        except Exception:
            edited = False
    store.record_pm_inbox_job(
        job.job_id,
        state_dir=live.state_dir,
        channel_id=channel_id,
        thread_id=thread_id,
        message_id=message_id,
        status=job.status,
        revision=job.revision,
        task_count=job.task_count,
        label=label,
        goal_preview=live.goal_preview,
        steer_after=str(known.get("steer_after") or ""),
    )
    return {"job_id": job.job_id, "action": "edited" if edited else "noted"}


def _open_thread(discord: Any, channel_id: str, message_id: str, name: str) -> str:
    opener = getattr(discord, "start_thread_from_message", None)
    if not callable(opener):
        return ""
    try:
        return str(opener(channel_id, message_id, (name or "job")[:100]) or "")
    except Exception:
        return ""


def _posted_message_id(posted: Any) -> str:
    if posted is None:
        return ""
    if isinstance(posted, list) and posted:
        return str(getattr(posted[-1], "message_id", "") or "")
    return str(getattr(posted, "message_id", "") or "")


# --- steer by thread reply ------------------------------------------------


def _drain_job_threads(
    discord: Any,
    store: Any,
    *,
    runner: Optional[CommandRunner],
    env: Optional[Mapping[str, str]],
) -> list[dict[str, Any]]:
    """An operator reply in a job's thread becomes ``puppetmaster steer``.

    These threads are deliberately not listen destinations: a reply here steers
    the observed Puppetmaster job, and must never mint a Discord OS cook.
    """

    try:
        rows = list(store.list_pm_inbox_jobs())
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        result = _drain_one_thread(
            discord, store, row, runner=runner, env=env
        )
        out.extend(result)
    return out


def _drain_one_thread(
    discord: Any,
    store: Any,
    row: Mapping[str, Any],
    *,
    runner: Optional[CommandRunner],
    env: Optional[Mapping[str, str]],
) -> list[dict[str, Any]]:
    from agent_discord.orchestration.listen import should_dispatch_inbound
    from agent_discord.orchestration.service import author_may_operate

    thread_id = str(row.get("thread_id") or "").strip()
    if not thread_id:
        return []
    channel_id = str(row.get("channel_id") or "").strip()
    job_id = str(row.get("job_id") or "").strip()
    anchor = str(row.get("steer_after") or "").strip()
    try:
        messages = list(
            discord.read_messages(
                channel_id or thread_id,
                limit=PM_INBOX_THREAD_READ_LIMIT,
                thread_id=thread_id,
                after=anchor or None,
                skip_duplicates=False,
            )
        )
    except Exception:
        return []
    newest = anchor
    for message in messages:
        mid = str(getattr(message, "message_id", "") or "")
        if mid and _id_after(mid, newest):
            newest = mid
    out: list[dict[str, Any]] = []
    # No anchor means this row never carried one: seed it rather than treating
    # whatever is already in the thread as a steer queue.
    if anchor:
        for message in messages:
            mid = str(getattr(message, "message_id", "") or "")
            if not mid or not _id_after(mid, anchor):
                continue
            if not should_dispatch_inbound(message):
                continue
            author = str(getattr(message, "author_id", "") or "")
            if not author_may_operate(
                store, author, "pm-steer", role_ids=_role_ids(message)
            ):
                continue
            if not store.claim_inbound_message(mid, thread_id):
                continue
            ok = run_pm_verb(
                "steer",
                job_id,
                state_dir=str(row.get("state_dir") or ""),
                message=str(getattr(message, "content", "") or ""),
                runner=runner,
                env=env,
            )
            _speak(
                discord,
                channel_id or thread_id,
                thread_id,
                f"Steered `{job_id}`." if ok else f"Could not steer `{job_id}`.",
            )
            out.append({"job_id": job_id, "action": "steer", "ok": ok})
    if newest != anchor:
        store.record_pm_inbox_job(
            job_id,
            state_dir=str(row.get("state_dir") or ""),
            channel_id=channel_id,
            thread_id=thread_id,
            message_id=str(row.get("message_id") or ""),
            status=str(row.get("status") or ""),
            revision=int(row.get("revision") or 0),
            task_count=int(row.get("task_count") or 0),
            label=str(row.get("label") or ""),
            goal_preview=str(row.get("goal_preview") or ""),
            steer_after=newest,
        )
    return out


def _id_after(message_id: str, previous: str) -> bool:
    if not previous:
        return bool(message_id)
    if message_id == previous:
        return False
    try:
        return int(message_id) > int(previous)
    except (TypeError, ValueError):
        return message_id != previous


def _role_ids(message: Any) -> list[str]:
    meta = getattr(message, "metadata", None)
    if not isinstance(meta, dict):
        return []
    raw = meta.get("role_ids") or meta.get("roles") or []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _speak(discord: Any, channel_id: str, thread_id: str, body: str) -> None:
    try:
        send = getattr(discord, "send_message", None)
        if callable(send):
            send(channel_id, body, thread_id=thread_id or None)
    except Exception:
        pass


# --- button clicks --------------------------------------------------------


def handle_pm_inbox_click(
    store: Any,
    payload: Mapping[str, Any],
    *,
    action: Optional[PmInboxAction] = None,
    opener: Any = None,
    runner: Optional[CommandRunner] = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Approve / Reject an observed job. Operators only; best-effort CLI."""

    from agent_discord.host.panel import (
        CALLBACK_DEFERRED_UPDATE,
        _operator_may_click,
        interaction_ids,
    )

    parsed = action
    if parsed is None:
        data = payload.get("data")
        custom_id = str(data.get("custom_id") or "") if isinstance(data, dict) else ""
        parsed = pm_inbox_action_from_custom_id(custom_id)
    if parsed is None:
        return ""
    if not _operator_may_click(store, payload, f"pm-{parsed.action}", opener=opener):
        return "denied"
    interaction_id, ix_token = interaction_ids(payload)
    if interaction_id and ix_token:
        try:
            from agent_discord.discord.rest import callback_interaction

            callback_interaction(
                interaction_id=interaction_id,
                interaction_token=ix_token,
                payload={"type": CALLBACK_DEFERRED_UPDATE},
                opener=opener,
            )
        except Exception:
            pass
    try:
        row = store.get_pm_inbox_job(parsed.job_id) or {}
    except Exception:
        row = {}
    run_pm_verb(
        parsed.action,
        parsed.job_id,
        state_dir=str(row.get("state_dir") or ""),
        runner=runner,
        env=env,
    )
    return f"pm-{parsed.action}"


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
