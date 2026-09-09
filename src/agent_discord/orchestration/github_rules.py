"""GitHub events that have no owner yet become a job thread.

Rules live in SQLite. Exact repo / branch / conclusion filters. Destination
new mints a job; single is the bound-PR path from github_wake. Same listen
poll, same claim_github_wake. Not a webhook, not cron, not Slack.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence
from uuid import uuid4

from agent_discord.contracts import TaskStatus
from agent_discord.orchestration.cards import CardMessage, send_card
from agent_discord.orchestration.github_wake import (
    KIND_CHECK_FAILED,
    KIND_CHECKS_GREEN,
    PullSnapshot,
    WakeEvent,
    apply_wake,
    link_stacked_pull_request,
    wake_events,
)
from agent_discord.orchestration.lineage import record_node

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
    return False


def admit_github_rules(
    store: Any,
    discord: Any,
    *,
    snapshots: Optional[Sequence[PullSnapshot]] = None,
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
    owned = getattr(store, "job_for_pull_request", None)
    delivered: list[dict[str, Any]] = []
    for snapshot in snapshots or ():
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
            if owner:
                continue
            if dest != DEST_NEW:
                continue
            primary = next(
                (event for event in events if event.kind == KIND_CHECK_FAILED),
                None,
            )
            if primary is None:
                primary = next((event for event in events if event.kind), None)
            if primary is None:
                continue
            minted = open_unbound_job(
                store,
                discord,
                snapshot=snapshot,
                event=primary,
                rule=rule,
                refresh_host=refresh_host,
            )
            if minted is not None:
                delivered.append(minted)
            break
    return delivered


def open_unbound_job(
    store: Any,
    discord: Any,
    *,
    snapshot: PullSnapshot,
    event: WakeEvent,
    rule: Any,
    refresh_host: bool,
) -> Optional[dict[str, Any]]:
    blob = dict(rule) if isinstance(rule, dict) else {}
    channel_id = str(blob.get("channel_id") or "").strip()
    workspace_id = str(blob.get("workspace_id") or "default").strip() or "default"
    prompt = str(blob.get("prompt") or "").strip() or event.summary
    if not channel_id:
        return None
    task_id = uuid4().hex
    run_id = uuid4().hex
    try:
        store.create_task(
            task_id=task_id,
            workspace_id=workspace_id,
            channel_id=channel_id,
            intake_text=prompt,
        )
        store.create_run(
            run_id=run_id,
            task_id=task_id,
            model="github-rule",
            adapter_name="github-rule",
            status=TaskStatus.COMPLETED,
        )
        store.update_run(run_id, status=TaskStatus.COMPLETED, summary=event.summary)
        store.bind_job_pull_request(
            task_id,
            repo=snapshot.repo,
            number=snapshot.number,
            branch=snapshot.branch,
            base=snapshot.base,
        )
    except Exception:
        return None
    try:
        record_node(
            store,
            run_id=run_id,
            task_id=task_id,
            step="intake",
            body=prompt,
        )
        link_stacked_pull_request(store, task_id)
    except Exception:
        pass
    code = ""
    reader = getattr(store, "task_job_code", None)
    if callable(reader):
        try:
            code = str(reader(task_id) or "")
        except Exception:
            code = ""
    thread_id = _start_job_thread(
        discord,
        channel_id,
        code=code,
        summary=event.summary,
    )
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
    return {
        "task_id": task_id,
        "run_id": run_id,
        "job_code": code,
        "thread_id": thread_id,
        "event_id": event.event_id,
    }


def _start_job_thread(
    discord: Any,
    channel_id: str,
    *,
    code: str,
    summary: str,
) -> str:
    if discord is None or not channel_id:
        return ""
    starter = CardMessage(
        kind="NOTE",
        title=(code or "job").strip() or "job",
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
        return str(opener(channel_id, message_id, (code or "job")[:100]) or "")
    except Exception:
        return ""


def _posted_message_id(posted: Any) -> str:
    if posted is None:
        return ""
    if isinstance(posted, list) and posted:
        return str(getattr(posted[-1], "message_id", "") or "")
    return str(getattr(posted, "message_id", "") or "")
