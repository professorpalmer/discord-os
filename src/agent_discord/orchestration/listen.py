"""Inbound Discord drain — phone / staff-channel messages become TaskIntake."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from agent_discord.contracts import DiscordMessage, RunReceipt, TaskIntake
from agent_discord.host.power import is_power_command, parse_power_command
from agent_discord.host.memory import bind_memory_channel, is_memory_bind
from agent_discord.host.realms import bind_channel_realm, is_bind_command, parse_bind_command
from agent_discord.host.repos import load_host_repos
from agent_discord.host.verbs import handle_open_message, is_open_command
from agent_discord.keys.connect import (
    handle_connect_message,
    is_connect_command,
    parse_connect_command,
)
from agent_discord.orchestration.cards import (
    connect_card,
    edit_card,
    host_card,
    is_harness_card,
    is_harness_message,
    open_card,
    send_card,
)
from agent_discord.orchestration.jobs import resolved_write_key
from agent_discord.orchestration.service import (
    author_may_dispatch,
    expire_parked_approvals,
    inbound_queue_enabled,
    is_spend_halted,
    operators_configured,
    parse_claim_command,
    parse_handoff_command,
    parse_schedule_command,
    seed_spend_cap_from_env,
    seed_write_gate_from_env,
    session_spend_usd,
    spend_cap_usd,
    writes_need_approval,
)

DISCORD_EPOCH_MS = 1_420_070_400_000
LISTEN_HISTORY_SLACK_MS = 15_000


def snowflake_created_ms(message_id: str) -> Optional[int]:
    try:
        return (int(message_id) >> 22) + DISCORD_EPOCH_MS
    except (TypeError, ValueError):
        return None


def listen_destinations(
    channel_ids: Sequence[str],
    *live_sources: Any,
    session_thread_ids: Sequence[str] = (),
) -> list[str]:
    """Primary listen ids plus live and recent idle job-thread dests.

    Idle sessions stay listenable after Done so a later reply in the same
    Discord thread starts a new job instead of going silent.
    """

    dests: list[str] = []
    seen: set[str] = set()
    for cid in channel_ids:
        value = str(cid or "").strip()
        if value and value not in seen:
            dests.append(value)
            seen.add(value)
    for src in live_sources:
        getter = getattr(src, "live_thread_ids", None)
        if not callable(getter):
            continue
        try:
            extra = getter()
        except Exception:
            extra = ()
        for tid in extra or ():
            value = str(tid or "").strip()
            if value and value not in seen:
                dests.append(value)
                seen.add(value)
    for tid in session_thread_ids or ():
        value = str(tid or "").strip()
        if value and value not in seen:
            dests.append(value)
            seen.add(value)
    return dests


def default_listen_since_ms(*, now_ms: Optional[int] = None) -> int:
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    return now - LISTEN_HISTORY_SLACK_MS


def _message_id_after(message_id: str, previous_id: str) -> bool:
    if not previous_id:
        return bool(message_id)
    if message_id == previous_id:
        return False
    try:
        return int(message_id) > int(previous_id)
    except (TypeError, ValueError):
        return message_id != previous_id


def _inbound_sort_key(message: DiscordMessage) -> tuple[object, ...]:
    created = snowflake_created_ms(message.message_id) if message.message_id else None
    try:
        numeric = int(message.message_id) if message.message_id else 0
    except (TypeError, ValueError):
        numeric = 0
    return (created is None, created or 0, numeric, message.message_id or "")


def _inbound_newer_than_watermark(
    message_id: str,
    created_ms: Optional[int],
    watermark: Mapping[str, Any],
) -> bool:
    last_ms = watermark.get("last_created_ms")
    last_id = str(watermark.get("last_message_id") or "")
    if created_ms is not None and last_ms is not None:
        if created_ms != int(last_ms):
            return created_ms > int(last_ms)
        return _message_id_after(message_id, last_id)
    if created_ms is not None:
        return True
    return bool(message_id) and message_id != last_id


def _watermark_after(
    watermark: Mapping[str, Any],
    created_ms: Optional[int],
    message_id: str,
) -> dict[str, Any]:
    last_ms = watermark.get("last_created_ms")
    last_id = str(watermark.get("last_message_id") or "")
    next_ms = last_ms
    next_id = last_id
    if created_ms is not None:
        if last_ms is None or created_ms > int(last_ms):
            next_ms = created_ms
            next_id = message_id or last_id
        elif created_ms == int(last_ms) and _message_id_after(message_id, last_id):
            next_id = message_id
    elif message_id and message_id != last_id:
        next_id = message_id
    return {
        "channel_id": watermark.get("channel_id"),
        "last_created_ms": next_ms,
        "last_message_id": next_id,
    }


def _advance_listen_watermark(
    store: Any,
    channel_id: str,
    created_ms: Optional[int],
    message_id: Optional[str],
    watermark: Mapping[str, Any],
) -> dict[str, Any]:
    updated = _watermark_after(watermark, created_ms, message_id or "")
    writer = getattr(store, "set_listen_watermark", None)
    if callable(writer):
        writer(
            channel_id,
            created_ms=updated.get("last_created_ms"),
            message_id=str(updated.get("last_message_id") or ""),
        )
        reader = getattr(store, "get_listen_watermark", None)
        if callable(reader):
            refreshed = reader(channel_id)
            if refreshed is not None:
                return refreshed
    return updated


def should_dispatch_inbound(message: DiscordMessage) -> bool:
    """Skip empty, bot receipts, progress lines, cards, and object-store captions."""

    content = (message.content or "").strip()
    embeds = None
    components = None
    meta = getattr(message, "metadata", None)
    if isinstance(meta, dict):
        raw_embeds = meta.get("embeds")
        if isinstance(raw_embeds, list):
            embeds = raw_embeds
        raw_components = meta.get("components")
        if isinstance(raw_components, list):
            components = raw_components
    if is_harness_message(content, embeds, components):
        return False
    if not content:
        if isinstance(meta, dict) and (
            meta.get("transcript")
            or meta.get("voice_transcript")
            or meta.get("voice_urls")
            or meta.get("local_audio_path")
            or meta.get("voice_bytes")
        ):
            return True
        return False
    if is_harness_card(content):
        return False
    if content.startswith("[") and "] " in content[:48]:
        return False
    if content.startswith("{") and content.endswith("}"):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return True
        if isinstance(payload, dict) and payload.get("agent_discord_object") == 1:
            return False
    return True


def drain_inbound(
    orchestrator: Any,
    discord: Any,
    *,
    channel_id: str,
    workspace_id: str = "default",
    guild_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    limit: int = 20,
    workspace: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    since_ms: Optional[int] = None,
    host_roots: Optional[Sequence[Path]] = None,
    host_runner: Optional[Any] = None,
    browser_open: Optional[Any] = None,
    job_pool: Optional[Any] = None,
) -> Sequence[RunReceipt]:
    """Read recent channel messages and dispatch each new human task once.

    Connect and open commands are intercepted before TaskIntake. A shred
    payload is never dispatched as a prompt, even when delete fails. Host
    opens stay on this process; Discord is only the remote.
    """

    messages = discord.read_messages(
        channel_id,
        limit=limit,
        thread_id=thread_id,
        skip_duplicates=False,
    )
    receipts: list[RunReceipt] = []
    ws = Path(workspace) if workspace is not None else _workspace_from(orchestrator)
    store = getattr(orchestrator, "store", None)
    if store is not None:
        seed_spend_cap_from_env(store, env)
        seed_write_gate_from_env(store, env)
    seed_ms = since_ms if since_ms is not None else default_listen_since_ms()
    # Session/job threads keep their own watermark key. Parent tip advances on
    # HOST panel paints and must not hide older-but-unseen thread follow-ups.
    watermark_key = (str(thread_id or "").strip() or str(channel_id or "").strip())
    seeder = getattr(store, "seed_listen_watermark", None)
    if callable(seeder):
        watermark = seeder(watermark_key, seed_ms)
    else:
        watermark = {"channel_id": watermark_key, "last_created_ms": seed_ms, "last_message_id": ""}
    snapshot = dict(watermark)
    pending: list[DiscordMessage] = []
    for message in messages:
        created_ms = snowflake_created_ms(message.message_id) if message.message_id else None
        if not _inbound_newer_than_watermark(message.message_id or "", created_ms, snapshot):
            continue
        pending.append(message)
    pending.sort(key=_inbound_sort_key)
    for message in pending:
        created_ms = snowflake_created_ms(message.message_id) if message.message_id else None
        if is_connect_command(message.content or ""):
            _absorb_connect(
                message,
                discord=discord,
                orchestrator=orchestrator,
                channel_id=channel_id,
                thread_id=message.thread_id or thread_id,
                workspace=ws,
                env=env,
            )
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        if is_bind_command(message.content or ""):
            if not author_may_dispatch(
                store,
                message.author_id,
                role_ids=_author_role_ids(message),
            ):
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            _absorb_bind(
                message,
                discord=discord,
                orchestrator=orchestrator,
                channel_id=channel_id,
                workspace_id=workspace_id,
                thread_id=message.thread_id or thread_id,
            )
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        if is_power_command(message.content or ""):
            _absorb_power(
                message,
                discord=discord,
                orchestrator=orchestrator,
                channel_id=channel_id,
                thread_id=message.thread_id or thread_id,
            )
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        if is_open_command(message.content or ""):
            if not author_may_dispatch(
                store,
                message.author_id,
                role_ids=_author_role_ids(message),
            ):
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            if not _channel_is_armed(store, channel_id):
                _claim_inbound(store, discord, message, channel_id)
                publish_host_card(
                    discord,
                    store,
                    channel_id,
                    thread_id=message.thread_id or thread_id,
                )
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            _absorb_open(
                message,
                discord=discord,
                orchestrator=orchestrator,
                channel_id=channel_id,
                thread_id=message.thread_id or thread_id,
                roots=host_roots or ((ws,) if ws is not None else ()),
                runner=host_runner,
                browser_open=browser_open,
            )
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        if _maybe_absorb_jishaku(
            message,
            discord=discord,
            store=store,
            channel_id=channel_id,
            thread_id=message.thread_id or thread_id,
            env=env,
        ):
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        intake_text, intake_meta, skip_voice = _collab_intake(message, discord)
        if skip_voice:
            _claim_inbound(store, discord, message, channel_id)
            _post_voice_whisper_miss(
                discord,
                channel_id,
                message.thread_id or thread_id,
            )
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        scheduled = parse_schedule_command(intake_text or (message.content or ""))
        if scheduled is not None:
            _absorb_schedule(
                message,
                discord=discord,
                store=store,
                channel_id=channel_id,
                workspace_id=workspace_id,
                every_s=scheduled[0],
                prompt=scheduled[1],
                thread_id=message.thread_id or thread_id,
            )
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        if not intake_text and not should_dispatch_inbound(message):
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        if not _channel_is_armed(store, channel_id):
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        text = intake_text or (message.content or "").strip()
        if not text:
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        if is_spend_halted(store, workspace_id):
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        if not author_may_dispatch(
            store,
            message.author_id,
            role_ids=_author_role_ids(message),
        ):
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        follow_thread = _follow_thread_id(message, thread_id, orchestrator, job_pool)
        if _absorb_spoken_gate(
            orchestrator,
            discord,
            store,
            message=message,
            text=text,
            channel_id=channel_id,
            thread_id=follow_thread,
        ):
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        if follow_thread and _thread_has_running_job(orchestrator, job_pool, follow_thread):
            if not _claim_inbound(store, discord, message, channel_id):
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            _handle_live_thread_followup(
                orchestrator,
                discord,
                store,
                job_pool,
                message=message,
                text=text,
                channel_id=channel_id,
                thread_id=follow_thread,
                workspace_id=workspace_id,
                env=env,
            )
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        extra_meta = dict(intake_meta or {})
        if not _claim_inbound(store, discord, message, channel_id):
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue
        claimed_code = parse_claim_command(intake_text or (message.content or ""))
        if claimed_code is not None:
            author = str(message.author_id or "")
            if author and not author_may_dispatch(store, author):
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            if job_pool is None:
                _post_host_deny(
                    discord,
                    channel_id,
                    follow_thread,
                    "Need: claim requires JobPool (live host) — refused.",
                )
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            row = store.get_task_by_job_code(claimed_code)
            if row is None:
                _post_host_deny(
                    discord,
                    channel_id,
                    follow_thread,
                    f"Need: claim {claimed_code} — unknown job_code.",
                )
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            import json
            meta_raw = row.get("metadata_json") or "{}"
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw or {})
            except Exception:
                meta = {}
            status = str(row.get("status") or "").strip().lower()
            prior = str(meta.get("claimed_by") or "").strip()
            live = status in {
                "pending",
                "queued",
                "running",
                "waiting",
                "waiting_approval",
                "parked",
                "failed",
            }
            if prior and prior != author and live:
                _post_host_deny(
                    discord,
                    channel_id,
                    follow_thread,
                    f"Need: claim already_claimed {claimed_code} by <@{prior}>.",
                )
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            store.merge_task_metadata(
                str(row.get("task_id") or ""),
                {
                    "claimed_by": author,
                    "lane": str(meta.get("lane") or "board"),
                    "board_claim": True,
                },
            )
            try:
                send = getattr(discord, "send_message", None)
                if callable(send):
                    send(
                        channel_id,
                        f"Claimed {claimed_code} → <@{author}> (board lane).",
                        thread_id=follow_thread,
                    )
            except Exception:
                pass
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue

        handed = parse_handoff_command(intake_text or (message.content or ""))
        if handed is not None:
            peer_id, peer_prompt = handed
            if job_pool is None:
                _post_host_deny(
                    discord,
                    channel_id,
                    follow_thread,
                    "Need: handoff/peer-task requires JobPool (live host) — refused.",
                )
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            author = str(message.author_id or "")
            if author and not author_may_dispatch(store, author):
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            if not author_may_dispatch(store, peer_id):
                _post_host_deny(
                    discord,
                    channel_id,
                    follow_thread,
                    f"Need: handoff peer {peer_id} is not an operator — Pair them first.",
                )
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            
            from agent_discord.host.brain import format_meat_proxy_handoff_preamble
            from agent_discord.orchestration.handoff_envelope import (
                build_handoff_envelope,
                find_live_handoff_claim,
                spoken_already_claimed,
            )

            envelope, cleaned_prompt = build_handoff_envelope(
                from_id=author,
                to_id=peer_id,
                peer_prompt=peer_prompt,
            )
            claimed = find_live_handoff_claim(
                store, envelope.handoff_id, channel_id=channel_id
            )
            if claimed is not None:
                _post_host_deny(
                    discord,
                    channel_id,
                    follow_thread,
                    spoken_already_claimed(
                        envelope.handoff_id,
                        job_code=str(claimed.get("job_code") or ""),
                    ),
                )
                watermark = _advance_listen_watermark(
                    store, watermark_key, created_ms, message.message_id, watermark
                )
                continue
            try:
                enriched_prompt = format_meat_proxy_handoff_preamble(
                    store,
                    workspace_id=workspace_id,
                    channel_id=channel_id,
                    from_id=author,
                    to_id=peer_id,
                    peer_prompt=cleaned_prompt,
                    envelope=envelope,
                )
            except TypeError:
                try:
                    enriched_prompt = format_meat_proxy_handoff_preamble(
                        store,
                        workspace_id=workspace_id,
                        channel_id=channel_id,
                        from_id=author,
                        to_id=peer_id,
                        peer_prompt=cleaned_prompt,
                    )
                except Exception:
                    enriched_prompt = cleaned_prompt
            except Exception:
                enriched_prompt = cleaned_prompt
            handoff_meta = envelope.as_metadata()
            # Parent context for Saga-lite compensation NOTE + Wave 6 recovery beat on unclean peer settle.
            if follow_thread:
                handoff_meta["parent_thread_id"] = follow_thread
            if message.message_id:
                handoff_meta["parent_message_id"] = message.message_id
            handoff_meta["parent_channel_id"] = channel_id
            handoff_intake = TaskIntake(
                text=enriched_prompt,
                channel_id=channel_id,
                workspace_id=workspace_id,
                guild_id=guild_id,
                thread_id=follow_thread,
                message_id=message.message_id or None,
                requester_id=peer_id,
                metadata=handoff_meta,
            )
            job_pool.submit(
                orchestrator.run_task,
                handoff_intake,
                write_key=resolved_write_key(handoff_intake, orchestrator),
            )
            try:
                send = getattr(discord, "send_message", None)
                if callable(send):
                    send(
                        channel_id,
                        f"Handoff → <@{peer_id}> id={envelope.handoff_id} "
                        f"(JobPool) — {cleaned_prompt[:100]}",
                        thread_id=follow_thread,
                    )
            except Exception:
                pass
            watermark = _advance_listen_watermark(
                store, watermark_key, created_ms, message.message_id, watermark
            )
            continue

        extra_meta["inbound_claimed"] = True
        intake = TaskIntake(
            text=text,
            channel_id=channel_id,
            workspace_id=workspace_id,
            guild_id=guild_id,
            thread_id=follow_thread,
            message_id=message.message_id or None,
            requester_id=message.author_id,
            metadata=extra_meta,
        )
        if job_pool is not None:
            job_pool.submit(
                orchestrator.run_task,
                intake,
                write_key=resolved_write_key(intake, orchestrator),
            )
        else:
            receipts.append(orchestrator.run_task(intake))
        watermark = _advance_listen_watermark(
            store, watermark_key, created_ms, message.message_id, watermark
        )
    receipts.extend(
        _fire_due_schedules(
            orchestrator,
            store,
            channel_id=channel_id,
            workspace_id=workspace_id,
            guild_id=guild_id,
            thread_id=thread_id,
            discord=discord,
        )
    )
    receipts.extend(
        _flush_inbound_queue(
            orchestrator,
            discord,
            store,
            job_pool,
            workspace_id=workspace_id,
            env=env,
        )
    )
    _tick_approval_timeout_best_effort(orchestrator, env)
    _tick_gate_queue_best_effort(orchestrator, env)
    if thread_id is None:
        try:
            from agent_discord.orchestration.github_rules import admit_github_rules
            from agent_discord.orchestration.github_wake import bot_allowlist, wake_github_jobs

            wake_github_jobs(
                store,
                discord,
                snapshotter=getattr(orchestrator, "github_snapshotter", None),
                allowlisted_bots=bot_allowlist(),
            )
            admit_github_rules(
                store,
                discord,
                orchestrator=orchestrator,
                snapshots=getattr(orchestrator, "github_unbound_snapshots", None),
                snapshotter=getattr(orchestrator, "github_snapshotter", None),
                allowlisted_bots=bot_allowlist(),
            )
        except Exception:
            pass
        _tick_host_liveness_best_effort(
            discord,
            store,
            channel_id=channel_id,
            workspace_id=workspace_id,
            workspace=ws,
        )
    return receipts







def _absorb_spoken_gate(
    orchestrator: Any,
    discord: Any,
    store: Any,
    *,
    message: DiscordMessage,
    text: str,
    channel_id: str,
    thread_id: Optional[str],
) -> bool:
    """Spoken Allow / Always / Deny for parked write or tool/ask gates.

    Plan parks (P2.8) accept Approve / Deny / Cancel only — never Always.
    """

    from agent_discord.orchestration.ask_gate import parse_spoken_gate_verb
    from agent_discord.orchestration.plan_approve import parse_spoken_plan_verb

    run_id = _parked_run_for_destination(store, channel_id=channel_id, thread_id=thread_id)
    if not run_id:
        return False
    verb = None
    if _parked_is_plan(store, run_id):
        verb = parse_spoken_plan_verb(text)
    else:
        verb = parse_spoken_gate_verb(text)
    if verb is None:
        return False
    if not _claim_inbound(store, discord, message, channel_id):
        return True
    applier = getattr(orchestrator, "apply_job_action", None)
    if not callable(applier):
        return True
    try:
        applier(verb, run_id)
    except Exception:
        pass
    return True


def _parked_is_plan(store: Any, run_id: str) -> bool:
    getter = getattr(store, "get_run", None)
    if not callable(getter):
        return False
    try:
        run = getter(run_id) or {}
    except Exception:
        return False
    task_id = str(run.get("task_id") or "")
    reader = getattr(store, "task_metadata", None)
    if not callable(reader) or not task_id:
        return False
    try:
        meta = reader(task_id) or {}
    except Exception:
        return False
    from agent_discord.orchestration.plan_approve import is_plan_gate_meta

    return is_plan_gate_meta(meta if isinstance(meta, dict) else {})


def _parked_run_for_destination(
    store: Any,
    *,
    channel_id: str = "",
    thread_id: Optional[str] = None,
) -> str:
    lister = getattr(store, "list_parked_approvals", None)
    if not callable(lister):
        return ""
    try:
        rows = list(lister())
    except Exception:
        return ""
    tid = (thread_id or "").strip()
    cid = (channel_id or "").strip()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_thread = str(row.get("thread_id") or "").strip()
        row_channel = str(row.get("channel_id") or "").strip()
        if tid and row_thread == tid:
            return str(row.get("run_id") or "").strip()
        if not tid and cid and row_channel == cid and not row_thread:
            return str(row.get("run_id") or "").strip()
    return ""


def _tick_approval_timeout_best_effort(
    orchestrator: Any, env: Optional[Mapping[str, str]]
) -> None:
    """Auto-deny stale parked write-gates. Best-effort."""

    try:
        expire_parked_approvals(orchestrator, env=env)
    except Exception:
        pass


def _tick_gate_queue_best_effort(
    orchestrator: Any, env: Optional[Mapping[str, str]]
) -> None:
    """Park Discord cards for pending live-hook requests. Best-effort."""

    try:
        from agent_discord.orchestration.gate_hook import drain_gate_queue

        drain_gate_queue(orchestrator, env=env)
    except Exception:
        pass


def _handle_live_thread_followup(
    orchestrator: Any,
    discord: Any,
    store: Any,
    job_pool: Optional[Any],
    *,
    message: DiscordMessage,
    text: str,
    channel_id: str,
    thread_id: str,
    workspace_id: str,
    env: Optional[Mapping[str, str]],
) -> None:
    """Steer if we can; otherwise durable-queue. Never mint a sibling write."""

    run_id = _running_run_id(orchestrator, job_pool, thread_id) or ""
    queue_id = None
    if inbound_queue_enabled(env):
        enqueuer = getattr(store, "enqueue_inbound", None)
        if callable(enqueuer):
            try:
                queue_id = enqueuer(
                    message_id=message.message_id or "",
                    channel_id=channel_id,
                    thread_id=thread_id,
                    text=text,
                    run_id=run_id,
                    workspace_id=workspace_id,
                    author_id=str(message.author_id or ""),
                )
            except Exception:
                queue_id = None
    steered = _steer_running_job(
        orchestrator,
        discord,
        job_pool,
        text=text,
        channel_id=channel_id,
        thread_id=thread_id,
        notify_miss=False,
        operator_id=str(message.author_id or ""),
    )
    if steered:
        if queue_id:
            _mark_queue(store, queue_id, applied=True)
        return
    if queue_id:
        _post_queued_ack(discord, channel_id, thread_id)
        return
    _post_steer_miss(discord, channel_id, thread_id)


def _flush_inbound_queue(
    orchestrator: Any,
    discord: Any,
    store: Any,
    job_pool: Optional[Any],
    *,
    workspace_id: str,
    env: Optional[Mapping[str, str]],
) -> list[RunReceipt]:
    if store is None or not inbound_queue_enabled(env):
        return []
    lister = getattr(store, "list_queued_inbound", None)
    if not callable(lister):
        return []
    try:
        rows = list(lister("", limit=20))
    except Exception:
        return []
    receipts: list[RunReceipt] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        qid = str(row.get("queue_id") or "").strip()
        dest_thread = str(row.get("thread_id") or "").strip()
        dest_channel = str(row.get("channel_id") or "").strip()
        body = str(row.get("text") or "").strip()
        if not dest_thread or not dest_channel or not body:
            _mark_queue(store, qid, applied=False)
            continue
        if _thread_has_running_job(orchestrator, job_pool, dest_thread):
            steered = _steer_running_job(
                orchestrator,
                discord,
                job_pool,
                text=body,
                channel_id=dest_channel,
                thread_id=dest_thread,
                notify_miss=False,
            )
            if steered:
                _mark_queue(store, qid, applied=True)
            continue
        intake = TaskIntake(
            text=body,
            channel_id=dest_channel,
            workspace_id=str(row.get("workspace_id") or workspace_id or "default"),
            thread_id=dest_thread,
            requester_id=str(row.get("author_id") or "") or None,
            metadata={"inbound_queued": True, "inbound_claimed": True},
        )
        try:
            if job_pool is not None:
                job_pool.submit(
                    orchestrator.run_task,
                    intake,
                    write_key=resolved_write_key(intake, orchestrator),
                )
            else:
                receipts.append(orchestrator.run_task(intake))
            _mark_queue(store, qid, applied=True)
        except Exception:
            continue
    return receipts


def _mark_queue(store: Any, queue_id: str, *, applied: bool) -> None:
    qid = (queue_id or "").strip()
    if not qid or store is None:
        return
    writer = getattr(store, "mark_inbound_applied" if applied else "mark_inbound_dropped", None)
    if callable(writer):
        try:
            writer(qid)
        except Exception:
            pass


def _post_queued_ack(discord: Any, channel_id: str, thread_id: Optional[str]) -> None:
    try:
        send = getattr(discord, "send_message", None)
        if callable(send):
            send(
                channel_id,
                "Queued. Will apply when this cook can take it.",
                thread_id=thread_id,
            )
    except Exception:
        pass


def _tick_host_liveness_best_effort(
    discord: Any,
    store: Any,
    *,
    channel_id: str,
    workspace_id: str,
    workspace: Optional[Path],
) -> None:
    """Phone-visible host digest on listen poll (debounced). Best-effort."""

    if workspace is None:
        return
    try:
        from agent_discord.host.liveness import tick_host_liveness

        tick_host_liveness(
            discord,
            workspace=Path(workspace),
            channel_id=channel_id,
            store=store,
            workspace_id=workspace_id,
        )
    except Exception:
        pass
    _tick_status_digest_best_effort(
        discord,
        store,
        channel_id=channel_id,
        workspace_id=workspace_id,
        workspace=workspace,
    )
    _tick_rich_presence_best_effort(
        store,
        channel_id=channel_id,
        workspace_id=workspace_id,
    )


def _tick_status_digest_best_effort(
    discord: Any,
    store: Any,
    *,
    channel_id: str,
    workspace_id: str,
    workspace: Optional[Path],
    force: bool = False,
) -> None:
    """P2.7 RO dashboard snapshot → Discord (debounced). Never mutates power."""

    if workspace is None:
        return
    try:
        from agent_discord.host.status_digest import tick_status_digest

        tick_status_digest(
            discord,
            workspace=Path(workspace),
            channel_id=channel_id,
            store=store,
            workspace_id=workspace_id,
            force=force,
        )
    except Exception:
        pass


def _tick_rich_presence_best_effort(
    store: Any,
    *,
    channel_id: str,
    workspace_id: str = "",
    armed: Optional[bool] = None,
) -> None:
    """Mac Rich Presence (Band B). Fail soft; independent of bot gateway."""

    try:
        from agent_discord.host.presence import tick_rich_presence

        tick_rich_presence(
            store,
            channel_id=channel_id,
            workspace_id=workspace_id,
            armed=armed,
        )
    except Exception:
        pass


def _follow_thread_id(
    message: DiscordMessage,
    thread_id: Optional[str],
    orchestrator: Any,
    job_pool: Optional[Any],
) -> Optional[str]:
    """Prefer an explicit thread, else a channel that is itself a live job thread."""

    follow = (message.thread_id or thread_id or "").strip() or None
    if follow:
        return follow
    channel = (message.channel_id or "").strip()
    if channel and _thread_has_running_job(orchestrator, job_pool, channel):
        return channel
    return None


def _running_run_id(orchestrator: Any, job_pool: Optional[Any], thread_id: str) -> Optional[str]:
    tid = (thread_id or "").strip()
    if not tid:
        return None
    finder = getattr(orchestrator, "running_run_for_thread", None)
    if callable(finder):
        try:
            found = finder(tid)
        except Exception:
            found = None
        if found:
            return str(found)
    if job_pool is not None:
        finder = getattr(job_pool, "run_id_for_thread", None)
        if callable(finder):
            try:
                found = finder(tid)
            except Exception:
                found = None
            if found:
                return str(found)
    return None


def _thread_has_running_job(
    orchestrator: Any,
    job_pool: Optional[Any],
    thread_id: str,
) -> bool:
    if _running_run_id(orchestrator, job_pool, thread_id):
        return True
    if job_pool is None:
        return False
    probe = getattr(job_pool, "is_thread_live", None)
    if not callable(probe):
        return False
    try:
        return bool(probe(thread_id))
    except Exception:
        return False


def _wait_for_run_id(
    orchestrator: Any,
    job_pool: Optional[Any],
    thread_id: str,
) -> Optional[str]:
    found = _running_run_id(orchestrator, job_pool, thread_id)
    if found:
        return found
    if job_pool is None:
        return None
    probe = getattr(job_pool, "is_thread_live", None)
    if not callable(probe):
        return None
    try:
        live = bool(probe(thread_id))
    except Exception:
        live = False
    if not live:
        return None
    for _ in range(15):
        time.sleep(0.02)
        found = _running_run_id(orchestrator, job_pool, thread_id)
        if found:
            return found
        try:
            if not probe(thread_id):
                break
        except Exception:
            break
    return None



def _post_voice_whisper_miss(
    discord: Any, channel_id: str, thread_id: Optional[str]
) -> None:
    """Spoken Done when a voice memo arrives without a usable local whisper."""

    try:
        from agent_discord.discord.voice import available as whisper_available
    except Exception:
        whisper_available = lambda **_kw: False  # noqa: E731
    if whisper_available():
        body = (
            "Heard the voice memo, but transcription came back empty. "
            "Retry the memo or paste the ask as text."
        )
    else:
        body = (
            "Heard the voice memo, but no local whisper CLI is on PATH "
            "(whisper-cli / whisper.cpp / whisper). Install one on the host, then retry."
        )
    try:
        send = getattr(discord, "send_message", None)
        if callable(send):
            send(channel_id, body, thread_id=thread_id)
    except Exception:
        pass


def _post_steer_miss(discord: Any, channel_id: str, thread_id: Optional[str]) -> None:
    try:
        send = getattr(discord, "send_message", None)
        if callable(send):
            send(channel_id, "Could not steer this run.", thread_id=thread_id)
    except Exception:
        pass


def _steer_running_job(
    orchestrator: Any,
    discord: Any,
    job_pool: Optional[Any],
    *,
    text: str,
    channel_id: str,
    thread_id: str,
    notify_miss: bool = True,
    operator_id: str = "",
) -> bool:
    """Join the live worker. Never submit a sibling job."""

    run_id = _wait_for_run_id(orchestrator, job_pool, thread_id)
    steerer = getattr(orchestrator, "steer", None)
    ok = False
    if callable(steerer) and run_id:
        try:
            ok = bool(steerer(run_id, text, operator_id=operator_id))
        except TypeError:
            # Older backends without operator_id kwarg.
            try:
                ok = bool(steerer(run_id, text))
            except Exception:
                ok = False
        except Exception:
            ok = False
    if ok and run_id:
        _maybe_post_dual_steer_note(
            orchestrator, discord, channel_id=channel_id, thread_id=thread_id, run_id=run_id
        )
    if not ok and notify_miss:
        _post_steer_miss(discord, channel_id, thread_id)
    return ok


def _maybe_post_dual_steer_note(
    orchestrator: Any,
    discord: Any,
    *,
    channel_id: str,
    thread_id: str,
    run_id: str,
) -> None:
    """One quiet dual-op conflict NOTE (Wave 6 P1a). No storm."""

    noter = getattr(orchestrator, "dual_steer_note_if_needed", None)
    if not callable(noter):
        return
    try:
        body = (noter(run_id) or "").strip()
    except Exception:
        body = ""
    if not body:
        return
    try:
        from agent_discord.orchestration.cards import note_card, send_card

        send_card(
            discord,
            channel_id,
            note_card(body),
            thread_id=thread_id or None,
        )
    except Exception:
        try:
            send = getattr(discord, "send_message", None)
            if callable(send):
                send(channel_id, body, thread_id=thread_id or None)
        except Exception:
            pass

def _workspace_from(orchestrator: Any) -> Optional[Path]:
    raw = getattr(orchestrator, "workspace", None)
    return Path(raw) if raw is not None else None


def _maybe_absorb_jishaku(
    message: DiscordMessage,
    *,
    discord: Any,
    store: Any,
    channel_id: str,
    thread_id: Optional[str],
    env: Optional[Mapping[str, str]],
) -> bool:
    """Intercept ``jsk`` / ``jishaku`` only when ``DISCORD_OS_JISHAKU=1``."""

    try:
        from agent_discord.host.jishaku import (
            absorb_jishaku_command,
            is_jishaku_command,
            jishaku_flag_on,
        )
    except Exception:
        return False
    if not jishaku_flag_on(env):
        return False
    if not is_jishaku_command(message.content or ""):
        return False
    _claim_inbound(store, discord, message, channel_id)
    absorb_jishaku_command(
        message,
        discord=discord,
        store=store,
        channel_id=channel_id,
        thread_id=thread_id,
        env=env,
        role_ids=_author_role_ids(message),
    )
    return True


def _absorb_connect(
    message: DiscordMessage,
    *,
    discord: Any,
    orchestrator: Any,
    channel_id: str,
    thread_id: Optional[str],
    workspace: Optional[Path],
    env: Optional[Mapping[str, str]],
) -> None:
    store = getattr(orchestrator, "store", None)
    if store is not None and message.message_id:
        store.claim_inbound_message(message.message_id, channel_id)
    observe = getattr(discord, "observe_message_id", None)
    if callable(observe) and message.message_id:
        try:
            observe(message.message_id)
        except Exception:
            pass
    parsed = parse_connect_command(message.content or "")
    delete_ok = True
    if parsed.secret and message.message_id:
        try:
            discord.delete_message(channel_id, message.message_id)
        except Exception:
            delete_ok = False
    if workspace is None:
        return
    result = handle_connect_message(
        message.content or "",
        workspace=workspace,
        env=env,
        delete_ok=delete_ok,
    )
    if result.card:
        send_card(
            discord,
            channel_id,
            connect_card(
                provider=result.provider,
                fingerprint=result.fingerprint,
                source=result.source,
                ticket=result.ticket,
                error=result.error,
            ),
            thread_id=thread_id,
        )


def _absorb_open(
    message: DiscordMessage,
    *,
    discord: Any,
    orchestrator: Any,
    channel_id: str,
    thread_id: Optional[str],
    roots: Sequence[Path],
    runner: Any,
    browser_open: Any,
) -> None:
    store = getattr(orchestrator, "store", None)
    if store is not None and message.message_id:
        store.claim_inbound_message(message.message_id, channel_id)
    observe = getattr(discord, "observe_message_id", None)
    if callable(observe) and message.message_id:
        try:
            observe(message.message_id)
        except Exception:
            pass
    result = handle_open_message(
        message.content or "",
        roots=list(roots),
        runner=runner,
        browser_open=browser_open,
    )
    if result.card:
        send_card(
            discord,
            channel_id,
            open_card(
                surface=result.surface,
                target=result.target,
                error=result.error,
                dest=result.dest,
                link_url=result.link_url,
            ),
            thread_id=thread_id,
        )


def _channel_is_armed(store: Any, channel_id: str) -> bool:
    reader = getattr(store, "host_is_armed", None)
    if not callable(reader):
        return True
    return bool(reader(channel_id, default=True))


def _claim_inbound(store: Any, discord: Any, message: DiscordMessage, channel_id: str) -> bool:
    claimed = True
    if store is not None and message.message_id:
        claim = getattr(store, "claim_inbound_message", None)
        if callable(claim):
            try:
                claimed = bool(claim(message.message_id, channel_id))
            except Exception:
                claimed = True
    if not claimed:
        return False
    observe = getattr(discord, "observe_message_id", None)
    if callable(observe) and message.message_id:
        try:
            observe(message.message_id)
        except Exception:
            pass
    return True


def _absorb_power(
    message: DiscordMessage,
    *,
    discord: Any,
    orchestrator: Any,
    channel_id: str,
    thread_id: Optional[str],
) -> None:
    store = getattr(orchestrator, "store", None)
    _claim_inbound(store, discord, message, channel_id)
    parsed = parse_power_command(message.content or "")
    if parsed.action == "on":
        from agent_discord.orchestration.service import seed_owner_if_empty

        seed_owner_if_empty(store, message.author_id)
    writer = getattr(store, "set_host_control", None)
    if parsed.action in {"on", "off"} and callable(writer):
        writer(channel_id, armed=parsed.action == "on")
    publish_host_card(discord, store, channel_id, thread_id=thread_id)
    # P2.7: /status and On push RO dashboard facts to Discord (phone). Read-only.
    if parsed.action in {"on", "status"}:
        ws = _workspace_from_store_or_meta(store, discord)
        _tick_status_digest_best_effort(
            discord,
            store,
            channel_id=channel_id,
            workspace_id=str(getattr(orchestrator, "workspace_id", None) or "default"),
            workspace=ws,
            force=True,
        )



def _post_host_deny(
    discord: Any, channel_id: str, thread_id: Optional[str], body: str
) -> None:
    try:
        send = getattr(discord, "send_message", None)
        if callable(send):
            send(channel_id, body, thread_id=thread_id)
    except Exception:
        pass


def _absorb_bind(
    message: DiscordMessage,
    *,
    discord: Any,
    orchestrator: Any,
    channel_id: str,
    workspace_id: str,
    thread_id: Optional[str],
) -> None:
    store = getattr(orchestrator, "store", None)
    _claim_inbound(store, discord, message, channel_id)
    from agent_discord.host.runners import (
        HostAllowlistError,
        bind_channel_host,
        is_host_bind_command,
        load_host_allowlist,
        parse_host_bind_command,
    )

    if is_host_bind_command(message.content or ""):
        host_id = parse_host_bind_command(message.content or "")
        allowlist = load_host_allowlist()
        try:
            chosen_host = bind_channel_host(
                store,
                workspace_id=workspace_id,
                channel_id=channel_id,
                host_id=host_id,
                allowlist=allowlist,
            )
        except HostAllowlistError as exc:
            _post_host_deny(discord, channel_id, thread_id, str(exc.spoken))
            publish_host_card(
                discord,
                store,
                channel_id,
                thread_id=thread_id,
                realm=_realm_name(store, channel_id, workspace_id),
            )
            return
        publish_host_card(
            discord,
            store,
            channel_id,
            thread_id=thread_id,
            realm=_realm_name(store, channel_id, workspace_id) or chosen_host.id,
        )
        return

    name = parse_bind_command(message.content or "")
    repos = list(getattr(orchestrator, "host_repos", None) or load_host_repos())
    chosen = None
    if is_memory_bind(name):
        bind_memory_channel(
            store,
            workspace_id=workspace_id,
            channel_id=channel_id,
        )
    elif name:
        chosen = bind_channel_realm(
            store,
            workspace_id=workspace_id,
            channel_id=channel_id,
            name=name,
            repos=repos,
        )
        _maybe_mark_forum_on_bind(
            discord,
            store,
            workspace_id=workspace_id,
            channel_id=channel_id,
            thread_id=thread_id,
            require_forum=False,
        )
    realm = ""
    if chosen is not None:
        realm = chosen.name
    elif name and not is_memory_bind(name):
        realm = name
    publish_host_card(
        discord,
        store,
        channel_id,
        thread_id=thread_id,
        realm=realm or _realm_name(store, channel_id, workspace_id),
    )



def _maybe_mark_forum_on_bind(
    discord: Any,
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    thread_id: Optional[str],
    require_forum: bool = False,
) -> None:
    """Forum-as-realm: auto-mark GUILD_FORUM binds; Need + refuse mark on ACL miss."""

    from agent_discord.host.forum_realm import ForumRealmError, validate_and_mark_forum_bind

    token = ""
    for attr in ("bot_token", "token", "_token"):
        raw = getattr(discord, attr, None)
        if isinstance(raw, str) and raw.strip():
            token = raw.strip()
            break
    provider = getattr(discord, "provider", None)
    if not token and provider is not None:
        for attr in ("bot_token", "token", "_token"):
            raw = getattr(provider, attr, None)
            if isinstance(raw, str) and raw.strip():
                token = raw.strip()
                break
    if not token:
        # No REST token on this facade (fake tests) — skip probe.
        return
    try:
        validate_and_mark_forum_bind(
            store,
            workspace_id=workspace_id,
            channel_id=channel_id,
            token=token,
            require_forum=require_forum,
        )
    except ForumRealmError as exc:
        _post_forum_need(discord, channel_id, thread_id, exc.spoken)


def _post_forum_need(
    discord: Any, channel_id: str, thread_id: Optional[str], spoken: str
) -> None:
    body = (spoken or "").strip() or "Need: forum-as-realm — refused."
    send = getattr(discord, "send_message", None)
    if not callable(send):
        return
    try:
        send(channel_id, body, thread_id=thread_id)
    except TypeError:
        try:
            send(channel_id, body)
        except Exception:
            pass
    except Exception:
        pass



def _realm_name(store: Any, channel_id: str, workspace_id: str = "default") -> str:
    from agent_discord.host.realms import binding_metadata

    reader = getattr(store, "get_binding", None)
    if not callable(reader):
        return ""
    try:
        return str(binding_metadata(reader(workspace_id, channel_id)).get("repo") or "")
    except Exception:
        return ""



def _workspace_from_store_or_meta(store: Any, discord: Any = None) -> Optional[Path]:
    """Best-effort workspace Path for HOST Need ranking."""

    _ = discord
    for attr in ("workspace", "_workspace"):
        raw = getattr(store, attr, None) if store is not None else None
        if raw:
            try:
                return Path(raw)
            except Exception:
                pass
    db = getattr(store, "path", None) or getattr(store, "db_path", None)
    if db:
        try:
            return Path(db).parent
        except Exception:
            pass
    return None


def publish_host_card(
    discord: Any,
    store: Any,
    channel_id: str,
    *,
    thread_id: Optional[str] = None,
    realm: str = "",
) -> None:
    """Post or edit the HOST card. Best-effort — never raise on the listen path."""

    from agent_discord.host.panel import host_panel_components

    armed = _channel_is_armed(store, channel_id)
    spend = 0.0
    spend_known = False
    cap = None
    halted = False
    write_gate = False
    try:
        from agent_discord.orchestration.service import spend_cost_known

        spend = session_spend_usd(store)
        spend_known = spend_cost_known(store)
        cap = spend_cap_usd(store)
        halted = is_spend_halted(store)
        write_gate = writes_need_approval(store)
    except Exception:
        spend = 0.0
        cap = None
        halted = False
        write_gate = False
    jobs: list[dict] = []
    lister = getattr(store, "list_recent_jobs", None)
    if callable(lister):
        try:
            jobs = list(lister(channel_id, limit=5))
        except Exception:
            jobs = []
    try:
        from agent_discord.host.liveness import (
            last_digest_from_state,
            merge_host_need_jobs,
            resolve_digest_for_panel,
        )

        ws = _workspace_from_store_or_meta(store, discord)
        digest = None
        if ws is not None:
            digest = resolve_digest_for_panel(
                workspace=ws, store=store, channel_id=channel_id
            )
            if digest is None:
                digest = last_digest_from_state(ws)
        jobs = merge_host_need_jobs(jobs, digest)
    except Exception:
        pass
    last_job = ""
    try:
        from agent_discord.orchestration.job_briefing import briefing_line

        if jobs:
            last_job = briefing_line(jobs[0])
    except Exception:
        last_job = ""
    avatar_url = ""
    token = str(getattr(getattr(discord, "provider", None), "_bot_token", "") or "")
    if token:
        try:
            from agent_discord.discord.rest import bot_avatar_url, fetch_bot_identity

            avatar_url = bot_avatar_url(fetch_bot_identity(token=token))
        except Exception:
            avatar_url = ""
    from agent_discord.host.memory import channel_is_memory

    github = ""
    try:
        from agent_discord.host.github import github_host_row

        github = github_host_row()
    except Exception:
        github = "sign-in"
    card = host_card(
        armed=armed,
        channel_id=channel_id,
        avatar_url=avatar_url,
        spend_usd=spend,
        cap_usd=cap,
        halted=halted,
        write_gate=write_gate,
        realm=realm or _realm_name(store, channel_id),
        bank=channel_is_memory(store, channel_id),
        github=github,
        last_job=last_job,
    )
    control = None
    reader = getattr(store, "get_host_control", None)
    if callable(reader):
        try:
            control = reader(channel_id)
        except Exception:
            control = None
    card_id = str((control or {}).get("card_message_id") or "")
    paired = False
    try:
        paired = bool(operators_configured(store))
    except Exception:
        paired = False
    buttons = host_panel_components(
        armed,
        jobs=jobs,
        write_gate=write_gate,
        paired=paired,
    )
    if card_id:
        try:
            edit_card(discord, channel_id, card_id, card, components=buttons)
            return
        except Exception:
            pass
    try:
        posted = send_card(
            discord,
            channel_id,
            card,
            thread_id=thread_id,
            components=buttons,
        )
    except Exception:
        return
    message_id = ""
    if isinstance(posted, list) and posted:
        message_id = str(getattr(posted[0], "message_id", "") or "")
    else:
        message_id = str(getattr(posted, "message_id", "") or "")
    writer = getattr(store, "set_host_control", None)
    if message_id and callable(writer):
        try:
            writer(channel_id, card_message_id=message_id)
        except Exception:
            pass


def _collab_intake(message: DiscordMessage, discord: Any) -> tuple[str, dict[str, Any], bool]:
    """Voice + thread-history context. Fetches bot-visible attachment bytes only."""

    meta: dict[str, Any] = {}
    if isinstance(message.metadata, Mapping):
        meta.update(dict(message.metadata))
    mentioned = "@" in (message.content or "")
    meta["mentioned"] = mentioned
    history: list[str] = []
    thread_id = message.thread_id
    if thread_id:
        reader = getattr(discord, "read_messages", None)
        if callable(reader):
            try:
                recent = reader(message.channel_id, limit=8, thread_id=thread_id)
                history = [
                    str(getattr(item, "content", "") or "").strip()
                    for item in list(recent or [])
                    if str(getattr(item, "content", "") or "").strip()
                ][-6:]
            except Exception:
                history = []
    if history:
        meta["thread_history"] = history
        meta["reading"] = f"thread {thread_id}"
    try:
        from agent_discord.discord.voice import (
            detect_voice_intent,
            materialize_voice_intake,
            spoken_command_to_intake,
        )
    except Exception:
        return "", meta, False
    try:
        intent = detect_voice_intent(message)
    except Exception:
        return "", meta, False
    if not intent:
        return "", meta, False
    if intent.get("kind") == "voice_attachment" and not (
        meta.get("transcript") or meta.get("voice_transcript")
    ):
        transcript = ""
        try:
            transcript = materialize_voice_intake(message, discord)
        except Exception:
            transcript = ""
        if not transcript:
            return "", meta, True
        meta["voice_transcript"] = transcript
        return spoken_command_to_intake(transcript) or transcript, meta, False
    transcript = str(intent.get("intake") or intent.get("transcript") or "")
    if not transcript and (meta.get("transcript") or meta.get("voice_transcript")):
        transcript = spoken_command_to_intake(
            str(meta.get("transcript") or meta.get("voice_transcript") or "")
        )
    return transcript.strip(), meta, False


def _author_role_ids(message: DiscordMessage) -> list[str]:
    meta = message.metadata if isinstance(message.metadata, Mapping) else {}
    raw = meta.get("author_roles") or meta.get("role_ids") or ()
    if isinstance(raw, str):
        return [bit for bit in raw.replace(",", " ").split() if bit]
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw if str(item).strip()]
    return []


def _absorb_schedule(
    message: DiscordMessage,
    *,
    discord: Any,
    store: Any,
    channel_id: str,
    workspace_id: str,
    every_s: int,
    prompt: str,
    thread_id: Optional[str],
) -> None:
    _claim_inbound(store, discord, message, channel_id)
    if not author_may_dispatch(store, message.author_id, role_ids=_author_role_ids(message)):
        return
    writer = getattr(store, "add_schedule", None)
    if not callable(writer):
        return
    try:
        writer(
            channel_id=channel_id,
            workspace_id=workspace_id,
            prompt=prompt,
            every_s=every_s,
            created_by=str(message.author_id or ""),
        )
    except Exception:
        return
    try:
        send_card(
            discord,
            channel_id,
            host_card(armed=_channel_is_armed(store, channel_id), channel_id=channel_id),
            thread_id=thread_id,
        )
    except Exception:
        pass


def _fire_due_schedules(
    orchestrator: Any,
    store: Any,
    *,
    channel_id: str,
    workspace_id: str,
    guild_id: Optional[str],
    thread_id: Optional[str],
    discord: Any = None,
) -> list[RunReceipt]:
    """Fire due schedules while HOST is armed.

    While Off (disarmed), overdue rows are **not** flooded as jobs. Instead we
    bump each schedule forward and post at most one Catch-up briefing with
    ``skipped_while_disarmed`` so On does not storm.
    """

    if store is None or is_spend_halted(store, workspace_id):
        return []
    due_reader = getattr(store, "due_schedules", None)
    bumper = getattr(store, "bump_schedule", None)
    if not callable(due_reader):
        return []
    now_ms = int(time.time() * 1000)
    try:
        due = list(due_reader(now_ms, channel_id))
    except Exception:
        return []
    if not due:
        return []

    if not _channel_is_armed(store, channel_id):
        _catch_up_skipped_while_disarmed(
            discord if discord is not None else getattr(orchestrator, "discord", None),
            store,
            due,
            channel_id=channel_id,
            thread_id=thread_id,
            now_ms=now_ms,
            bumper=bumper,
        )
        return []

    from agent_discord.orchestration.board_catchup import is_board_digest_prompt

    receipts: list[RunReceipt] = []
    for row in due:
        prompt = str(row.get("prompt") or "").strip()
        schedule_id = str(row.get("schedule_id") or "")
        every_s = int(row.get("every_s") or 0)
        if not prompt or not schedule_id:
            continue
        created_by = str(row.get("created_by") or "")
        if created_by and not author_may_dispatch(store, created_by):
            continue
        # Wave 4 P0: board digest schedules post conflict scan without a cook.
        if is_board_digest_prompt(prompt):
            _post_board_digest(
                discord if discord is not None else getattr(orchestrator, "discord", None),
                store,
                channel_id=channel_id,
                thread_id=thread_id,
                prompt=prompt,
            )
            if callable(bumper) and every_s > 0:
                try:
                    bumper(schedule_id, now_ms + every_s * 1000)
                except Exception:
                    pass
            continue
        try:
            ask_text = prompt
            overnight = False
            try:
                from agent_discord.orchestration.overnight_pack import (
                    compose_overnight_brief_ask,
                    is_overnight_brief_prompt,
                )

                overnight = is_overnight_brief_prompt(prompt)
                if overnight:
                    ask_text = compose_overnight_brief_ask(
                        prompt,
                        store=store,
                        channel_id=channel_id,
                        workspace_id=str(row.get("workspace_id") or workspace_id),
                    )
            except Exception:
                ask_text = prompt
                overnight = False
            receipts.append(
                orchestrator.run_task(
                    TaskIntake(
                        text=ask_text,
                        channel_id=channel_id,
                        workspace_id=str(row.get("workspace_id") or workspace_id),
                        guild_id=guild_id,
                        thread_id=thread_id,
                        requester_id=created_by or None,
                        metadata={
                            "scheduled": True,
                            "schedule_id": schedule_id,
                            "overnight_brief": overnight,
                        },
                    )
                )
            )
        except Exception:
            continue
        if callable(bumper) and every_s > 0:
            try:
                bumper(schedule_id, now_ms + every_s * 1000)
            except Exception:
                pass
    return receipts


def _catch_up_skipped_while_disarmed(
    discord: Any,
    store: Any,
    due: list,
    *,
    channel_id: str,
    thread_id: Optional[str],
    now_ms: int,
    bumper: Any,
) -> None:
    """One Catch-up briefing; bump due schedules so Off→On does not storm.

    Wave 4: also surface ADR/PR board conflicts so cron catch-up reduces
    coordination tax without a job storm.
    """

    from agent_discord.orchestration.board_catchup import (
        collect_channel_conflicts,
        format_board_catchup,
    )

    skipped: list[str] = []
    for row in due:
        prompt = str(row.get("prompt") or "").strip()
        schedule_id = str(row.get("schedule_id") or "")
        every_s = int(row.get("every_s") or 0)
        if not schedule_id:
            continue
        label = prompt if prompt else schedule_id
        if len(label) > 80:
            label = label[:77] + "..."
        skipped.append(label)
        if callable(bumper) and every_s > 0:
            try:
                bumper(schedule_id, now_ms + every_s * 1000)
            except Exception:
                pass
        elif callable(bumper):
            # No interval — push a day so it does not remain perpetually due.
            try:
                bumper(schedule_id, now_ms + 86_400_000)
            except Exception:
                pass
    if not skipped:
        return
    conflicts = []
    try:
        conflicts = collect_channel_conflicts(store, channel_id)
    except Exception:
        conflicts = []
    body = format_board_catchup(skipped_labels=skipped, conflicts=conflicts)
    send = getattr(discord, "send_message", None) if discord is not None else None
    if not callable(send):
        return
    try:
        send(channel_id, body, thread_id=thread_id)
    except TypeError:
        try:
            send(channel_id, body)
        except Exception:
            pass
    except Exception:
        pass


def _post_board_digest(
    discord: Any,
    store: Any,
    *,
    channel_id: str,
    thread_id: Optional[str],
    prompt: str = "",
) -> None:
    """Armed board-digest schedule: conflict scan only (no cook storm)."""

    from agent_discord.orchestration.board_catchup import (
        collect_channel_conflicts,
        format_board_catchup,
    )

    conflicts = []
    try:
        conflicts = collect_channel_conflicts(store, channel_id)
    except Exception:
        conflicts = []
    pushed: list[str] = []
    if conflicts:
        pushed.append("review shared ADR/PR lanes before next implement")
    elif (prompt or "").strip():
        pushed.append("board quiet — no shared ADR/PR refs on Need/Live")
    body = format_board_catchup(conflicts=conflicts, pushed=pushed)
    send = getattr(discord, "send_message", None) if discord is not None else None
    if not callable(send):
        return
    try:
        send(channel_id, body, thread_id=thread_id)
    except TypeError:
        try:
            send(channel_id, body)
        except Exception:
            pass
    except Exception:
        pass
