"""Fork a job from one lineage step instead of continuing from its tip.

A reply in a job thread — ``fork from 2: try it with the cache off`` — opens a
**sibling** thread in the parent channel whose new run parents at step 2 of the
replied-to run's DAG. The original thread keeps its own tip, so the two lines of
work do not step on each other.

``N`` is the number ``discord-os lineage RUN_ID`` prints for that step, or a
node key prefix. One to three digits is read as a step number, so a key prefix
has to be at least four characters and unambiguous — which it is anyway, since
``node_by_key_prefix`` refuses a prefix that matches two nodes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

FORK_RE = re.compile(
    r"^\s*fork\s+from\s+(?P<token>[0-9a-f]+)\s*[:\-]\s*(?P<prompt>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_MAX_STEP_DIGITS = 3
FORK_PARENT_META = "fork_parent_key"
FORK_OF_META = "fork_of_run"
FORK_OF_CODE_META = "fork_of_code"
FORK_STEP_META = "fork_step"


@dataclass(frozen=True)
class ForkAsk:
    token: str
    prompt: str


def parse_fork_command(text: str) -> Optional[ForkAsk]:
    """``fork from <N|keyprefix>: <instruction>``, else None."""

    match = FORK_RE.match(text or "")
    if match is None:
        return None
    prompt = " ".join(match.group("prompt").split())
    if not prompt:
        return None
    return ForkAsk(token=match.group("token").strip().lower(), prompt=prompt)


def resolve_fork_parent(
    store: Any, run_id: str, token: str
) -> tuple[Optional[Any], int, str]:
    """The node ``token`` names and its step number, or a spoken refusal."""

    from agent_discord.orchestration.lineage import (
        list_stack,
        node_at_step,
        node_by_key_prefix,
    )

    rid = (run_id or "").strip()
    if not rid:
        return None, 0, "Need: fork found no run in this thread."
    nodes = list_stack(store, rid)
    if not nodes:
        return None, 0, "Need: fork found no lineage for this job."
    raw = (token or "").strip().lower()
    if raw.isdigit() and len(raw) <= _MAX_STEP_DIGITS:
        node = node_at_step(nodes, int(raw))
        if node is None:
            return None, 0, (
                f"Need: fork from {raw} — this job has {len(nodes)} step(s). "
                "Run discord-os lineage for the numbers."
            )
    else:
        node = node_by_key_prefix(nodes, raw)
        if node is None:
            return None, 0, f"Need: fork from {raw} — no single lineage node matches."
    return node, _step_number_of(nodes, node), ""


def fork_metadata(
    node: Any,
    *,
    run_id: str,
    step_number: int = 0,
    job_code: str = "",
) -> dict[str, Any]:
    return {
        FORK_PARENT_META: str(getattr(node, "node_key", "") or ""),
        FORK_OF_META: (run_id or "").strip(),
        FORK_OF_CODE_META: (job_code or "").strip(),
        FORK_STEP_META: int(step_number or 0),
    }


def fork_note(metadata: Any) -> str:
    """First-card line: what this run forked from. Empty when it is not a fork."""

    meta = metadata or {}
    parent = str(meta.get(FORK_PARENT_META) or "").strip()
    if not parent:
        return ""
    where = (
        str(meta.get(FORK_OF_CODE_META) or "").strip()
        or str(meta.get(FORK_OF_META) or "")[:12]
    )
    step = int(meta.get(FORK_STEP_META) or 0)
    if step:
        return f"Forked from step {step} of {where} (node {parent[:8]})."
    return f"Forked from {where} (node {parent[:8]})."


def _step_number_of(nodes: Sequence[Any], node: Any) -> int:
    key = str(getattr(node, "node_key", "") or "")
    for index, candidate in enumerate(nodes or (), start=1):
        if candidate.node_key == key:
            return index
    return 0


__all__ = [
    "FORK_OF_CODE_META",
    "FORK_OF_META",
    "FORK_PARENT_META",
    "FORK_STEP_META",
    "ForkAsk",
    "fork_metadata",
    "fork_note",
    "parse_fork_command",
    "resolve_fork_parent",
]
