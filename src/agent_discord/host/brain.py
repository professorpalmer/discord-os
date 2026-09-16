"""Per-DRI brain lake bind — single-host SQLite, not a Durable Objects clone.

Binds strategy docs path + transcripts channel + journal flag onto the channel
binding metadata, then formats a prompt inject block. Compose with desk-pack /
memory / wiki / github — never a second JobPool.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from agent_discord.host.realms import binding_metadata


def bind_brain(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    dri: str,
    strategy_docs: str = "",
    transcripts_channel: str = "",
    journal: bool = True,
) -> dict[str, Any]:
    """Mark channel binding as a DRI brain workspace."""

    cid = (channel_id or "").strip()
    dri_s = (dri or "").strip()
    if not cid:
        raise ValueError("add brain needs --channel-id")
    if not dri_s:
        raise ValueError("add brain needs --dri")
    docs = (strategy_docs or "").strip()
    if docs:
        path = Path(docs).expanduser()
        if not path.exists():
            raise ValueError(f"strategy docs path missing: {path}")
        docs = str(path.resolve())
    transcripts = (transcripts_channel or "").strip()
    writer = getattr(store, "merge_binding_metadata", None)
    if not callable(writer):
        raise ValueError("store cannot merge binding metadata")
    updates = {
        "brain": True,
        "dri": dri_s,
        "strategy_docs": docs,
        "transcripts_channel": transcripts,
        "journal": bool(journal),
    }
    writer(workspace_id, cid, updates)
    return {
        "kind": "brain",
        "channel_id": cid,
        "workspace_id": workspace_id,
        "dri": dri_s,
        "strategy_docs": docs,
        "transcripts_channel": transcripts,
        "journal": bool(journal),
        "honest_limit": "single-host SQLite brain — not multi-host / Durable Objects",
    }


def brain_from_binding(binding: Mapping[str, Any] | None) -> dict[str, Any]:
    meta = binding_metadata(binding or {})
    if not meta.get("brain"):
        return {}
    return {
        "dri": str(meta.get("dri") or "").strip(),
        "strategy_docs": str(meta.get("strategy_docs") or "").strip(),
        "transcripts_channel": str(meta.get("transcripts_channel") or "").strip(),
        "journal": bool(meta.get("journal")),
    }


def list_journal_notes(
    store: Any,
    *,
    workspace_id: str,
    dri: str = "",
    limit: int = 6,
) -> list[str]:
    """Recent journal preference rows (kind=journal) and/or memory source journal:*."""

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
        dri_l = (dri or "").strip().lower()
        for row in rows:
            key = str(row.get("key") or "")
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            if dri_l and dri_l not in key.lower() and not key.lower().startswith("journal"):
                # still allow generic journal keys
                if dri_l not in value.lower():
                    pass
            notes.append(f"{key}: {value}" if key else value)
            if len(notes) >= limit:
                return notes[:limit]
    recall = getattr(store, "recall", None)
    if callable(recall) and len(notes) < limit:
        try:
            hits = recall(
                workspace_id=workspace_id,
                channel_id="",
                query=f"journal {dri}".strip(),
                limit=limit,
            )
        except Exception:
            hits = []
        for hit in hits or []:
            src = str(hit.get("source") or "")
            if src.startswith("journal") or "journal" in src:
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
    binding: Mapping[str, Any] | None,
    *,
    store: Any = None,
    workspace_id: str = "default",
    channel_id: str = "",
    max_bytes: int = 1800,
    max_journal: int = 5,
    max_docs: int = 6,
    max_done: int = 3,
) -> str:
    """Budgeted MemGPT-style recall pack for a DRI brain lake."""

    brain = brain_from_binding(binding)
    if not brain:
        return ""
    lines = ["[brain-lake]", "pack: compact-recall"]
    dri = brain.get("dri") or ""
    if dri:
        lines.append(f"DRI: {dri}")
    docs = brain.get("strategy_docs") or ""
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
    transcripts = brain.get("transcripts_channel") or ""
    if transcripts:
        lines.append(f"Transcripts channel: {transcripts}")
    if brain.get("journal") and store is not None:
        notes = list_journal_notes(
            store, workspace_id=workspace_id, dri=dri, limit=max_journal
        )
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
    # Plan gallery hits (P1c)
    if store is not None:
        plans = list_plan_gallery(store, workspace_id=workspace_id, limit=3)
        if plans:
            lines.append("[plan-gallery]")
            for item in plans:
                lines.append(f"- {item}")
    lines.append(
        "Honest limit: single-host SQLite brain lake — not multi-host Durable Objects."
    )
    return clip_pack_text("\n".join(lines), max_bytes=max_bytes)


def list_plan_gallery(
    store: Any,
    *,
    workspace_id: str = "default",
    limit: int = 3,
) -> list[str]:
    """Recent kind=plan preference rows for [plan-gallery] inject."""

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


def format_brain_prompt_block(
    binding: Mapping[str, Any] | None,
    *,
    store: Any = None,
    workspace_id: str = "default",
    channel_id: str = "",
    max_bytes: int = 1800,
) -> str:
    """Worker prompt inject — compact recall pack (Wave 5 P1a)."""

    return build_compact_recall_pack(
        binding,
        store=store,
        workspace_id=workspace_id,
        channel_id=channel_id,
        max_bytes=max_bytes,
    )



def format_meat_proxy_handoff_preamble(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    from_id: str,
    to_id: str,
    peer_prompt: str,
    envelope: Any = None,
) -> str:
    """Lake→lake handoff context so humans are not the meat proxy.

    Escalates to humans only on ROE (gates) — this block travels with the
    JobPool peer task. Optional Wave 5 ``envelope`` adds typed handoff lines.
    """

    binding = {}
    getter = getattr(store, "get_binding", None)
    if callable(getter):
        try:
            binding = getter(workspace_id, channel_id) or {}
        except Exception:
            binding = {}
    brain_block = format_brain_prompt_block(
        binding, store=store, workspace_id=workspace_id
    )
    mem = ""
    reader = getattr(store, "prompt_memory_block", None)
    if callable(reader):
        try:
            mem = (reader(workspace_id) or "").strip()
        except Exception:
            mem = ""
    env_lines: list[str] = []
    if envelope is not None:
        hid = str(getattr(envelope, "handoff_id", "") or "").strip()
        if hid:
            env_lines.append(f"handoff_id={hid}")
        for attr, label in (
            ("constraints", "constraints"),
            ("expecting", "expecting"),
            ("freshness", "freshness"),
            ("supersedes", "supersedes"),
            ("roe_hint", "roe_hint"),
            ("brain_dri", "brain_dri"),
        ):
            val = str(getattr(envelope, attr, "") or "").strip()
            if val:
                env_lines.append(f"{label}={val}")
    parts = [
        f"[meat-proxy-cut] Handoff lake context from <@{from_id}> → <@{to_id}>.",
        "Escalate to humans only on ROE (write/ask/plan gates) — do not meat-proxy via chat paste.",
    ]
    if env_lines:
        parts.append("[handoff-envelope]\n" + "\n".join(env_lines))
    parts.append(f"Task: {peer_prompt.strip()}")
    if brain_block:
        parts.append(brain_block)
    if mem:
        clipped = mem if len(mem) <= 600 else mem[:597] + "..."
        parts.append("[desk-memory]\n" + clipped)
    return "\n\n".join(parts)
