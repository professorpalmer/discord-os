"""Discord channels as a durable think-tank.

Other rooms hold state the way a group chat does. Hermes persist-then-settle
plus GrokBot's always-on stitch — own code, Discord is the store.

A **brain lake** is the recall half of the same store: strategy docs,
a transcripts channel and journal rows bound onto channel binding metadata,
formatted as the ``[brain-lake]`` worker prompt inject and the
``discord-os brain show`` pack. Single-host SQLite — not Durable Objects.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from agent_discord.contracts import DiscordMessage
from agent_discord.host.realms import binding_metadata


MEMORY_NAMES = frozenset({"memory", "bank", "tank", "think-tank", "thinktank"})
MEMORY_PREFIXES = frozenset(
    {"/memory", "!memory", "memory", "/bank", "!bank", "bank"}
)


def is_memory_bind(name: str) -> bool:
    return (name or "").strip().lower() in MEMORY_NAMES


def bind_memory_channel(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    label: str = "",
) -> bool:
    writer = getattr(store, "merge_binding_metadata", None)
    if not callable(writer) or not channel_id:
        return False
    updates = {"memory": True}
    if label:
        updates["memory_label"] = label
    writer(workspace_id, channel_id, updates)
    return True


def seed_memory_channels(
    store: Any,
    *,
    workspace_id: str,
    env: Optional[Mapping[str, str]] = None,
) -> tuple[str, ...]:
    source = dict(os.environ if env is None else env)
    ids = _split_ids(source.get("DISCORD_OS_MEMORY") or "")
    for channel_id in ids:
        bind_memory_channel(store, workspace_id=workspace_id, channel_id=channel_id)
    return ids


def memory_channel_ids(
    store: Any,
    *,
    workspace_id: str = "default",
    env: Optional[Mapping[str, str]] = None,
) -> tuple[str, ...]:
    seen: list[str] = []
    known = set()
    source = dict(os.environ if env is None else env)
    for channel_id in _split_ids(source.get("DISCORD_OS_MEMORY") or ""):
        if channel_id not in known:
            seen.append(channel_id)
            known.add(channel_id)
    lister = getattr(store, "list_bindings", None)
    if callable(lister):
        for row in lister(workspace_id) or ():
            meta = binding_metadata(row)
            channel_id = str(row.get("channel_id") or "").strip()
            if channel_id and meta.get("memory") and channel_id not in known:
                seen.append(channel_id)
                known.add(channel_id)
    return tuple(seen)


def channel_is_memory(
    store: Any,
    channel_id: str,
    *,
    workspace_id: str = "default",
) -> bool:
    reader = getattr(store, "get_binding", None)
    if callable(reader) and bool(binding_metadata(reader(workspace_id, channel_id)).get("memory")):
        return True
    lister = getattr(store, "list_bindings", None)
    if not callable(lister):
        return False
    for row in lister() or ():
        if str(row.get("channel_id") or "") == channel_id and binding_metadata(row).get("memory"):
            return True
    return False


def recall_think_tank(
    discord: Any,
    store: Any,
    query: str,
    *,
    workspace_id: str = "default",
    limit_per: int = 8,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    channels = memory_channel_ids(store, workspace_id=workspace_id, env=env)
    if not channels:
        return ""
    blocks: list[str] = []
    needles = [part for part in (query or "").lower().split() if len(part) > 2][:8]
    for channel_id in channels:
        lines = _channel_lines(
            discord,
            channel_id,
            needles=needles,
            limit=limit_per,
        )
        recaller = getattr(store, "recall", None)
        if callable(recaller):
            try:
                for row in recaller(
                    workspace_id=workspace_id,
                    channel_id=channel_id,
                    query=query,
                    limit=limit_per,
                ):
                    if str(row.get("source") or "") != "think-tank":
                        continue
                    text = str(row.get("content") or "").strip()
                    if text and text not in lines:
                        lines.append(text[:240])
            except Exception:
                pass
        if not lines:
            continue
        blocks.append(f"#{channel_id}")
        blocks.extend(f"- {line}" for line in lines)
    return "\n".join(blocks)


def post_think_tank_note(
    discord: Any,
    channel_id: str,
    text: str,
    *,
    source_channel: str = "",
) -> Optional[DiscordMessage]:
    from agent_discord.orchestration.cards import note_card, send_card

    body = (text or "").strip()
    if not body or not channel_id:
        return None
    card = note_card(body, source_channel=source_channel)
    try:
        posted = send_card(discord, channel_id, card)
    except Exception:
        return None
    if isinstance(posted, list):
        return posted[0] if posted else None
    return posted


def settle_think_tank(
    discord: Any,
    store: Any,
    *,
    workspace_id: str,
    origin_channel: str,
    summary: str,
    env: Optional[Mapping[str, str]] = None,
) -> list[str]:
    text = (summary or "").strip()
    if not text:
        return []
    posted: list[str] = []
    for channel_id in memory_channel_ids(store, workspace_id=workspace_id, env=env):
        if channel_id == origin_channel:
            continue
        msg = post_think_tank_note(
            discord,
            channel_id,
            text,
            source_channel=origin_channel,
        )
        if msg is not None:
            posted.append(channel_id)
            remember = getattr(store, "remember", None)
            if callable(remember):
                try:
                    remember(
                        workspace_id=workspace_id,
                        channel_id=channel_id,
                        content=text[:500],
                        source="think-tank",
                        provenance={"origin": origin_channel},
                    )
                except Exception:
                    pass
    return posted


def memory_reach_block(
    store: Any = None,
    *,
    workspace_id: str = "default",
    env: Optional[Mapping[str, str]] = None,
) -> str:
    ids = memory_channel_ids(store, workspace_id=workspace_id, env=env) if store is not None else ()
    lines = [
        "Think-tank (Discord is the durable store):",
        "- Bound channels are memory. Use discord-os recall / note.",
    ]
    if ids:
        lines.append("- Memory channels: " + ", ".join(ids))
    return "\n".join(lines)


BRAIN_HONEST_LIMIT = (
    "single-host SQLite brain lake — not multi-host Durable Objects"
)


def bind_brain_lake(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    strategy_docs: str = "",
    transcripts_channel: str = "",
    journal: bool = True,
) -> dict[str, Any]:
    """Mark a channel binding as a brain lake (strategy / transcripts / journal)."""

    cid = (channel_id or "").strip()
    if not cid:
        raise ValueError("add brain needs --channel-id")
    docs = (strategy_docs or "").strip()
    if docs:
        path = Path(docs).expanduser()
        if not path.exists():
            raise ValueError(f"strategy docs path missing: {path}")
        docs = str(path.resolve())
    writer = getattr(store, "merge_binding_metadata", None)
    if not callable(writer):
        raise ValueError("store cannot merge binding metadata")
    transcripts = (transcripts_channel or "").strip()
    writer(
        workspace_id,
        cid,
        {
            "brain": True,
            "strategy_docs": docs,
            "transcripts_channel": transcripts,
            "journal": bool(journal),
        },
    )
    return {
        "kind": "brain",
        "channel_id": cid,
        "workspace_id": workspace_id,
        "strategy_docs": docs,
        "transcripts_channel": transcripts,
        "journal": bool(journal),
        "honest_limit": BRAIN_HONEST_LIMIT,
    }


def list_journal_notes(
    store: Any,
    *,
    workspace_id: str,
    limit: int = 6,
) -> list[str]:
    """Recent journal preference rows (kind=journal), then memory source journal:*."""

    notes: list[str] = []
    lister = getattr(store, "list_preferences", None)
    if callable(lister):
        try:
            rows = list(lister(workspace_id, kind="journal") or [])
        except TypeError:
            try:
                rows = [
                    r
                    for r in (lister(workspace_id) or [])
                    if str(r.get("kind") or "") == "journal"
                ]
            except Exception:
                rows = []
        except Exception:
            rows = []
        for row in rows:
            key = str(row.get("key") or "")
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            notes.append(f"{key}: {value}" if key else value)
            if len(notes) >= limit:
                return notes[:limit]
    recall = getattr(store, "recall", None)
    if callable(recall):
        try:
            hits = recall(
                workspace_id=workspace_id,
                channel_id="",
                query="journal",
                limit=limit,
            )
        except Exception:
            hits = []
        for hit in hits or []:
            if "journal" not in str(hit.get("source") or ""):
                continue
            content = str(hit.get("content") or "").strip()
            if content:
                notes.append(content)
            if len(notes) >= limit:
                break
    return notes[:limit]


def list_done_summaries(
    store: Any,
    *,
    channel_id: str = "",
    limit: int = 3,
) -> list[str]:
    """Recent Done job summaries with task/job ids for the recall pack."""

    if store is None:
        return []
    lister = getattr(store, "list_recent_jobs", None)
    if not callable(lister):
        return []
    try:
        rows = lister(channel_id or "", limit=max(12, limit * 4))
    except Exception:
        return []
    out: list[str] = []
    for row in rows or ():
        status = str(row.get("status") or "").strip().lower()
        if status not in {"completed", "succeeded", "done", "success"}:
            continue
        code = str(row.get("job_code") or row.get("task_id") or "").strip()
        summary = str(row.get("summary") or "").strip().replace("\n", " ")
        if not summary:
            continue
        clipped = summary if len(summary) <= 100 else summary[:97] + "..."
        out.append(f"{code}: {clipped}" if code else clipped)
        if len(out) >= limit:
            break
    return out


def list_plan_gallery(
    store: Any,
    *,
    workspace_id: str = "default",
    limit: int = 3,
) -> list[str]:
    """Recent kind=plan preference rows for the [plan-gallery] inject."""

    if store is None:
        return []
    lister = getattr(store, "list_preferences", None)
    if not callable(lister):
        return []
    try:
        rows = list(lister(workspace_id, kind="plan") or [])
    except TypeError:
        try:
            rows = [r for r in (lister(workspace_id) or []) if str(r.get("kind") or "") == "plan"]
        except Exception:
            return []
    except Exception:
        return []
    out: list[str] = []
    for row in rows:
        key = str(row.get("key") or "").strip()
        val = str(row.get("value") or "").strip().replace("\n", " ")
        if not val:
            continue
        clipped = val if len(val) <= 120 else val[:117] + "..."
        label = key.split(":")[-1][:12] if key else "plan"
        out.append(f"{label}: {clipped}")
        if len(out) >= limit:
            break
    return out


def record_plan_gallery(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    plan_text: str,
) -> str:
    """Persist an approved plan for later [plan-gallery] recall. Returns key."""

    import hashlib

    body = (plan_text or "").strip()
    if not body or store is None:
        return ""
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    cid = (channel_id or "").strip() or "ch"
    key = f"plan:{cid}:{digest}"
    setter = getattr(store, "set_preference", None)
    if not callable(setter):
        return ""
    clipped = body if len(body) <= 800 else body[:797] + "..."
    try:
        setter(workspace_id or "default", key, clipped, kind="plan")
    except Exception:
        return ""
    return key


def list_brain_cites(
    store: Any,
    *,
    workspace_id: str = "default",
    channel_id: str = "",
    limit: int = 6,
) -> list[str]:
    """Compact ARC-lite citation ids for brain show / recall pack."""

    cites: list[str] = []
    if store is None:
        return cites
    # Recent Done job codes (DOS-*).
    for item in list_done_summaries(store, channel_id=channel_id, limit=limit):
        code = str(item).split(":", 1)[0].strip()
        if code.upper().startswith("DOS-") and code not in cites:
            cites.append(code)
        if len(cites) >= limit:
            return cites[:limit]
    # Journal preference keys / ids.
    for note in list_journal_notes(store, workspace_id=workspace_id, limit=limit):
        key = str(note).split(":", 1)[0].strip()
        if key.startswith("journal"):
            tip = key if len(key) <= 40 else key[:37] + "..."
            if tip not in cites:
                cites.append(tip)
        if len(cites) >= limit:
            return cites[:limit]
    # Artifact sha8 from recent jobs when available.
    lister = getattr(store, "list_recent_jobs", None)
    if callable(lister):
        try:
            rows = list(lister(channel_id or "", limit=8) or [])
        except Exception:
            rows = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            sha = str(row.get("artifact_sha") or row.get("sha256") or "").strip()
            if len(sha) >= 8:
                tip = f"sha:{sha[:8]}"
                if tip not in cites:
                    cites.append(tip)
            if len(cites) >= limit:
                break
    return cites[:limit]


def clip_pack_text(text: str, *, max_bytes: int = 1800) -> str:
    raw = text or ""
    encoded = raw.encode("utf-8")
    if len(encoded) <= max_bytes:
        return raw
    # Keep head; avoid cutting mid-line when possible.
    trimmed = encoded[: max(0, max_bytes - 3)].decode("utf-8", errors="ignore")
    if "\n" in trimmed:
        trimmed = trimmed.rsplit("\n", 1)[0]
    return trimmed.rstrip() + "..."


def build_compact_recall_pack(
    binding: Optional[Mapping[str, Any]],
    *,
    store: Any = None,
    workspace_id: str = "default",
    channel_id: str = "",
    max_bytes: int = 1800,
    max_journal: int = 5,
    max_docs: int = 6,
    max_done: int = 3,
) -> str:
    """Budgeted MemGPT-style ``[brain-lake]`` recall pack for a bound channel."""

    meta = binding_metadata(binding or {})
    if not meta.get("brain"):
        return ""
    lines = ["[brain-lake]", "pack: compact-recall"]
    docs = str(meta.get("strategy_docs") or "").strip()
    if docs:
        lines.append(f"Strategy docs: {docs}")
        try:
            path = Path(docs)
            if path.is_dir():
                names = sorted(p.name for p in path.iterdir() if p.is_file())[:max_docs]
                if names:
                    lines.append("Docs: " + ", ".join(names))
            elif path.is_file():
                lines.append(f"Doc file: {path.name}")
        except OSError:
            pass
    transcripts = str(meta.get("transcripts_channel") or "").strip()
    if transcripts:
        lines.append(f"Transcripts channel: {transcripts}")
    if meta.get("journal") and store is not None:
        notes = list_journal_notes(store, workspace_id=workspace_id, limit=max_journal)
        if notes:
            lines.append("Journal:")
            for note in notes[:max_journal]:
                clipped = note if len(note) <= 140 else note[:137] + "..."
                lines.append(f"- {clipped}")
    if store is not None:
        dones = list_done_summaries(store, channel_id=channel_id, limit=max_done)
        if dones:
            lines.append("Recent Done:")
            for item in dones:
                lines.append(f"- {item}")
        plans = list_plan_gallery(store, workspace_id=workspace_id, limit=3)
        if plans:
            lines.append("[plan-gallery]")
            for item in plans:
                lines.append(f"- {item}")
        cites = list_brain_cites(
            store,
            workspace_id=workspace_id,
            channel_id=channel_id,
            limit=6,
        )
        if cites:
            lines.append("Cites: " + " · ".join(cites))
    lines.append(f"Honest limit: {BRAIN_HONEST_LIMIT}.")
    return clip_pack_text("\n".join(lines), max_bytes=max_bytes)


def _channel_lines(
    discord: Any,
    channel_id: str,
    *,
    needles: Sequence[str],
    limit: int,
) -> list[str]:
    reader = getattr(discord, "read_messages", None)
    if not callable(reader):
        return []
    try:
        messages = list(reader(channel_id, limit=max(limit * 3, 12), skip_duplicates=False))
    except Exception:
        return []
    usable: list[str] = []
    matched: list[str] = []
    for message in messages:
        content = (getattr(message, "content", "") or "").strip()
        if not content:
            continue
        embeds = None
        components = None
        meta = getattr(message, "metadata", None)
        if isinstance(meta, dict):
            embeds = meta.get("embeds")
            components = meta.get("components")
        if _skip_harness_line(content, embeds, components):
            continue
        clipped = content[:240]
        usable.append(clipped)
        hay = content.lower()
        if needles and any(needle in hay for needle in needles):
            matched.append(clipped)
        if len(usable) >= limit and (not needles or len(matched) >= limit):
            break
    if matched:
        return matched[:limit]
    return usable[:limit]


def _skip_harness_line(content: str, embeds: Any, components: Any) -> bool:
    text = (content or "").strip()
    if text.startswith("**Card**") or text.startswith("**Receipt**"):
        return True
    _ = embeds
    _ = components
    return False


def _split_ids(raw: str) -> tuple[str, ...]:
    items = []
    seen = set()
    for part in (raw or "").replace(";", ",").split(","):
        channel_id = part.strip()
        if channel_id and channel_id not in seen:
            items.append(channel_id)
            seen.add(channel_id)
    return tuple(items)
