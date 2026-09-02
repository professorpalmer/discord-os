"""Execution lineage DAG. SQLite on this Mac, not a Temporal cluster.

node_key = sha256(step, input hash, parent keys). A steer or retry is an
upstream edit: descendants are the only steps that need another run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

LINEAGE_STEPS = frozenset(
    {"intake", "dispatch", "finding", "diff", "settle", "steer", "replay"}
)


@dataclass(frozen=True)
class LineageNode:
    node_key: str
    run_id: str
    task_id: str
    step: str
    parent_keys: tuple[str, ...]
    input_sha256: str
    artifact_id: str
    status: str


def input_sha256(body: str) -> str:
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def node_key(step: str, digest: str, parent_keys: Sequence[str] = ()) -> str:
    payload = json.dumps(
        {
            "input": digest,
            "parents": list(parent_keys),
            "step": step,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_node(
    store: Any,
    *,
    run_id: str,
    task_id: str,
    step: str,
    body: str,
    parent_keys: Sequence[str] = (),
    artifact_id: str = "",
    status: str = "complete",
) -> str:
    """Idempotent insert. Returns the node key."""

    digest = input_sha256(body)
    parents = tuple(k for k in parent_keys if k)
    key = node_key(step, digest, parents)
    writer = getattr(store, "upsert_lineage_node", None)
    if callable(writer):
        writer(
            node_key=key,
            run_id=run_id,
            task_id=task_id,
            step=step,
            parent_keys=parents,
            input_sha256=digest,
            artifact_id=artifact_id,
            status=status,
        )
    return key


def list_nodes(store: Any, run_id: str) -> tuple[LineageNode, ...]:
    reader = getattr(store, "list_lineage_nodes", None)
    if not callable(reader):
        return ()
    rows = reader(run_id) or ()
    out: list[LineageNode] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        parents = row.get("parent_keys") or ()
        if isinstance(parents, str):
            try:
                parents = json.loads(parents)
            except json.JSONDecodeError:
                parents = ()
        out.append(
            LineageNode(
                node_key=str(row.get("node_key") or ""),
                run_id=str(row.get("run_id") or ""),
                task_id=str(row.get("task_id") or ""),
                step=str(row.get("step") or ""),
                parent_keys=tuple(str(p) for p in parents),
                input_sha256=str(row.get("input_sha256") or ""),
                artifact_id=str(row.get("artifact_id") or ""),
                status=str(row.get("status") or "complete"),
            )
        )
    return tuple(n for n in out if n.node_key)


def tip_key(nodes: Sequence[LineageNode]) -> str:
    complete = [n for n in nodes if n.status != "stale"]
    if not complete:
        return ""
    referenced = {parent for node in complete for parent in node.parent_keys}
    tips = [node for node in complete if node.node_key not in referenced]
    if not tips:
        return complete[-1].node_key
    return tips[-1].node_key


def children_of(nodes: Sequence[LineageNode], parent_key: str) -> tuple[LineageNode, ...]:
    key = (parent_key or "").strip()
    if not key:
        return ()
    return tuple(n for n in nodes if key in n.parent_keys)


def descendants_to_replay(
    nodes: Sequence[LineageNode], parent_key: str
) -> tuple[str, ...]:
    """Keys of nodes that descend from parent_key, breadth-first, unique."""

    pending = list(children_of(nodes, parent_key))
    seen: set[str] = set()
    ordered: list[str] = []
    while pending:
        node = pending.pop(0)
        if node.node_key in seen:
            continue
        seen.add(node.node_key)
        ordered.append(node.node_key)
        pending.extend(children_of(nodes, node.node_key))
    return tuple(ordered)


def mark_stale(store: Any, node_keys: Sequence[str]) -> int:
    writer = getattr(store, "mark_lineage_stale", None)
    if not callable(writer):
        return 0
    keys = [k for k in node_keys if k]
    if not keys:
        return 0
    return int(writer(keys) or 0)


def cite_artifact(artifact: Mapping[str, Any] | None) -> str:
    if not artifact:
        return ""
    kind = str(artifact.get("kind") or "blob")
    digest = str(artifact.get("sha256") or "")[:12]
    name = str(artifact.get("filename") or kind)
    if digest:
        return f"{name} {digest}"
    return name


def format_nodes(nodes: Sequence[LineageNode]) -> str:
    if not nodes:
        return "no lineage nodes"
    lines = ["step  key              parents  artifact"]
    for node in nodes:
        short = node.node_key[:12]
        parents = ",".join(p[:8] for p in node.parent_keys) or "-"
        art = (node.artifact_id or "-")[:12]
        lines.append(f"{node.step:7} {short}  {parents:16}  {art}")
    return "\n".join(lines)


def node_payload(node: LineageNode) -> dict[str, Any]:
    return {
        "node_key": node.node_key,
        "run_id": node.run_id,
        "task_id": node.task_id,
        "step": node.step,
        "parent_keys": list(node.parent_keys),
        "input_sha256": node.input_sha256,
        "artifact_id": node.artifact_id,
        "status": node.status,
    }


def latest_run_id(store: Any) -> Optional[str]:
    reader = getattr(store, "latest_lineage_run_id", None)
    if not callable(reader):
        return None
    found = reader()
    return str(found) if found else None
