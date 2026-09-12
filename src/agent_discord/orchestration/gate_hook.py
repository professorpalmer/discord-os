"""Live ask-gate + ExitPlanMode hold — durable file queue.

Phone Allow / Deny / Always (tool-class) and Approve / Cancel (plan) must
block the live worker mid-cook, not only unit-test orch methods. Full
Puppetmaster ``canUseTool`` is not available in-process on the agentic
subprocess, so this module is the seam:

- ``tool_class_decision`` → park a Discord card → block until
  ``gate_result_for`` (or the result file) or approval timeout self-denies.
- ExitPlanMode / plan-ready → ``raise_plan_approve`` (Approve / Cancel, no
  Always) → block implement until allow / deny / timeout.
- Durable file queue the agentic hook and Discord listen/orch share.
- Hook CLI always exits 0 (dis-claude shape). Unanswered / timeout → deny.

Stolen shapes (not clones): albertorsesc PreToolUse hold, DisCode CLI hooks,
dis-claude atomic file-queue, c-lord ExitPlanMode. Docs:
``docs/cards/ask-gate.md``, ``docs/cards/plan-approve.md``.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from agent_discord.orchestration.ask_gate import (
    GATE_KIND_ASK,
    GATE_KIND_TOOL,
    normalize_tool_class,
    tool_class_decision,
)
from agent_discord.orchestration.plan_approve import (
    GATE_KIND_PLAN,
    is_exit_plan_tool,
    plan_text_from_tool_input,
)
from agent_discord.redaction import redact_text_markers

PROTOCOL_VERSION = 1
ENV_GATE_DIR = "DISCORD_OS_GATE_DIR"
ENV_GATE_ROOT = "DISCORD_OS_GATE_ROOT"
ENV_RUN_ID = "DISCORD_OS_RUN_ID"
ENV_TIMEOUT = "DISCORD_OS_GATE_TIMEOUT_SECONDS"
ENV_HOOK = "DISCORD_OS_GATE_HOOK"
ENV_INJECT = "DISCORD_OS_GATE_INJECT"
DEFAULT_POLL_SECONDS = 0.05
PENDING_DIR = "pending"
RESULTS_DIR = "results"

Clock = Callable[[], float]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class GateRequest:
    """One worker-side hold request on the durable queue."""

    request_id: str
    run_id: str
    tool_name: str
    tool_class: str
    detail: str = ""
    kind: str = GATE_KIND_TOOL
    question: str = ""
    options: tuple[Any, ...] = ()
    created_at_ms: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "v": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "tool_name": self.tool_name,
            "tool_class": self.tool_class,
            "detail": self.detail,
            "kind": self.kind,
            "question": self.question,
            "options": list(self.options),
            "created_at_ms": int(self.created_at_ms),
        }


@dataclass(frozen=True)
class GateHoldResult:
    """Worker-facing hold outcome. ``decision`` is allow | always | deny."""

    request_id: str
    decision: str
    gate_answer: str = ""
    reason: str = ""
    tool_class: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "v": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "decision": self.decision,
            "gate_result": self.decision,
            "gate_answer": self.gate_answer,
            "reason": self.reason,
            "tool_class": self.tool_class,
        }


def _safe_run_id(run_id: str) -> str:
    text = (run_id or "").strip() or "unknown"
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)
    return cleaned[:80] or "unknown"


def resolve_gate_root(
    workspace: Optional[Path | str] = None,
    store: Any = None,
    env: Optional[Mapping[str, str]] = None,
) -> Path:
    """Workspace/gates, else next to SQLite, else env override."""

    source = env if env is not None else os.environ
    raw = str(source.get(ENV_GATE_ROOT) or source.get(ENV_GATE_DIR) or "").strip()
    if raw:
        path = Path(raw)
        # Per-run dir (has pending/) — listen wants the parent root.
        if (path / PENDING_DIR).is_dir() and path.parent.name:
            return path.parent
        return path
    if workspace:
        return Path(workspace) / "gates"
    db = getattr(store, "path", None)
    if db:
        return Path(db).parent / "gates"
    return Path(tempfile.gettempdir()) / "discord-os-gates"


def run_gate_dir(root: Path, run_id: str) -> Path:
    return Path(root) / _safe_run_id(run_id)


def resolve_run_gate_dir(
    *,
    run_id: str = "",
    workspace: Optional[Path | str] = None,
    store: Any = None,
    env: Optional[Mapping[str, str]] = None,
) -> Path:
    source = env if env is not None else os.environ
    rid = (run_id or source.get(ENV_RUN_ID) or "").strip()
    raw = str(source.get(ENV_GATE_DIR) or "").strip()
    if raw:
        path = Path(raw)
        if (path / PENDING_DIR).is_dir() or (rid and path.name == _safe_run_id(rid)):
            return path
        if rid:
            return run_gate_dir(path, rid)
        return path
    root = resolve_gate_root(workspace=workspace, store=store, env=source)
    if rid:
        return run_gate_dir(root, rid)
    return root


def ensure_run_gate_dir(path: Path) -> Path:
    path = Path(path)
    (path / PENDING_DIR).mkdir(parents=True, exist_ok=True)
    (path / RESULTS_DIR).mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def enqueue_request(run_dir: Path, request: GateRequest) -> Path:
    ensure_run_gate_dir(run_dir)
    return atomic_write_json(
        Path(run_dir) / PENDING_DIR / f"{request.request_id}.json",
        request.to_payload(),
    )


def complete_request(run_dir: Path, result: GateHoldResult) -> Path:
    ensure_run_gate_dir(run_dir)
    return atomic_write_json(
        Path(run_dir) / RESULTS_DIR / f"{result.request_id}.json",
        result.to_payload(),
    )


def read_result(run_dir: Path, request_id: str) -> Optional[GateHoldResult]:
    data = _read_json(Path(run_dir) / RESULTS_DIR / f"{request_id}.json")
    if not data:
        return None
    decision = str(data.get("decision") or data.get("gate_result") or "").strip().lower()
    if decision not in {"allow", "always", "deny"}:
        return None
    return GateHoldResult(
        request_id=str(data.get("request_id") or request_id),
        decision=decision,
        gate_answer=str(data.get("gate_answer") or ""),
        reason=str(data.get("reason") or ""),
        tool_class=str(data.get("tool_class") or ""),
    )


def request_from_payload(data: Mapping[str, Any]) -> Optional[GateRequest]:
    rid = str(data.get("request_id") or "").strip()
    run_id = str(data.get("run_id") or "").strip()
    if not rid or not run_id:
        return None
    options = data.get("options") if isinstance(data.get("options"), list) else []
    created = data.get("created_at_ms") or 0
    try:
        created_ms = int(created)
    except (TypeError, ValueError):
        created_ms = 0
    return GateRequest(
        request_id=rid,
        run_id=run_id,
        tool_name=str(data.get("tool_name") or ""),
        tool_class=str(data.get("tool_class") or ""),
        detail=str(data.get("detail") or ""),
        kind=str(data.get("kind") or GATE_KIND_TOOL),
        question=str(data.get("question") or ""),
        options=tuple(options),
        created_at_ms=created_ms,
    )


def list_pending(run_dir: Path) -> list[GateRequest]:
    pending = Path(run_dir) / PENDING_DIR
    if not pending.is_dir():
        return []
    out: list[GateRequest] = []
    for path in sorted(pending.glob("*.json")):
        if path.name.startswith("."):
            continue
        data = _read_json(path)
        if not data:
            continue
        req = request_from_payload(data)
        if req is None:
            continue
        if read_result(run_dir, req.request_id) is not None:
            continue
        out.append(req)
    return out


def iter_run_dirs(root: Path) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    if (root / PENDING_DIR).is_dir():
        return [root]
    return [
        child
        for child in sorted(root.iterdir())
        if child.is_dir() and (child / PENDING_DIR).is_dir()
    ]


def gate_timeout_seconds(env: Optional[Mapping[str, str]] = None) -> float:
    source = env if env is not None else os.environ
    raw = str(source.get(ENV_TIMEOUT) or "").strip()
    if raw:
        try:
            return max(0.05, float(raw))
        except ValueError:
            pass
    from agent_discord.orchestration.service import approval_timeout_seconds

    seconds = approval_timeout_seconds(source)
    if seconds <= 0:
        # Fail closed: an explicit "never expire" still cannot hold forever
        # in the hook process. 20 minutes matches the product default.
        return 20 * 60
    return float(seconds)


def wait_for_result(
    run_dir: Path,
    request_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleeper: Optional[Sleeper] = None,
    clock: Optional[Clock] = None,
    poller: Optional[Callable[[], Optional[GateHoldResult]]] = None,
    tool_class: str = "",
) -> GateHoldResult:
    """Block until a result file (or poller) appears. Timeout → deny."""

    sleep = sleeper or time.sleep
    now = clock or time.time
    deadline = now() + max(0.0, float(timeout_seconds))
    while now() < deadline:
        found = read_result(run_dir, request_id)
        if found is not None:
            return found
        if poller is not None:
            extra = poller()
            if extra is not None:
                complete_request(run_dir, extra)
                return extra
        sleep(max(0.001, float(poll_seconds)))
    denied = GateHoldResult(
        request_id=request_id,
        decision="deny",
        reason="timeout",
        tool_class=tool_class,
    )
    complete_request(run_dir, denied)
    return denied


def extract_tool(payload: Mapping[str, Any]) -> tuple[str, Any]:
    """Pull (tool_name, tool_input) from a PreToolUse-shaped payload."""

    for key in ("tool_name", "toolName", "tool", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            tool_input = (
                payload.get("tool_input")
                or payload.get("toolInput")
                or payload.get("arguments")
                or payload.get("command")
                or {}
            )
            return value, tool_input
    command = payload.get("command")
    if isinstance(command, str) and command.strip():
        return "shell", command
    nested = payload.get("hook_input") or payload.get("data") or payload.get("extra")
    if isinstance(nested, Mapping):
        return extract_tool(nested)
    return "", {}


def detail_from_input(tool_input: Any) -> str:
    if isinstance(tool_input, str):
        return redact_text_markers(tool_input)[:500]
    if isinstance(tool_input, Mapping):
        for key in ("command", "path", "file_path", "url", "query", "detail"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return redact_text_markers(value)[:500]
            if isinstance(value, list):
                joined = " ".join(str(part) for part in value)
                if joined.strip():
                    return redact_text_markers(joined)[:500]
        try:
            blob = json.dumps(dict(tool_input), sort_keys=True)
        except (TypeError, ValueError):
            blob = str(tool_input)
        return redact_text_markers(blob)[:500]
    return redact_text_markers(str(tool_input or ""))[:500]


def ask_fields_from_input(tool_input: Any) -> tuple[str, tuple[Any, ...]]:
    if not isinstance(tool_input, Mapping):
        return "", ()
    question = str(
        tool_input.get("question")
        or tool_input.get("prompt")
        or tool_input.get("text")
        or ""
    ).strip()
    raw = tool_input.get("options") or tool_input.get("choices") or ()
    if isinstance(raw, str):
        options: tuple[Any, ...] = (raw,)
    elif isinstance(raw, Sequence):
        options = tuple(raw)
    else:
        options = ()
    return question, options


def new_request_id() -> str:
    return uuid.uuid4().hex


def build_request(
    *,
    run_id: str,
    tool_name: str,
    tool_input: Any = None,
    request_id: str = "",
    created_at_ms: Optional[int] = None,
) -> GateRequest:
    if is_exit_plan_tool(tool_name):
        plan_body = plan_text_from_tool_input(tool_input) or detail_from_input(tool_input)
        ts = int(created_at_ms if created_at_ms is not None else time.time() * 1000)
        return GateRequest(
            request_id=(request_id or new_request_id()).strip() or new_request_id(),
            run_id=(run_id or "").strip(),
            tool_name=(tool_name or "").strip(),
            tool_class="plan",
            detail=plan_body,
            kind=GATE_KIND_PLAN,
            question="",
            options=(),
            created_at_ms=ts,
        )
    klass = normalize_tool_class(tool_name) or (tool_name or "").strip()
    detail = detail_from_input(tool_input)
    kind = GATE_KIND_ASK if klass == "ask" else GATE_KIND_TOOL
    question, options = ask_fields_from_input(tool_input) if kind == GATE_KIND_ASK else ("", ())
    ts = int(created_at_ms if created_at_ms is not None else time.time() * 1000)
    return GateRequest(
        request_id=(request_id or new_request_id()).strip() or new_request_id(),
        run_id=(run_id or "").strip(),
        tool_name=(tool_name or "").strip(),
        tool_class=klass,
        detail=detail,
        kind=kind,
        question=question,
        options=options,
        created_at_ms=ts,
    )



def gate_inject_dir() -> Path:
    """Directory with sitecustomize.py prepended onto agentic PYTHONPATH."""

    return Path(__file__).resolve().parent / "gate_inject"


def attach_gate_env(
    env: dict[str, str],
    *,
    run_id: str,
    workspace: Optional[Path | str] = None,
    store: Any = None,
    timeout_seconds: Optional[float] = None,
) -> Path:
    """Stamp agentic child env so a PreToolUse hook can hold this run."""

    run_dir = ensure_run_gate_dir(
        resolve_run_gate_dir(run_id=run_id, workspace=workspace, store=store, env=env)
    )
    root = run_dir.parent
    env[ENV_GATE_DIR] = str(run_dir)
    env[ENV_GATE_ROOT] = str(root)
    env[ENV_RUN_ID] = (run_id or "").strip()
    if timeout_seconds is not None:
        env[ENV_TIMEOUT] = str(float(timeout_seconds))
    env.setdefault(ENV_HOOK, "discord-os gate-hook")
    # Prepend sitecustomize inject so puppetmaster agentic PreToolUse really fires.
    inject = gate_inject_dir()
    if (inject / "sitecustomize.py").is_file():
        prev = str(env.get("PYTHONPATH") or "").strip()
        env["PYTHONPATH"] = (
            str(inject) if not prev else f"{inject}{os.pathsep}{prev}"
        )
        env[ENV_INJECT] = "1"
    return run_dir


def hook_stdout_payload(result: GateHoldResult) -> dict[str, Any]:
    """Claude-style permissionDecision. Always + allow both execute the tool."""

    allowed = result.decision in {"allow", "always"}
    decision = "allow" if allowed else "deny"
    reason = result.reason or (
        "Allowed." if allowed else "Denied. Tool was not allowed."
    )
    return {
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
        "permission": decision,
        "continue": allowed,
        "gate_result": result.decision,
        "gate_answer": result.gate_answer,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        },
    }


def deny_result(request_id: str, reason: str, tool_class: str = "") -> GateHoldResult:
    return GateHoldResult(
        request_id=request_id or "unknown",
        decision="deny",
        reason=reason,
        tool_class=tool_class,
    )


def hold_tool_decision(
    store: Any,
    orch: Any,
    *,
    run_id: str,
    tool_name: str,
    tool_input: Any = None,
    detail: str = "",
    timeout_seconds: Optional[float] = None,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleeper: Optional[Sleeper] = None,
    clock: Optional[Clock] = None,
    env: Optional[Mapping[str, str]] = None,
    request_id: str = "",
) -> GateHoldResult:
    """In-process canUseTool: decide, park Discord card, block until resolved."""

    source = env if env is not None else os.environ
    req = build_request(
        run_id=run_id,
        tool_name=tool_name,
        tool_input=tool_input if tool_input is not None else detail,
        request_id=request_id,
    )
    if detail:
        req = GateRequest(
            request_id=req.request_id,
            run_id=req.run_id,
            tool_name=req.tool_name,
            tool_class=req.tool_class,
            detail=redact_text_markers(detail)[:500],
            kind=req.kind,
            question=req.question,
            options=req.options,
            created_at_ms=req.created_at_ms,
        )
    if not req.run_id:
        return deny_result(req.request_id, "missing run_id", req.tool_class)

    channel_id = ""
    thread_id = ""
    if orch is not None:
        getter = getattr(orch.store, "get_run", None) if getattr(orch, "store", None) else None
        run = getter(run_id) if callable(getter) else {}
        task_id = str((run or {}).get("task_id") or "")
        task = {}
        if task_id:
            task = (getattr(orch.store, "get_task", lambda _t: {})(task_id) or {})
            meta_reader = getattr(orch.store, "task_metadata", None)
            meta = meta_reader(task_id) if callable(meta_reader) else {}
            if not isinstance(meta, dict):
                meta = {}
            channel_id = str(task.get("channel_id") or meta.get("channel_id") or "")
            thread_id = str(task.get("thread_id") or meta.get("thread_id") or "")
        else:
            meta = {}
    else:
        meta = {}

    decision = tool_class_decision(
        store,
        req.tool_name or req.tool_class,
        channel_id=channel_id,
        thread_id=thread_id,
    )
    if decision.decision == "deny":
        return deny_result(req.request_id, decision.reason or "denied", decision.tool_class)
    if decision.decision == "allow":
        return GateHoldResult(
            request_id=req.request_id,
            decision="allow",
            reason=decision.reason or "allowed",
            tool_class=decision.tool_class,
        )

    run_dir = ensure_run_gate_dir(
        resolve_run_gate_dir(
            run_id=run_id,
            workspace=getattr(orch, "workspace", None) if orch is not None else None,
            store=store,
            env=source,
        )
    )
    enqueue_request(run_dir, req)
    if orch is not None:
        parked = None
        if req.kind == GATE_KIND_ASK:
            raiser = getattr(orch, "raise_ask_user", None)
            if callable(raiser):
                parked = raiser(
                    run_id,
                    question=req.question or "Choose one.",
                    options=req.options or ("Yes", "No"),
                    live=True,
                    request_id=req.request_id,
                )
        else:
            raiser = getattr(orch, "raise_tool_gate", None)
            if callable(raiser):
                parked = raiser(
                    run_id,
                    tool_class=decision.tool_class or req.tool_class,
                    detail=req.detail,
                    live=True,
                    request_id=req.request_id,
                )
        if isinstance(parked, dict) and parked.get("status") == "denied":
            denied = deny_result(
                req.request_id,
                str(parked.get("summary") or "denied"),
                decision.tool_class or req.tool_class,
            )
            complete_request(run_dir, denied)
            return denied

    def _poll() -> Optional[GateHoldResult]:
        if orch is None:
            return None
        polled = orch.gate_result_for(run_id)
        result = str(polled.get("gate_result") or "").strip().lower()
        if result not in {"allow", "always", "deny"}:
            return None
        return GateHoldResult(
            request_id=req.request_id,
            decision=result,
            gate_answer=str(polled.get("gate_answer") or ""),
            reason=result,
            tool_class=str(polled.get("gate_class") or decision.tool_class),
        )

    held = wait_for_result(
        run_dir,
        req.request_id,
        timeout_seconds=(
            float(timeout_seconds)
            if timeout_seconds is not None
            else gate_timeout_seconds(source)
        ),
        poll_seconds=poll_seconds,
        sleeper=sleeper,
        clock=clock,
        poller=_poll,
        tool_class=decision.tool_class or req.tool_class,
    )
    if (
        held.decision == "deny"
        and held.reason == "timeout"
        and orch is not None
    ):
        try:
            if orch.gate_result_for(run_id).get("awaiting_gate"):
                orch.expire_parked_run(run_id)
        except Exception:
            pass
    return held



def hold_plan_decision(
    store: Any,
    orch: Any,
    *,
    run_id: str,
    plan_text: str = "",
    plan_status: str = "ready",
    summary: str = "",
    timeout_seconds: Optional[float] = None,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleeper: Optional[Sleeper] = None,
    clock: Optional[Clock] = None,
    env: Optional[Mapping[str, str]] = None,
    request_id: str = "",
) -> GateHoldResult:
    """In-process ExitPlanMode: park Approve/Cancel, block until resolved.

    Never Always. Fail closed on empty plan / timeout / deny.
    """

    source = env if env is not None else os.environ
    req = build_request(
        run_id=run_id,
        tool_name="ExitPlanMode",
        tool_input={"plan": plan_text, "summary": summary},
        request_id=request_id,
    )
    if plan_text:
        req = GateRequest(
            request_id=req.request_id,
            run_id=req.run_id,
            tool_name=req.tool_name,
            tool_class="plan",
            detail=redact_text_markers(plan_text)[:4000],
            kind=GATE_KIND_PLAN,
            question="",
            options=(),
            created_at_ms=req.created_at_ms,
        )
    if not req.run_id:
        return deny_result(req.request_id, "missing run_id", "plan")
    if not (req.detail or "").strip():
        return deny_result(req.request_id, "unknown plan", "plan")

    run_dir = ensure_run_gate_dir(
        resolve_run_gate_dir(
            run_id=run_id,
            workspace=getattr(orch, "workspace", None) if orch is not None else None,
            store=store,
            env=source,
        )
    )
    enqueue_request(run_dir, req)
    if orch is not None:
        raiser = getattr(orch, "raise_plan_approve", None)
        if callable(raiser):
            parked = raiser(
                run_id,
                plan_text=req.detail,
                summary=summary,
                plan_status=plan_status or "ready",
            )
            if isinstance(parked, dict) and parked.get("status") == "denied":
                denied = deny_result(
                    req.request_id,
                    str(parked.get("summary") or "denied"),
                    "plan",
                )
                complete_request(run_dir, denied)
                return denied

    def _poll() -> Optional[GateHoldResult]:
        if orch is None:
            return None
        polled = orch.gate_result_for(run_id)
        result = str(polled.get("gate_result") or "").strip().lower()
        # Plan card: allow | deny only (Always is write-gate).
        if result == "always":
            result = "allow"
        if result not in {"allow", "deny"}:
            return None
        return GateHoldResult(
            request_id=req.request_id,
            decision=result,
            gate_answer=str(polled.get("gate_answer") or ""),
            reason=result,
            tool_class="plan",
        )

    held = wait_for_result(
        run_dir,
        req.request_id,
        timeout_seconds=(
            float(timeout_seconds)
            if timeout_seconds is not None
            else gate_timeout_seconds(source)
        ),
        poll_seconds=poll_seconds,
        sleeper=sleeper,
        clock=clock,
        poller=_poll,
        tool_class="plan",
    )
    if (
        held.decision == "deny"
        and held.reason == "timeout"
        and orch is not None
    ):
        try:
            if orch.gate_result_for(run_id).get("awaiting_gate"):
                orch.expire_parked_run(run_id)
        except Exception:
            pass
    return held


def drain_gate_queue(
    orchestrator: Any,
    *,
    env: Optional[Mapping[str, str]] = None,
    now_ms: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Park Discord cards for pending hook files; write results when resolved.

    Fail closed: a pending request older than the approval timeout self-denies.
    """

    if orchestrator is None:
        return []
    source = env if env is not None else os.environ
    store = getattr(orchestrator, "store", None)
    root = resolve_gate_root(
        workspace=getattr(orchestrator, "workspace", None),
        store=store,
        env=source,
    )
    timeout_s = gate_timeout_seconds(source)
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    acted: list[dict[str, Any]] = []
    for run_dir in iter_run_dirs(root):
        for req in list_pending(run_dir):
            existing = read_result(run_dir, req.request_id)
            if existing is not None:
                continue
            polled = {}
            getter = getattr(orchestrator, "gate_result_for", None)
            if callable(getter):
                try:
                    polled = getter(req.run_id) or {}
                except Exception:
                    polled = {}
            result = str(polled.get("gate_result") or "").strip().lower()
            if result in {"allow", "always", "deny"}:
                written = GateHoldResult(
                    request_id=req.request_id,
                    decision=result,
                    gate_answer=str(polled.get("gate_answer") or ""),
                    reason=result,
                    tool_class=str(polled.get("gate_class") or req.tool_class),
                )
                complete_request(run_dir, written)
                acted.append({"action": "resolve", "run_id": req.run_id, **written.to_payload()})
                continue
            aged = req.created_at_ms > 0 and (now - req.created_at_ms) >= int(timeout_s * 1000)
            if aged:
                denied = deny_result(req.request_id, "timeout", req.tool_class)
                complete_request(run_dir, denied)
                expirer = getattr(orchestrator, "expire_parked_run", None)
                if callable(expirer) and polled.get("awaiting_gate"):
                    try:
                        expirer(req.run_id)
                    except Exception:
                        pass
                acted.append({"action": "timeout", "run_id": req.run_id, **denied.to_payload()})
                continue
            if polled.get("awaiting_gate"):
                continue
            # File-queue hook always enqueues; honor write-gate off / session
            # Always here so the blocked worker unblocks without a Discord card.
            if req.kind not in {GATE_KIND_ASK, GATE_KIND_PLAN} and not is_exit_plan_tool(
                req.tool_name
            ):
                channel_id = ""
                thread_id = ""
                try:
                    run = {}
                    getter = getattr(store, "get_run", None) if store is not None else None
                    if callable(getter):
                        run = getter(req.run_id) or {}
                    task_id = str((run or {}).get("task_id") or "")
                    if task_id and store is not None:
                        task = (getattr(store, "get_task", lambda _t: {})(task_id) or {})
                        meta_reader = getattr(store, "task_metadata", None)
                        meta = meta_reader(task_id) if callable(meta_reader) else {}
                        if not isinstance(meta, dict):
                            meta = {}
                        channel_id = str(
                            task.get("channel_id") or meta.get("channel_id") or ""
                        )
                        thread_id = str(
                            task.get("thread_id") or meta.get("thread_id") or ""
                        )
                except Exception:
                    channel_id = ""
                    thread_id = ""
                try:
                    decided = tool_class_decision(
                        store,
                        req.tool_class or req.tool_name,
                        channel_id=channel_id,
                        thread_id=thread_id,
                    )
                except Exception:
                    decided = None
                if decided is not None and decided.decision == "allow":
                    written = GateHoldResult(
                        request_id=req.request_id,
                        decision="allow",
                        reason=decided.reason or "allowed",
                        tool_class=decided.tool_class or req.tool_class,
                    )
                    complete_request(run_dir, written)
                    acted.append(
                        {
                            "action": "auto_allow",
                            "run_id": req.run_id,
                            **written.to_payload(),
                        }
                    )
                    continue
                if decided is not None and decided.decision == "deny":
                    denied = deny_result(
                        req.request_id,
                        decided.reason or "denied",
                        decided.tool_class or req.tool_class,
                    )
                    complete_request(run_dir, denied)
                    acted.append(
                        {"action": "deny", "run_id": req.run_id, **denied.to_payload()}
                    )
                    continue
            try:
                if req.kind == GATE_KIND_ASK:
                    orchestrator.raise_ask_user(
                        req.run_id,
                        question=req.question or "Choose one.",
                        options=req.options or ("Yes", "No"),
                        live=True,
                        request_id=req.request_id,
                    )
                elif req.kind == GATE_KIND_PLAN or is_exit_plan_tool(req.tool_name):
                    orchestrator.raise_plan_approve(
                        req.run_id,
                        plan_text=req.detail,
                        summary="Plan ready. Approve to implement.",
                        plan_status="ready",
                    )
                else:
                    klass = normalize_tool_class(req.tool_class or req.tool_name)
                    if klass is None:
                        denied = deny_result(
                            req.request_id, "unknown tool class", req.tool_class
                        )
                        complete_request(run_dir, denied)
                        acted.append(
                            {"action": "deny", "run_id": req.run_id, **denied.to_payload()}
                        )
                        continue
                    orchestrator.raise_tool_gate(
                        req.run_id,
                        tool_class=klass,
                        detail=req.detail,
                        live=True,
                        request_id=req.request_id,
                    )
                acted.append(
                    {
                        "action": "park",
                        "run_id": req.run_id,
                        "request_id": req.request_id,
                        "tool_class": req.tool_class,
                    }
                )
            except Exception:
                denied = deny_result(req.request_id, "park failed", req.tool_class)
                complete_request(run_dir, denied)
                acted.append({"action": "deny", "run_id": req.run_id, **denied.to_payload()})
    return acted


def run_hook(
    argv: Optional[Sequence[str]] = None,
    *,
    stdin=None,
    stdout=None,
    env: Optional[Mapping[str, str]] = None,
    sleeper: Optional[Sleeper] = None,
    clock: Optional[Clock] = None,
) -> int:
    """PreToolUse CLI. Always exits 0. Decision is JSON on stdout."""

    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="discord-os gate-hook")
    parser.add_argument(
        "--print-attach",
        action="store_true",
        help="Print how the agentic worker attaches this hook",
    )
    args = parser.parse_args(list(argv) if argv is not None else [])
    out = stdout if stdout is not None else sys.stdout
    source = dict(env if env is not None else os.environ)
    if args.print_attach:
        out.write(ATTACH_TEXT)
        if not ATTACH_TEXT.endswith("\n"):
            out.write("\n")
        return 0

    raw = ""
    try:
        stream = stdin if stdin is not None else sys.stdin
        raw = stream.read()
    except Exception:
        raw = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, Mapping):
            payload = {}
    except (json.JSONDecodeError, ValueError):
        payload = {}

    try:
        tool_name, tool_input = extract_tool(payload)
        run_id = str(
            payload.get("run_id") or source.get(ENV_RUN_ID) or ""
        ).strip()
        req = build_request(run_id=run_id, tool_name=tool_name, tool_input=tool_input)
        if not req.run_id or not tool_name:
            result = deny_result(req.request_id or "unknown", "missing run_id or tool")
        elif req.kind == GATE_KIND_PLAN or is_exit_plan_tool(tool_name):
            if not (req.detail or "").strip():
                result = deny_result(req.request_id, "unknown plan", "plan")
            else:
                run_dir = ensure_run_gate_dir(
                    resolve_run_gate_dir(run_id=req.run_id, env=source)
                )
                enqueue_request(run_dir, req)
                result = wait_for_result(
                    run_dir,
                    req.request_id,
                    timeout_seconds=gate_timeout_seconds(source),
                    sleeper=sleeper,
                    clock=clock,
                    tool_class="plan",
                )
        else:
            klass = normalize_tool_class(tool_name)
            if klass is None:
                result = deny_result(req.request_id, "unknown tool class", tool_name)
            elif klass == "read":
                result = GateHoldResult(
                    request_id=req.request_id,
                    decision="allow",
                    reason="read passthrough",
                    tool_class="read",
                )
            else:
                run_dir = ensure_run_gate_dir(
                    resolve_run_gate_dir(run_id=req.run_id, env=source)
                )
                enqueue_request(run_dir, req)
                result = wait_for_result(
                    run_dir,
                    req.request_id,
                    timeout_seconds=gate_timeout_seconds(source),
                    sleeper=sleeper,
                    clock=clock,
                    tool_class=klass,
                )
        out.write(json.dumps(hook_stdout_payload(result)))
        out.write("\n")
    except Exception as exc:
        fallback = hook_stdout_payload(
            deny_result("unknown", f"hook error: {type(exc).__name__}")
        )
        try:
            out.write(json.dumps(fallback))
            out.write("\n")
        except Exception:
            pass
    return 0


ATTACH_TEXT = """# Live ask-gate + ExitPlanMode hook attach

Product compute is OpenRouter / puppetmaster agentic. The worker is a
subprocess, so Discord OS cannot call canUseTool in-process. Attach this
hook so:

- tool-class decisions park Allow / Always / Deny and **block the worker**
- ExitPlanMode / plan-ready parks Approve / Cancel (no Always) and
  **blocks implement** until the phone resolves it

Timeout self-denies (same DISCORD_OS_APPROVAL_TIMEOUT_MINUTES).

Env stamped on every agentic spawn:

  DISCORD_OS_GATE_DIR     per-run queue (pending/ + results/)
  DISCORD_OS_GATE_ROOT    workspace/gates
  DISCORD_OS_RUN_ID       live run id
  DISCORD_OS_GATE_HOOK    discord-os gate-hook

PreToolUse-shaped command (stdin JSON, stdout permissionDecision, exit 0):

  discord-os gate-hook

Listen/orch drains pending/ , parks the card, and writes results/ when
Allow / Deny / Always / Approve / Cancel (or expire) lands. Fail closed:
no result → deny.

Local agentic: PYTHONPATH prepends gate_inject/sitecustomize.py so
AgenticAdapter._execute_tool invokes this hook before each tool.

Path A SSH: gate queue stays on this Mac — gates across SSH are not
wired yet (P1).

In-process adapters: request_tool_hold / request_plan_hold.
"""
