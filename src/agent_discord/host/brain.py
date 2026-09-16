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


def format_brain_prompt_block(
    binding: Mapping[str, Any] | None,
    *,
    store: Any = None,
    workspace_id: str = "default",
) -> str:
    """Worker prompt inject for a DRI brain lake (honest single-host)."""

    brain = brain_from_binding(binding)
    if not brain:
        return ""
    lines = ["[brain-lake]"]
    dri = brain.get("dri") or ""
    if dri:
        lines.append(f"DRI: {dri}")
    docs = brain.get("strategy_docs") or ""
    if docs:
        lines.append(f"Strategy docs: {docs}")
        # List a few filenames so the worker does not hunt.
        try:
            path = Path(docs)
            if path.is_dir():
                names = sorted(p.name for p in path.iterdir() if p.is_file())[:8]
                if names:
                    lines.append("Docs: " + ", ".join(names))
            elif path.is_file():
                lines.append(f"Doc file: {path.name}")
        except OSError:
            pass
    transcripts = brain.get("transcripts_channel") or ""
    if transcripts:
        lines.append(f"Meeting transcripts channel: {transcripts}")
    if brain.get("journal") and store is not None:
        notes = list_journal_notes(store, workspace_id=workspace_id, dri=dri)
        if notes:
            lines.append("Journal:")
            for note in notes:
                clipped = note if len(note) <= 160 else note[:157] + "..."
                lines.append(f"- {clipped}")
    lines.append(
        "Honest limit: single-host SQLite brain lake — not multi-host Durable Objects."
    )
    return "\n".join(lines)


def format_meat_proxy_handoff_preamble(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    from_id: str,
    to_id: str,
    peer_prompt: str,
) -> str:
    """Lake→lake handoff context so humans are not the meat proxy.

    Escalates to humans only on ROE (gates) — this block travels with the
    JobPool peer task.
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
    parts = [
        f"[meat-proxy-cut] Handoff lake context from <@{from_id}> → <@{to_id}>.",
        "Escalate to humans only on ROE (write/ask/plan gates) — do not meat-proxy via chat paste.",
        f"Task: {peer_prompt.strip()}",
    ]
    if brain_block:
        parts.append(brain_block)
    if mem:
        clipped = mem if len(mem) <= 600 else mem[:597] + "..."
        parts.append("[desk-memory]\n" + clipped)
    return "\n\n".join(parts)
