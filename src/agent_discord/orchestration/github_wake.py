"""PR / CI wake into the owning job thread.

GitHub auth stays in host.github. This module owns subscribe-shaped follow-up:
bound PRs, check conclusions, human review comments. Poll from the listen
loop. Not a webhook server, not a PR inbox, not a second board.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from agent_discord.orchestration.cards import github_wake_card, send_card
from agent_discord.orchestration.job_briefing import ATTENTION_NEED, ATTENTION_WAITING
from agent_discord.orchestration.lineage import list_nodes, record_node, tip_key

KIND_CHECK_FAILED = "check_failed"
KIND_CHECKS_GREEN = "checks_green"
KIND_REVIEW = "review"
KIND_MERGED = "merged"

_FAIL_CONCLUSIONS = frozenset({"failure", "cancelled", "timed_out", "action_required"})
_PR_URL = re.compile(
    r"https?://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)",
    re.IGNORECASE,
)
_BOT_LOGIN_RE = re.compile(r"\[bot\]$", re.IGNORECASE)


@dataclass(frozen=True)
class CheckItem:
    name: str
    status: str
    conclusion: str = ""


@dataclass(frozen=True)
class ReviewNote:
    comment_id: str
    author: str
    body: str
    is_bot: bool


@dataclass(frozen=True)
class PullSnapshot:
    repo: str
    number: int
    merged: bool = False
    checks: tuple[CheckItem, ...] = ()
    reviews: tuple[ReviewNote, ...] = ()
    branch: str = ""
    base: str = ""


@dataclass(frozen=True)
class WakeEvent:
    kind: str
    event_id: str
    summary: str
    attention: str


Snapshotter = Callable[[str, int], Optional[PullSnapshot]]


def parse_pull_url(text: str) -> Optional[tuple[str, int]]:
    match = _PR_URL.search(text or "")
    if not match:
        return None
    repo = f"{match.group(1)}/{match.group(2)}"
    return repo, int(match.group(3))


def is_bot_author(author: str, *, allowlisted: Sequence[str] = ()) -> bool:
    login = (author or "").strip()
    if not login:
        return False
    allowed = {item.strip().lower() for item in allowlisted if str(item).strip()}
    if login.lower() in allowed:
        return False
    return bool(_BOT_LOGIN_RE.search(login)) or login.lower() in {"github-actions[bot]", "github-actions"}


def wake_events(
    snapshot: PullSnapshot,
    *,
    allowlisted_bots: Sequence[str] = (),
) -> tuple[WakeEvent, ...]:
    events: list[WakeEvent] = []
    failed = [
        item
        for item in snapshot.checks
        if str(item.status).lower() == "completed"
        and str(item.conclusion or "").lower() in _FAIL_CONCLUSIONS
    ]
    pending = [
        item
        for item in snapshot.checks
        if str(item.status).lower() in {"queued", "in_progress", "pending"}
    ]
    completed = [
        item for item in snapshot.checks if str(item.status).lower() == "completed"
    ]
    if failed:
        names = ", ".join(item.name or "check" for item in failed[:4])
        events.append(
            WakeEvent(
                kind=KIND_CHECK_FAILED,
                event_id=f"check-fail:{snapshot.repo}#{snapshot.number}:{failed[0].name}:{failed[0].conclusion}",
                summary=f"PR #{snapshot.number} failed: {names}",
                attention=ATTENTION_NEED,
            )
        )
    elif snapshot.checks and completed and not pending and not failed:
        events.append(
            WakeEvent(
                kind=KIND_CHECKS_GREEN,
                event_id=f"check-green:{snapshot.repo}#{snapshot.number}",
                summary=f"PR #{snapshot.number} checks green",
                attention="",
            )
        )
    elif pending and not failed:
        events.append(
            WakeEvent(
                kind="",
                event_id=f"waiting:{snapshot.repo}#{snapshot.number}",
                summary=f"PR #{snapshot.number} waiting on checks",
                attention=ATTENTION_WAITING,
            )
        )
    for note in snapshot.reviews:
        if note.is_bot or is_bot_author(note.author, allowlisted=allowlisted_bots):
            continue
        body = " ".join((note.body or "").split())
        if len(body) > 120:
            body = body[:117] + "..."
        events.append(
            WakeEvent(
                kind=KIND_REVIEW,
                event_id=f"review:{snapshot.repo}#{snapshot.number}:{note.comment_id}",
                summary=f"PR #{snapshot.number} review from {note.author}: {body}".rstrip(": "),
                attention=ATTENTION_NEED,
            )
        )
    if snapshot.merged:
        events.append(
            WakeEvent(
                kind=KIND_MERGED,
                event_id=f"merged:{snapshot.repo}#{snapshot.number}",
                summary=f"PR #{snapshot.number} merged",
                attention="",
            )
        )
    return tuple(events)


def discover_job_pull_requests(store: Any) -> None:
    lister = getattr(store, "list_recent_jobs", None)
    binder = getattr(store, "bind_job_pull_request", None)
    if not callable(lister) or not callable(binder):
        return
    try:
        jobs = list(lister("", limit=25))
    except Exception:
        return
    bound = getattr(store, "job_for_pull_request", None)
    for job in jobs:
        summary = str(job.get("summary") or "")
        parsed = parse_pull_url(summary)
        if parsed is None:
            continue
        repo, number = parsed
        task_id = str(job.get("task_id") or "")
        if not task_id:
            continue
        if callable(bound):
            try:
                owner = bound(repo, number)
            except Exception:
                owner = None
            if owner:
                continue
        try:
            binder(task_id, repo=repo, number=number)
        except Exception:
            continue
        try:
            link_stacked_pull_request(store, task_id)
        except Exception:
            continue


def link_stacked_pull_request(store: Any, task_id: str) -> str:
    """If this job's PR base is another job's head, parent the child at that tip."""

    rid = (task_id or "").strip()
    if not rid or store is None:
        return ""
    finder = getattr(store, "job_for_head_branch", None)
    latest = getattr(store, "latest_run_id_for_task", None)
    if not callable(finder) or not callable(latest):
        return ""
    repo = ""
    base = ""
    lister = getattr(store, "list_job_pull_requests", None)
    if callable(lister):
        try:
            for row in lister() or ():
                if str(row.get("task_id") or "") != rid:
                    continue
                repo = str(row.get("repo") or "")
                base = str(row.get("base") or "")
                break
        except Exception:
            repo, base = "", ""
    if not repo or not base:
        reader = getattr(store, "task_metadata", None)
        blob: dict[str, Any] = {}
        if callable(reader):
            try:
                github = (reader(rid) or {}).get("github") or {}
            except Exception:
                github = {}
            if isinstance(github, dict):
                blob = github
        repo = repo or str(blob.get("repo") or "")
        base = base or str(blob.get("base") or "")
    if not repo or not base:
        return ""
    try:
        parent = finder(repo, base)
    except Exception:
        parent = None
    if not parent:
        return ""
    parent_task = str(parent.get("task_id") or "")
    if not parent_task or parent_task == rid:
        return ""
    parent_run = latest(parent_task)
    child_run = latest(rid)
    if not parent_run or not child_run:
        return ""
    tip = tip_key(list_nodes(store, parent_run))
    if not tip:
        return ""
    return record_node(
        store,
        run_id=child_run,
        task_id=rid,
        step="stack",
        body=f"{repo} base={base}",
        parent_keys=(tip,),
    )


def wake_github_jobs(
    store: Any,
    discord: Any,
    *,
    snapshotter: Optional[Snapshotter] = None,
    allowlisted_bots: Sequence[str] = (),
    refresh_host: bool = True,
) -> list[dict[str, Any]]:
    """Follow bound PRs. Post check/review wakes into the job thread only."""

    if store is None:
        return []
    discover_job_pull_requests(store)
    reader = getattr(store, "list_job_pull_requests", None)
    if not callable(reader):
        return []
    try:
        rows = list(reader())
    except Exception:
        return []
    fetch = snapshotter or gh_pull_snapshot
    delivered: list[dict[str, Any]] = []
    for row in rows:
        repo = str(row.get("repo") or "").strip()
        try:
            number = int(row.get("number") or 0)
        except (TypeError, ValueError):
            continue
        task_id = str(row.get("task_id") or "")
        if not repo or number < 1 or not task_id:
            continue
        try:
            snapshot = fetch(repo, number)
        except Exception:
            continue
        if snapshot is None:
            continue
        try:
            binder = getattr(store, "bind_job_pull_request", None)
            if callable(binder):
                binder(
                    task_id,
                    repo=repo,
                    number=number,
                    branch=snapshot.branch,
                    base=snapshot.base,
                )
            link_stacked_pull_request(store, task_id)
        except Exception:
            pass
        for event in wake_events(snapshot, allowlisted_bots=allowlisted_bots):
            result = apply_wake(
                store,
                discord,
                task_id=task_id,
                channel_id=str(row.get("channel_id") or ""),
                thread_id=str(row.get("thread_id") or ""),
                run_id=str(row.get("run_id") or ""),
                event=event,
                refresh_host=refresh_host,
            )
            if result is not None:
                delivered.append(result)
    return delivered


def bot_allowlist(*, env: Optional[Mapping[str, str]] = None) -> tuple[str, ...]:
    source = os.environ if env is None else env
    raw = str(source.get("DISCORD_OS_GITHUB_BOT_ALLOW") or "").strip()
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def gh_pull_snapshot(
    repo: str,
    number: int,
    *,
    runner: Optional[Callable[..., Any]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[PullSnapshot]:
    """Best-effort ``gh`` snapshot. Tests inject a snapshotter instead."""

    try:
        from agent_discord.host.github import github_host_env, gh_auth_state, GITHUB_AUTHED
        from agent_discord.host.repos import which_on_host
    except Exception:
        return None
    child = github_host_env(env=env)
    if gh_auth_state(env=env, runner=runner) != GITHUB_AUTHED:
        return None
    gh = which_on_host("gh", env=child)
    if not gh:
        return None
    run = runner
    if run is None:
        import subprocess

        run = subprocess.run
    try:
        proc = run(
            [
                gh,
                "pr",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "mergedAt,statusCheckRollup,reviews,url,headRefName,baseRefName",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=child,
        )
    except Exception:
        return None
    if getattr(proc, "returncode", 1) not in {0, None}:
        return None
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    checks = _checks_from_rollup(payload.get("statusCheckRollup"))
    reviews = _reviews_from_payload(payload.get("reviews"))
    comments = _issue_comments(repo, number, run=run, env=child, gh=gh)
    merged = bool(payload.get("mergedAt"))
    return PullSnapshot(
        repo=repo,
        number=number,
        merged=merged,
        checks=tuple(checks),
        reviews=tuple(reviews) + tuple(comments),
        branch=str(payload.get("headRefName") or ""),
        base=str(payload.get("baseRefName") or ""),
    )


def apply_wake(
    store: Any,
    discord: Any,
    *,
    task_id: str,
    channel_id: str,
    thread_id: str,
    run_id: str,
    event: WakeEvent,
    refresh_host: bool,
) -> Optional[dict[str, Any]]:
    setter = getattr(store, "set_job_github_attention", None)
    if callable(setter):
        try:
            setter(task_id, event.attention, summary=event.summary)
        except Exception:
            pass
    if not event.kind:
        if refresh_host and channel_id:
            _refresh_host(store, discord, channel_id)
        return {
            "task_id": task_id,
            "kind": "waiting",
            "posted": False,
            "event_id": event.event_id,
        }
    claimer = getattr(store, "claim_github_wake", None)
    claimed = True
    if callable(claimer):
        try:
            claimed = bool(claimer(event.event_id, task_id))
        except Exception:
            claimed = True
    if not claimed:
        return None
    posted = False
    if event.kind in {KIND_CHECK_FAILED, KIND_REVIEW} and thread_id and discord is not None:
        posted = _post_thread_wake(discord, channel_id, thread_id, event)
    if event.kind and run_id:
        try:
            parents = ()
            tip = tip_key(list_nodes(store, run_id))
            if tip:
                parents = (tip,)
            record_node(
                store,
                run_id=run_id,
                task_id=task_id,
                step="wake",
                body=event.event_id,
                parent_keys=parents,
            )
        except Exception:
            pass
    if refresh_host and channel_id:
        _refresh_host(store, discord, channel_id)
    return {
        "task_id": task_id,
        "kind": event.kind,
        "posted": posted,
        "event_id": event.event_id,
        "summary": event.summary,
    }


def _post_thread_wake(discord: Any, channel_id: str, thread_id: str, event: WakeEvent) -> bool:
    dest = (thread_id or "").strip()
    parent = (channel_id or "").strip()
    if not dest:
        return False
    try:
        send_card(
            discord,
            parent or dest,
            github_wake_card(event.summary, kind=event.kind),
            thread_id=dest,
        )
        return True
    except Exception:
        return False


def _refresh_host(store: Any, discord: Any, channel_id: str) -> None:
    try:
        from agent_discord.orchestration.listen import publish_host_card

        publish_host_card(discord, store, channel_id)
    except Exception:
        return


def _checks_from_rollup(raw: Any) -> list[CheckItem]:
    items: list[CheckItem] = []
    rows = raw if isinstance(raw, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("context") or "check")
        status = str(row.get("status") or row.get("state") or "").lower()
        conclusion = str(row.get("conclusion") or "").lower()
        if status in {"success", "failure", "cancelled", "timed_out"} and not conclusion:
            conclusion = status
            status = "completed"
        items.append(CheckItem(name=name, status=status or "completed", conclusion=conclusion))
    return items


def _reviews_from_payload(raw: Any) -> list[ReviewNote]:
    notes: list[ReviewNote] = []
    rows = raw if isinstance(raw, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        author = ""
        user = row.get("author") or row.get("user") or {}
        if isinstance(user, dict):
            author = str(user.get("login") or user.get("name") or "")
        elif isinstance(user, str):
            author = user
        body = str(row.get("body") or row.get("state") or "")
        comment_id = str(row.get("id") or row.get("databaseId") or "")
        if not comment_id:
            continue
        notes.append(
            ReviewNote(
                comment_id=str(comment_id),
                author=author,
                body=body,
                is_bot=is_bot_author(author),
            )
        )
    return notes


def _issue_comments(
    repo: str,
    number: int,
    *,
    run: Callable[..., Any],
    env: Mapping[str, str],
    gh: str,
) -> list[ReviewNote]:
    try:
        proc = run(
            [gh, "api", f"repos/{repo}/issues/{number}/comments"],
            capture_output=True,
            text=True,
            timeout=30,
            env=dict(env),
        )
    except Exception:
        return []
    if getattr(proc, "returncode", 1) not in {0, None}:
        return []
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    notes: list[ReviewNote] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        user = row.get("user") or {}
        login = ""
        user_type = ""
        if isinstance(user, dict):
            login = str(user.get("login") or "")
            user_type = str(user.get("type") or "")
        comment_id = str(row.get("id") or "")
        if not comment_id:
            continue
        notes.append(
            ReviewNote(
                comment_id=comment_id,
                author=login,
                body=str(row.get("body") or ""),
                is_bot=str(user_type).lower() == "bot" or is_bot_author(login),
            )
        )
    return notes
