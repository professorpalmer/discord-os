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
    {
        "intake",
        "dispatch",
        "finding",
        "diff",
        "settle",
        "steer",
        "replay",
        "wake",
        "stack",
    }
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


def _node_from_row(row: Mapping[str, Any]) -> Optional[LineageNode]:
    parents = row.get("parent_keys") or ()
    if isinstance(parents, str):
        try:
            parents = json.loads(parents)
        except json.JSONDecodeError:
            parents = ()
    node = LineageNode(
        node_key=str(row.get("node_key") or ""),
        run_id=str(row.get("run_id") or ""),
        task_id=str(row.get("task_id") or ""),
        step=str(row.get("step") or ""),
        parent_keys=tuple(str(p) for p in parents),
        input_sha256=str(row.get("input_sha256") or ""),
        artifact_id=str(row.get("artifact_id") or ""),
        status=str(row.get("status") or "complete"),
    )
    return node if node.node_key else None


def list_nodes(store: Any, run_id: str) -> tuple[LineageNode, ...]:
    reader = getattr(store, "list_lineage_nodes", None)
    if not callable(reader):
        return ()
    out: list[LineageNode] = []
    for row in reader(run_id) or ():
        if not isinstance(row, Mapping):
            continue
        node = _node_from_row(row)
        if node is not None:
            out.append(node)
    return tuple(out)


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


def list_stack(store: Any, run_id: str) -> tuple[LineageNode, ...]:
    """This run's nodes plus cross-run descendants (stacked PRs)."""

    roots = list(list_nodes(store, run_id))
    if not roots:
        return ()
    gathered: dict[str, LineageNode] = {node.node_key: node for node in roots}
    pending = [node.node_key for node in roots]
    reader = getattr(store, "list_lineage_children", None)
    while pending:
        parent = pending.pop(0)
        kids = (reader(parent) or ()) if callable(reader) else ()
        for row in kids:
            if not isinstance(row, Mapping):
                continue
            child = _node_from_row(row)
            if child is None or child.node_key in gathered:
                continue
            gathered[child.node_key] = child
            pending.append(child.node_key)
    combined = tuple(gathered[key] for key in gathered)
    tip = tip_key(roots)
    extra_keys = descendants_to_replay(combined, tip) if tip else ()
    extra = tuple(gathered[key] for key in extra_keys if key in gathered)
    return tuple(roots) + extra


def child_job_codes(
    store: Any, nodes: Sequence[LineageNode], root_task_id: str
) -> tuple[str, ...]:
    reader = getattr(store, "task_job_code", None)
    if not callable(reader):
        return ()
    root = (root_task_id or "").strip()
    seen: set[str] = set()
    out: list[str] = []
    for node in nodes:
        if not node.task_id or node.task_id == root:
            continue
        code = str(reader(node.task_id) or "")
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return tuple(out)


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


def resolve_run_id(store: Any, token: str) -> str:
    """Run id, speakable job code, or latest."""

    from agent_discord.orchestration.job_briefing import is_job_code, normalize_job_code

    raw = (token or "").strip()
    if not raw:
        return latest_run_id(store) or ""
    if is_job_code(raw):
        finder = getattr(store, "get_task_by_job_code", None)
        latest = getattr(store, "latest_run_id_for_task", None)
        if callable(finder) and callable(latest):
            task = finder(normalize_job_code(raw))
            if task:
                return str(latest(str(task.get("task_id") or "")) or "")
    return raw


def progress_ledger_facts(
    store: Any,
    run_id: str,
    *,
    limit: int = 5,
) -> list[str]:
    """≤5 lineage/event facts for Live/Done card footer (Wave 5 P1b)."""

    rid = (run_id or "").strip()
    if not rid or store is None:
        return []
    facts: list[str] = []
    for node in list_nodes(store, rid):
        step = (node.step or "").strip().lower()
        if not step:
            continue
        label = step
        if node.artifact_id:
            label = f"{step} art={(node.artifact_id or '')[:10]}"
        elif node.input_sha256:
            label = f"{step} sha={(node.input_sha256 or '')[:8]}"
        facts.append(label)
        if len(facts) >= limit:
            return facts[:limit]
    lister = getattr(store, "list_events", None)
    if callable(lister):
        try:
            rows = list(lister(rid) or [])
        except Exception:
            rows = []
        interesting = (
            "plan_approved",
            "gate_allowed",
            "gate_allow",
            "handoff_claimed",
            "claim",
            "artifact",
            "approved",
            "parked",
        )
        for row in rows:
            kind = str(row.get("kind") or "").strip().lower()
            summary = str(row.get("summary") or "").strip()
            key = f"{kind} {summary}".lower()
            if not any(tok in key for tok in interesting):
                continue
            tip = summary or kind
            tip = tip if len(tip) <= 48 else tip[:45] + "..."
            label = f"{kind}:{tip}" if kind and summary else (kind or tip)
            if label and label not in facts:
                facts.append(label)
            if len(facts) >= limit:
                break
    return facts[:limit]


def format_progress_ledger(facts, *, limit: int = 5) -> str:
    rows = [str(f).strip() for f in (facts or []) if str(f).strip()][:limit]
    if not rows:
        return ""
    return "Ledger: " + " · ".join(rows)


def narrative_beats(
    store: Any,
    run_id: str,
    *,
    limit: int = 3,
) -> list[str]:
    """≤3 Need→Done story beats (Wave 6 P1d) under the progress ledger.

    Prefers plan_approved → gate_allowed → artifact sha — not a second board.
    """

    rid = (run_id or "").strip()
    if not rid or store is None:
        return []
    preferred = (
        "plan_approved",
        "gate_allowed",
        "gate_allow",
        "artifact",
        "handoff_claimed",
        "claim",
        "approved",
    )
    beats: list[str] = []
    seen: set[str] = set()
    for node in list_nodes(store, rid):
        step = (node.step or "").strip().lower()
        if not step or step in seen:
            continue
        if step == "steer":
            continue
        if node.artifact_id and (step.startswith("artifact") or "artifact" in step):
            label = f"artifact_sha {(node.artifact_id or '')[:8]}"
        elif step in preferred:
            # Keep story verbs (plan_approved / gate_allowed / …).
            label = step
            if node.artifact_id and step.startswith("gate"):
                # Optional sha tip when gate carries an artifact id.
                label = f"{step} · sha:{(node.artifact_id or '')[:8]}"
        elif "artifact" in step and (node.artifact_id or node.input_sha256):
            sha = (node.artifact_id or node.input_sha256 or "")[:8]
            label = f"artifact_sha {sha}"
        else:
            continue
        seen.add(step)
        beats.append(label)
        if len(beats) >= limit:
            return beats[:limit]
    # Fall back to event scan for plan/gate/artifact when nodes sparse.
    if len(beats) < limit:
        for fact in progress_ledger_facts(store, rid, limit=8):
            low = fact.lower()
            if not any(tok in low for tok in preferred) and "sha" not in low and "art=" not in low:
                continue
            tip = fact if len(fact) <= 40 else fact[:37] + "..."
            if tip not in beats:
                beats.append(tip)
            if len(beats) >= limit:
                break
    return beats[:limit]


def format_narrative_beats(beats, *, limit: int = 3) -> str:
    rows = [str(b).strip() for b in (beats or []) if str(b).strip()][:limit]
    if not rows:
        return ""
    return " → ".join(rows)


def citation_refs(
    store: Any,
    run_id: str,
    *,
    job_code: str = "",
    limit: int = 5,
) -> list[str]:
    """ARC-lite cites: DOS-* / artifact sha8 / journal ids (Wave 6 P1e)."""

    refs: list[str] = []
    code = (job_code or "").strip()
    if code:
        refs.append(code)
    rid = (run_id or "").strip()
    if rid and store is not None:
        for node in list_nodes(store, rid):
            if node.artifact_id:
                tip = f"sha:{(node.artifact_id or '')[:8]}"
                if tip not in refs:
                    refs.append(tip)
            elif node.input_sha256:
                tip = f"sha:{(node.input_sha256 or '')[:8]}"
                if tip not in refs:
                    refs.append(tip)
            if len(refs) >= limit:
                break
        if len(refs) < limit:
            lister = getattr(store, "list_artifacts_for_run", None) or getattr(
                store, "list_artifacts", None
            )
            if callable(lister):
                try:
                    arts = list(lister(rid) or [])
                except TypeError:
                    try:
                        arts = list(lister(run_id=rid) or [])
                    except Exception:
                        arts = []
                except Exception:
                    arts = []
                for art in arts:
                    if not isinstance(art, dict):
                        continue
                    sha = str(art.get("sha256") or art.get("artifact_id") or "")
                    if sha:
                        tip = f"sha:{sha[:8]}"
                        if tip not in refs:
                            refs.append(tip)
                    if len(refs) >= limit:
                        break
    return refs[:limit]


def format_citation_refs(refs, *, limit: int = 5) -> str:
    rows = [str(r).strip() for r in (refs or []) if str(r).strip()][:limit]
    if not rows:
        return ""
    return " · ".join(rows)
