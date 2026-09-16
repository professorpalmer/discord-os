"""Board catch-up — ADR/PR conflict scan for cron + Catch-up honesty.

Composes JobPool job rows + optional job_pull_requests. Not a second board,
not a Durable Objects clone, not an Off→On job storm.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

# ADR-003, adr-003, ADR 003, docs/adr/0003-foo.md, adr/0003-foo.md
_ADR_RE = re.compile(
    r"(?i)\b(?:ADR[-_ ]?(\d{1,4})|(?:docs/)?adr/(\d{1,4})[-\w]*\.md)\b"
)
_PR_RE = re.compile(
    r"(?i)(?:https?://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)|(?:\brepo\s+)?([\w.-]+/[\w.-]+)#(\d+)|\bPR\s*#(\d+)\b)"
)

_DIGEST_PREFIXES = (
    "board catch-up",
    "board catchup",
    "board-catchup",
    "digest:",
    "digest ",
    "[board-catchup]",
)


@dataclass(frozen=True)
class ConflictHit:
    left_code: str
    right_code: str
    shared: str
    kind: str  # adr | pr | cwd


def is_board_digest_prompt(prompt: str) -> bool:
    """True when a schedule should post a board digest instead of a full cook."""

    raw = (prompt or "").strip().lower()
    if not raw:
        return False
    return any(raw.startswith(p) or p in raw[:40] for p in _DIGEST_PREFIXES)


def extract_adr_refs(text: str) -> frozenset[str]:
    found: set[str] = set()
    for match in _ADR_RE.finditer(text or ""):
        num = match.group(1) or match.group(2)
        if num:
            found.add(f"ADR-{int(num):03d}")
    return frozenset(found)


def extract_pr_refs(text: str) -> frozenset[str]:
    found: set[str] = set()
    for match in _PR_RE.finditer(text or ""):
        if match.group(1) and match.group(2) and match.group(3):
            found.add(f"{match.group(1)}/{match.group(2)}#{match.group(3)}")
        elif match.group(4) and match.group(5):
            found.add(f"{match.group(4)}#{match.group(5)}")
        elif match.group(6):
            found.add(f"PR#{match.group(6)}")
    return frozenset(found)


def _job_blob(job: Mapping[str, Any]) -> str:
    bits = [
        str(job.get("intake_text") or ""),
        str(job.get("summary") or ""),
        str(job.get("job_code") or ""),
    ]
    meta = job.get("metadata") or job.get("metadata_json") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    if isinstance(meta, Mapping):
        bits.append(json.dumps(meta, sort_keys=True)[:800])
        for key in ("cwd", "realm", "lane", "write_key"):
            if meta.get(key):
                bits.append(str(meta.get(key)))
    return "\n".join(bits)


def _job_label(job: Mapping[str, Any]) -> str:
    code = str(job.get("job_code") or "").strip()
    if code:
        return code
    tid = str(job.get("task_id") or "").strip()
    return tid[:12] if tid else "?"


def _active_jobs(jobs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for job in jobs:
        status = str(job.get("status") or "").strip().lower()
        attention = str(job.get("attention") or "").strip().lower()
        if status in {"pending", "running", "progress", "failed"} or attention in {
            "need",
            "waiting",
        }:
            out.append(job)
    return out


def scan_job_conflicts(
    jobs: Sequence[Mapping[str, Any]],
    *,
    cwd_by_task: Optional[Mapping[str, str]] = None,
) -> list[ConflictHit]:
    """Pairwise shared ADR/PR (and optional cwd) across Need/Live/Waiting jobs."""

    active = _active_jobs(jobs)
    if len(active) < 2:
        return []
    cwd_map = dict(cwd_by_task or {})
    indexed: list[tuple[str, frozenset[str], frozenset[str], str]] = []
    for job in active:
        label = _job_label(job)
        blob = _job_blob(job)
        adrs = extract_adr_refs(blob)
        prs = extract_pr_refs(blob)
        cwd = str(cwd_map.get(str(job.get("task_id") or "")) or "").strip()
        if not cwd:
            meta = job.get("metadata") or {}
            if isinstance(meta, Mapping):
                cwd = str(meta.get("cwd") or meta.get("write_key") or "").strip()
        indexed.append((label, adrs, prs, cwd))

    hits: list[ConflictHit] = []
    seen: set[tuple[str, str, str]] = set()
    for i in range(len(indexed)):
        left_code, left_adrs, left_prs, left_cwd = indexed[i]
        for j in range(i + 1, len(indexed)):
            right_code, right_adrs, right_prs, right_cwd = indexed[j]
            if left_code == right_code:
                continue
            for shared in sorted(left_adrs & right_adrs):
                key = tuple(sorted((left_code, right_code)) + [shared])
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    ConflictHit(
                        left_code=left_code,
                        right_code=right_code,
                        shared=shared,
                        kind="adr",
                    )
                )
            for shared in sorted(left_prs & right_prs):
                key = tuple(sorted((left_code, right_code)) + [shared])
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    ConflictHit(
                        left_code=left_code,
                        right_code=right_code,
                        shared=shared,
                        kind="pr",
                    )
                )
            if left_cwd and right_cwd and left_cwd == right_cwd:
                key = tuple(sorted((left_code, right_code)) + [f"cwd:{left_cwd}"])
                if key not in seen:
                    seen.add(key)
                    hits.append(
                        ConflictHit(
                            left_code=left_code,
                            right_code=right_code,
                            shared=left_cwd,
                            kind="cwd",
                        )
                    )
    return hits


def format_conflict_lines(hits: Sequence[ConflictHit], *, limit: int = 8) -> list[str]:
    lines: list[str] = []
    for hit in list(hits)[: max(0, int(limit))]:
        if hit.kind == "adr":
            lines.append(
                f"{hit.left_code} ↔ {hit.right_code} via {hit.shared} (ADR coordination tax)"
            )
        elif hit.kind == "pr":
            lines.append(
                f"{hit.left_code} ↔ {hit.right_code} via {hit.shared} (PR overlap)"
            )
        else:
            short = hit.shared if len(hit.shared) <= 60 else hit.shared[:57] + "..."
            lines.append(
                f"{hit.left_code} ↔ {hit.right_code} share checkout {short}"
            )
    if len(hits) > limit:
        lines.append(f"(+{len(hits) - limit} more)")
    return lines


def format_board_catchup(
    *,
    skipped_labels: Sequence[str] = (),
    conflicts: Sequence[ConflictHit] = (),
    pushed: Sequence[str] = (),
) -> str:
    """One Catch-up / board-digest body (Need-shaped text)."""

    parts: list[str] = []
    skipped = [s for s in skipped_labels if str(s).strip()]
    if skipped:
        body = (
            f"Catch-up: {len(skipped)} schedule(s) skipped_while_disarmed — "
            + "; ".join(skipped[:8])
        )
        if len(skipped) > 8:
            body += f" (+{len(skipped) - 8} more)"
        parts.append(body)
    else:
        parts.append("Board catch-up")
    conflict_lines = format_conflict_lines(conflicts)
    if conflict_lines:
        parts.append("Conflicts:")
        parts.extend(f"- {line}" for line in conflict_lines)
    else:
        parts.append("Conflicts: none detected on Need/Live board scan.")
    push = [p for p in pushed if str(p).strip()]
    if push:
        parts.append("Push forward: " + "; ".join(push[:6]))
    return "\n".join(parts)


def collect_channel_conflicts(
    store: Any,
    channel_id: str,
    *,
    limit: int = 25,
) -> list[ConflictHit]:
    """Load recent jobs from store and scan. Soft-empty on missing APIs."""

    lister = getattr(store, "list_recent_jobs", None)
    if not callable(lister):
        return []
    try:
        jobs = list(lister(channel_id, limit=limit) or [])
    except TypeError:
        try:
            jobs = list(lister(channel_id) or [])
        except Exception:
            return []
    except Exception:
        return []
    # Attach metadata when store exposes task_metadata
    meta_reader = getattr(store, "task_metadata", None)
    enriched: list[dict[str, Any]] = []
    for job in jobs:
        item = dict(job)
        tid = str(item.get("task_id") or "")
        if tid and callable(meta_reader):
            try:
                item["metadata"] = meta_reader(tid) or {}
            except Exception:
                item["metadata"] = {}
        enriched.append(item)
    return scan_job_conflicts(enriched)
