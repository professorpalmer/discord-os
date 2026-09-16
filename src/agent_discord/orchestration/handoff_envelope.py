"""Wave 5 typed handoff envelope — JobPool-only, board + brain lakes.

Schema rides on task metadata. Re-dispatch of the same ``handoff_id`` while a
live cook exists → spoken ``already_claimed`` (no second JobPool job).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from agent_discord.orchestration.service import parse_handoff_command

LIVE_HANDOFF_STATUSES = frozenset(
    {
        "pending",
        "queued",
        "running",
        "waiting",
        "waiting_approval",
        "parked",
    }
)

_KV_RE = re.compile(
    r"(?:^|\s)(id|handoff_id|constraints|expecting|supersedes|roe_hint|brain_dri|freshness)"
    r"=([^\s|]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HandoffEnvelope:
    handoff_id: str
    from_id: str
    to_id: str
    constraints: str = ""
    expecting: str = ""
    freshness: str = ""
    supersedes: str = ""
    roe_hint: str = ""
    brain_dri: str = ""

    def as_metadata(self) -> dict[str, Any]:
        meta = {
            "handoff_id": self.handoff_id,
            "handoff_from": self.from_id,
            "handoff_to": self.to_id,
            "from": self.from_id,
            "to": self.to_id,
            "peer_task": True,
            "lane": "handoff",
            "meat_proxy_cut": True,
        }
        if self.constraints:
            meta["constraints"] = self.constraints
        if self.expecting:
            meta["expecting"] = self.expecting
        if self.freshness:
            meta["freshness"] = self.freshness
        if self.supersedes:
            meta["supersedes"] = self.supersedes
        if self.roe_hint:
            meta["roe_hint"] = self.roe_hint
        if self.brain_dri:
            meta["brain_dri"] = self.brain_dri
        return meta

    def clipped_fields(self, *, max_len: int = 80) -> list[tuple[str, str]]:
        """Receipt-card friendly (label, value) pairs."""

        rows: list[tuple[str, str]] = [
            ("Handoff", self.handoff_id[:max_len]),
            ("From", self.from_id[:max_len]),
            ("To", self.to_id[:max_len]),
        ]
        optional = (
            ("Constraints", self.constraints),
            ("Expecting", self.expecting),
            ("Freshness", self.freshness),
            ("Supersedes", self.supersedes),
            ("ROE", self.roe_hint),
            ("Brain DRI", self.brain_dri),
        )
        for label, raw in optional:
            text = (raw or "").strip()
            if text:
                rows.append((label, text[:max_len]))
        return rows


def stable_handoff_id(*, from_id: str, to_id: str, prompt: str) -> str:
    blob = f"{from_id.strip()}|{to_id.strip()}|{_normalize_prompt(prompt)}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _normalize_prompt(prompt: str) -> str:
    return " ".join((prompt or "").strip().lower().split())


def parse_envelope_kv(prompt: str) -> tuple[str, dict[str, str]]:
    """Strip leading/trailing ``key=value`` tokens from the peer prompt."""

    raw = (prompt or "").strip()
    found: dict[str, str] = {}
    # Also allow pipe-separated trailing: "do x | constraints=no-push"
    parts = [p.strip() for p in raw.split("|")]
    kept: list[str] = []
    for part in parts:
        cleaned = part
        for match in list(_KV_RE.finditer(part)):
            key = match.group(1).lower()
            if key == "id":
                key = "handoff_id"
            found[key] = match.group(2).strip()
            cleaned = cleaned.replace(match.group(0), " ")
        cleaned = " ".join(cleaned.split()).strip()
        if cleaned:
            kept.append(cleaned)
    return " ".join(kept).strip() or raw, found


def build_handoff_envelope(
    *,
    from_id: str,
    to_id: str,
    peer_prompt: str,
    brain_dri: str = "",
    now_ms: Optional[int] = None,
) -> tuple[HandoffEnvelope, str]:
    """Return (envelope, cleaned_prompt)."""

    cleaned, kv = parse_envelope_kv(peer_prompt)
    hid = (kv.get("handoff_id") or "").strip() or stable_handoff_id(
        from_id=from_id, to_id=to_id, prompt=cleaned
    )
    freshness = (kv.get("freshness") or "").strip()
    if not freshness:
        stamp = int(now_ms if now_ms is not None else time.time() * 1000)
        freshness = f"ms:{stamp}"
    env = HandoffEnvelope(
        handoff_id=hid,
        from_id=str(from_id or "").strip(),
        to_id=str(to_id or "").strip(),
        constraints=(kv.get("constraints") or "").strip(),
        expecting=(kv.get("expecting") or "").strip(),
        freshness=freshness,
        supersedes=(kv.get("supersedes") or "").strip(),
        roe_hint=(kv.get("roe_hint") or "").strip(),
        brain_dri=(kv.get("brain_dri") or brain_dri or "").strip(),
    )
    return env, cleaned


def spoken_already_claimed(handoff_id: str, *, job_code: str = "") -> str:
    hid = (handoff_id or "").strip() or "(empty)"
    code = (job_code or "").strip()
    if code:
        return f"Need: handoff already_claimed id={hid} job={code} — no second live cook."
    return f"Need: handoff already_claimed id={hid} — no second live cook."


def find_live_handoff_claim(
    store: Any,
    handoff_id: str,
    *,
    channel_id: str = "",
    limit: int = 40,
) -> Optional[dict[str, Any]]:
    """Return a live/parked job row whose metadata.handoff_id matches."""

    hid = (handoff_id or "").strip()
    if not hid:
        return None
    finder = getattr(store, "find_live_handoff_by_id", None)
    if callable(finder):
        try:
            hit = finder(
                hid,
                channel_id=channel_id or "",
                live_statuses=tuple(sorted(LIVE_HANDOFF_STATUSES)),
            )
        except TypeError:
            hit = finder(hid, channel_id=channel_id or "")
        except Exception:
            hit = None
        if hit:
            return dict(hit)
    # Fallback: scan recent jobs if metadata present on rows
    _ = limit
    lister = getattr(store, "list_recent_jobs", None)
    if not callable(lister):
        return None
    try:
        rows = lister(channel_id or "", limit=limit)
    except Exception:
        return None
    for row in rows or ():
        meta_raw = row.get("metadata_json") or row.get("metadata") or {}
        if isinstance(meta_raw, str):
            try:
                meta = json.loads(meta_raw or "{}")
            except json.JSONDecodeError:
                meta = {}
        elif isinstance(meta_raw, Mapping):
            meta = dict(meta_raw)
        else:
            meta = {}
        if str(meta.get("handoff_id") or "").strip() != hid:
            continue
        status = str(row.get("status") or "").strip().lower()
        if status in LIVE_HANDOFF_STATUSES:
            return dict(row)
    return None


def envelope_from_metadata(meta: Mapping[str, Any] | None) -> Optional[HandoffEnvelope]:
    if not isinstance(meta, Mapping):
        return None
    hid = str(meta.get("handoff_id") or "").strip()
    if not hid:
        return None
    from_id = str(meta.get("from") or meta.get("handoff_from") or "").strip()
    to_id = str(meta.get("to") or meta.get("handoff_to") or "").strip()
    return HandoffEnvelope(
        handoff_id=hid,
        from_id=from_id,
        to_id=to_id,
        constraints=str(meta.get("constraints") or "").strip(),
        expecting=str(meta.get("expecting") or "").strip(),
        freshness=str(meta.get("freshness") or "").strip(),
        supersedes=str(meta.get("supersedes") or "").strip(),
        roe_hint=str(meta.get("roe_hint") or "").strip(),
        brain_dri=str(meta.get("brain_dri") or "").strip(),
    )


def parse_handoff_with_envelope(
    text: str,
) -> Optional[tuple[str, str]]:
    """Compat: peer_id + raw prompt (KV still inside prompt for build step)."""

    return parse_handoff_command(text)
