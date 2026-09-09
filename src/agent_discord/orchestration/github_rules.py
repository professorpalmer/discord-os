"""GitHub events that have no owner yet become a job thread.

Rules live in SQLite. Exact repo / branch / conclusion filters. Destination
new cooks the stored prompt when no bind exists. Destination single enqueues
that prompt into the owning job. Same listen poll, same claim_github_wake.
Not a webhook, not cron, not Slack.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from agent_discord.contracts import TaskIntake
from agent_discord.orchestration.cards import CardMessage, send_card
from agent_discord.orchestration.github_wake import (
    KIND_CHECK_FAILED,
    KIND_CHECKS_GREEN,
    KIND_MERGED,
    PullSnapshot,
    WakeEvent,
    apply_wake,
    link_stacked_pull_request,
    wake_events,
)

DEST_NEW = "new"
DEST_SINGLE = "single"


def rule_matches(
    rule: Any,
    snapshot: PullSnapshot,
    events: Sequence[WakeEvent],
) -> bool:
    blob = dict(rule) if isinstance(rule, dict) else {}
    repo = str(blob.get("repo") or "").strip()
    if repo and repo != snapshot.repo:
        return False
    branch = str(blob.get("branch") or "").strip()
    if branch:
        heads = {str(snapshot.branch or ""), str(snapshot.base or "")}
        if branch not in heads:
            return False
    conclusion = str(blob.get("conclusion") or "").strip().lower()
    if not conclusion:
        return True
    if conclusion in {"failure", "failed"}:
        return any(event.kind == KIND_CHECK_FAILED for event in events)
    if conclusion in {"success", "green"}:
        return any(event.kind == KIND_CHECKS_GREEN for event in events)
    if conclusion in {"merged", "merge"}:
        return any(event.kind == KIND_MERGED for event in events)
    return False


def admit_github_rules(
    store: Any,
    discord: Any,
    *,
    orchestrator: Any = None,
    snapshots: Optional[Sequence[PullSnapshot]] = None,
    snapshotter: Any = None,
    allowlisted_bots: Sequence[str] = (),
    refresh_host: bool = True,
) -> list[dict[str, Any]]:
    if store is None:
        return []
    reader = getattr(store, "list_github_rules", None)
    if not callable(reader):
        return []
    try:
        rules = list(reader() or ())
    except Exception:
        return []
    if not rules:
        return []
    candidates = _candidate_snapshots(store, snapshots=snapshots, snapshotter=snapshotter)
    if not candidates:
        return []
    owned = getattr(store, "job_for_pull_request", None)
    delivered: list[dict[str, Any]] = []
    for snapshot in candidates:
        events = wake_events(snapshot, allowlisted_bots=allowlisted_bots)
        owner = None
        if callable(owned):
            try:
                owner = owned(snapshot.repo, snapshot.number)
            except Exception:
                owner = None
        for rule in rules:
            if not rule_matches(rule, snapshot, events):
                continue
            dest = str((rule or {}).get("destination") or DEST_NEW).strip().lower()
            primary = _primary_event(events, str((rule or {}).get("conclusion") or ""))
            if primary is None:
                continue
            if dest == DEST_SINGLE:
                if not owner:
                    continue
                followed = follow_bound_job(
                    store,
                    discord,
                    owner=owner,
                    event=primary,
                    rule=rule,
                    orchestrator=orchestrator,
                )
                if followed is not None:
                    delivered.append(followed)
                break
            if owner or dest != DEST_NEW:
                continue
            minted = open_unbound_job(
                store,
                discord,
                snapshot=snapshot,
                event=primary,
                rule=rule,
                orchestrator=orchestrator,
                refresh_host=refresh_host,
            )
            if minted is not None:
                delivered.append(minted)
            break
    return delivered


def follow_bound_job(
    store: Any,
    discord: Any,
    *,
    owner: Any,
    event: WakeEvent,
    rule: Any,
    orchestrator: Any,
) -> Optional[dict[str, Any]]:
    blob = dict(rule) if isinstance(rule, dict) else {}
    prompt = str(blob.get("prompt") or "").strip()
    if not prompt or orchestrator is None:
        return None
    task_id = str(owner.get("task_id") or "")
    thread_id = str(owner.get("thread_id") or "")
    channel_id = str(blob.get("channel_id") or owner.get("channel_id") or "").strip()
    workspace_id = str(blob.get("workspace_id") or "default").strip() or "default"
    if not task_id or not channel_id:
        return None
    rule_id = str(blob.get("rule_id") or "")
    if not _claim_rule(store, rule_id, event, task_id):
        return None
    body = _cook_prompt(prompt, event)
    run_id = str(owner.get("run_id") or "")
    if not run_id:
        latest = getattr(store, "latest_run_id_for_task", None)
        if callable(latest):
            try:
                run_id = str(latest(task_id) or "")
            except Exception:
                run_id = ""
    steerer = getattr(orchestrator, "steer", None)
    if callable(steerer) and run_id:
        try:
            if steerer(run_id, body):
                return {
                    "task_id": task_id,
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "event_id": event.event_id,
                    "steered": True,
                }
        except Exception:
            pass
    runner = getattr(orchestrator, "run_task", None)
    if not callable(runner):
        return None
    try:
        receipt = runner(
            TaskIntake(
                text=body,
                channel_id=channel_id,
                workspace_id=workspace_id,
                thread_id=thread_id or None,
                metadata={
                    "github_rule": True,
                    "github_event": event.event_id,
                    "approved": True,
                    "replay_of": run_id,
                },
            )
        )
    except Exception:
        return None
    return {
        "task_id": str(getattr(receipt, "task_id", "") or ""),
        "run_id": str(getattr(receipt, "run_id", "") or ""),
        "thread_id": thread_id,
        "event_id": event.event_id,
        "steered": False,
    }


def open_unbound_job(
    store: Any,
    discord: Any,
    *,
    snapshot: PullSnapshot,
    event: WakeEvent,
    rule: Any,
    orchestrator: Any,
    refresh_host: bool,
) -> Optional[dict[str, Any]]:
    blob = dict(rule) if isinstance(rule, dict) else {}
    channel_id = str(blob.get("channel_id") or "").strip()
    workspace_id = str(blob.get("workspace_id") or "default").strip() or "default"
    prompt = str(blob.get("prompt") or "").strip() or event.summary
    runner = getattr(orchestrator, "run_task", None) if orchestrator is not None else None
    if not channel_id or not callable(runner):
        return None
    thread_id = _start_job_thread(
        discord,
        channel_id,
        title=event.summary or "job",
        summary=event.summary,
    )
    try:
        receipt = runner(
            TaskIntake(
                text=_cook_prompt(prompt, event),
                channel_id=channel_id,
                workspace_id=workspace_id,
                thread_id=thread_id or None,
                metadata={
                    "github_rule": True,
                    "github_event": event.event_id,
                    "approved": True,
                },
            )
        )
    except Exception:
        return None
    task_id = str(getattr(receipt, "task_id", "") or "")
    run_id = str(getattr(receipt, "run_id", "") or "")
    if not task_id:
        return None
    try:
        store.bind_job_pull_request(
            task_id,
            repo=snapshot.repo,
            number=snapshot.number,
            branch=snapshot.branch,
            base=snapshot.base,
        )
        link_stacked_pull_request(store, task_id)
    except Exception:
        pass
    if thread_id:
        binder = getattr(store, "bind_task_thread", None)
        if callable(binder):
            try:
                binder(task_id, thread_id)
            except Exception:
                pass
    apply_wake(
        store,
        discord,
        task_id=task_id,
        channel_id=channel_id,
        thread_id=thread_id,
        run_id=run_id,
        event=event,
        refresh_host=refresh_host,
    )
    code = ""
    reader = getattr(store, "task_job_code", None)
    if callable(reader):
        try:
            code = str(reader(task_id) or "")
        except Exception:
            code = ""
    return {
        "task_id": task_id,
        "run_id": run_id,
        "job_code": code,
        "thread_id": thread_id,
        "event_id": event.event_id,
    }


def _candidate_snapshots(
    store: Any,
    *,
    snapshots: Optional[Sequence[PullSnapshot]],
    snapshotter: Any,
) -> list[PullSnapshot]:
    out: list[PullSnapshot] = []
    seen: set[tuple[str, int]] = set()

    def add(snapshot: Optional[PullSnapshot]) -> None:
        if snapshot is None:
            return
        key = (str(snapshot.repo), int(snapshot.number))
        if key in seen:
            return
        seen.add(key)
        out.append(snapshot)

    for snapshot in snapshots or ():
        add(snapshot)
    if not callable(snapshotter):
        return out
    lister = getattr(store, "list_job_pull_requests", None)
    if not callable(lister):
        return out
    try:
        rows = list(lister() or ())
    except Exception:
        return out
    for row in rows:
        repo = str(row.get("repo") or "").strip()
        try:
            number = int(row.get("number") or 0)
        except (TypeError, ValueError):
            continue
        if not repo or number < 1:
            continue
        try:
            add(snapshotter(repo, number))
        except Exception:
            continue
    return out


def _primary_event(events: Sequence[WakeEvent], conclusion: str) -> Optional[WakeEvent]:
    kind = ""
    wanted = (conclusion or "").strip().lower()
    if wanted in {"failure", "failed"}:
        kind = KIND_CHECK_FAILED
    elif wanted in {"success", "green"}:
        kind = KIND_CHECKS_GREEN
    elif wanted in {"merged", "merge"}:
        kind = KIND_MERGED
    if kind:
        return next((event for event in events if event.kind == kind), None)
    failed = next((event for event in events if event.kind == KIND_CHECK_FAILED), None)
    if failed is not None:
        return failed
    return next((event for event in events if event.kind), None)


def _claim_rule(store: Any, rule_id: str, event: WakeEvent, task_id: str) -> bool:
    claimer = getattr(store, "claim_github_wake", None)
    if not callable(claimer):
        return True
    eid = f"rule:{rule_id or 'anon'}:{event.event_id}"
    try:
        return bool(claimer(eid, task_id))
    except Exception:
        return True


def _cook_prompt(prompt: str, event: WakeEvent) -> str:
    body = (prompt or "").strip() or event.summary
    summary = (event.summary or "").strip()
    if summary and summary not in body:
        return f"{body}\n\n{summary}"
    return body


def _start_job_thread(
    discord: Any,
    channel_id: str,
    *,
    title: str,
    summary: str,
) -> str:
    if discord is None or not channel_id:
        return ""
    starter = CardMessage(
        kind="NOTE",
        title=(title or "job").strip() or "job",
        description=summary or "",
    )
    try:
        posted = send_card(discord, channel_id, starter)
    except Exception:
        return ""
    message_id = _posted_message_id(posted)
    if not message_id:
        return ""
    opener = getattr(discord, "start_thread_from_message", None)
    if not callable(opener):
        return ""
    try:
        return str(opener(channel_id, message_id, (title or "job")[:100]) or "")
    except Exception:
        return ""


def _posted_message_id(posted: Any) -> str:
    if posted is None:
        return ""
    if isinstance(posted, list) and posted:
        return str(getattr(posted[-1], "message_id", "") or "")
    return str(getattr(posted, "message_id", "") or "")
