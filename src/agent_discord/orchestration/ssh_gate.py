"""Path A SSH gate parity / live Discord bridge.

Local agentic PreToolUse holds on this Mac's ``DISCORD_OS_GATE_*`` file queue.
Remote ``puppetmaster agentic`` over SSH does not share that filesystem.

Default (``DISCORD_OS_SSH_GATES`` unset):
* When HOST write-gate is on → spoken **Need** + remote Deny inject for
  write/edit/shell tools (honest; never silent ungated writes).
* When write-gate is off → SSH cook unchanged.

``DISCORD_OS_SSH_GATES=bridge`` (**OPT-IN** live reverse hold):
* Remote inject emits ``DISCORD_OS_GATE_PENDING=`` markers, holds on a remote
  temp queue, and waits for Allow / Always / Deny results.
* Mac Path A progress pipe mirrors pending into the local gate queue so
  listen/orch parks phone cards, then SSH-writes results back.
* Fail closed when bridge cannot arm (missing run_id / wrap failure) — never
  silent ungated remote writes while bridge was requested.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import textwrap
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

SSH_GATES_GAP = "gates do not cross SSH yet"
SSH_GATES_ENV = "DISCORD_OS_SSH_GATES"
GATE_PENDING_MARKER = "DISCORD_OS_GATE_PENDING="
SSH_GATE_DIR_ENV = "DISCORD_OS_SSH_GATE_DIR"
DEFAULT_BRIDGE_CONTROL_PATH = "/tmp/discord-os-ssh-cm-%r@%h:%p"

ExecFn = Callable[..., Any]


def ssh_gates_cross(*, env: Optional[Mapping[str, str]] = None) -> bool:
    """True when live Discord gate bridge across SSH is enabled.

    Default False — honest. Set ``DISCORD_OS_SSH_GATES=bridge`` for Path A
    reverse hold (phone Allow / Deny / Always across SSH cook).
    """

    source = env if env is not None else os.environ
    raw = str(source.get(SSH_GATES_ENV) or "").strip().lower()
    return raw in {"bridge", "1", "true", "yes", "on"}


def spoken_ssh_gates_need(host_id: str) -> str:
    hid = (host_id or "ssh").strip() or "ssh"
    return (
        f"Need: {SSH_GATES_GAP} on `{hid}` — write-gate holds are local-only. "
        "Remote write/edit/shell tools Deny until Path A gate bridge; "
        "cook analyze/read on SSH or turn write-gate off for ungated remote writes. "
        "Set DISCORD_OS_SSH_GATES=bridge for live phone Allow/Deny across SSH."
    )


def spoken_ssh_gates_bridge_armed(host_id: str) -> str:
    hid = (host_id or "ssh").strip() or "ssh"
    return (
        f"SSH gate bridge armed on `{hid}` — phone Allow / Deny / Always "
        "holds remote tools across Path A."
    )


def spoken_ssh_gates_bridge_denied(host_id: str, *, detail: str = "") -> str:
    hid = (host_id or "ssh").strip() or "ssh"
    extra = f" ({detail.strip()[:160]})" if (detail or "").strip() else ""
    return (
        f"Denied. SSH gate bridge cannot arm on `{hid}`{extra}. "
        "Fail closed — remote cook not started ungated. "
        "Unset DISCORD_OS_SSH_GATES or fix SSH BatchMode / run_id."
    )


def write_gate_blocks_ssh(*, store: Any = None) -> bool:
    """True when HOST write-gate is on (SSH should speak Need / fail-close writes)."""

    if store is None:
        return False
    try:
        from agent_discord.orchestration.service import writes_need_approval

        return bool(writes_need_approval(store))
    except Exception:
        return False


def remote_gate_dir_for_run(run_id: str) -> str:
    """Deterministic remote temp queue path for one Path A run."""

    text = (run_id or "").strip() or "unknown"
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)
    safe = (cleaned[:80] or "unknown")
    return f"/tmp/discord-os-ssh-gate-{safe}"


def bridge_control_path(
    *,
    explicit: str = "",
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """ControlPath for bridge writeback / Cancel. Env wins; else a safe default."""

    path = (explicit or "").strip()
    if path:
        return path
    source = env if env is not None else os.environ
    from_env = (source.get("DISCORD_OS_SSH_CONTROL_PATH") or "").strip()
    if from_env:
        return from_env
    return DEFAULT_BRIDGE_CONTROL_PATH


# --- Deny-only inject (gap mode; write-gate on, bridge off) -----------------

_REMOTE_GATE_DENY_INJECT = textwrap.dedent(
    r"""
    import os, sys, threading
    _LOCK = threading.Lock()
    _PATCHED = set()
    _GATED = frozenset({
        "shell", "bash", "write", "edit", "browser", "network", "git", "mcp",
        "implement", "createfile", "create_file", "strreplace", "multiedit",
        "run_command", "run_terminal", "write_file", "edit_file", "delete_file",
        "web_fetch", "webfetch", "websearch",
    })

    def _armed():
        return str(os.environ.get("DISCORD_OS_SSH_WRITE_GATE") or "").strip().lower() in {
            "1", "true", "yes", "on",
        }

    def _norm(name: str) -> str:
        return (name or "").strip().lower().replace("-", "_")

    def _gated(name: str) -> bool:
        t = _norm(name)
        if t in _GATED:
            return True
        if "__" in t:
            return t.rsplit("__", 1)[-1] in _GATED
        return False

    def _deny_msg(name: str) -> str:
        return (
            "error: tool %r denied by discord-os ssh gate "
            "(Denied. Need: gates do not cross SSH yet — write-gate holds are "
            "local-only. Tool blocked on Path A until bridge.)"
        ) % (name or "tool",)

    def _wrap(mod):
        mid = id(mod)
        with _LOCK:
            if mid in _PATCHED:
                return
            _PATCHED.add(mid)
        adapter = getattr(mod, "AgenticAdapter", None)
        if adapter is None:
            return
        orig = getattr(adapter, "_execute_tool", None)
        if not callable(orig):
            return
        if getattr(orig, "_discord_os_ssh_deny_patched", False):
            return

        def _execute_tool(self, name, args=None, cwd=None, implement=False, task=None, *a, **kw):
            if _armed() and _gated(str(name or "")):
                return _deny_msg(str(name or ""))
            return orig(self, name, args, cwd, implement, task, *a, **kw)

        _execute_tool._discord_os_ssh_deny_patched = True
        adapter._execute_tool = _execute_tool

    def _boot():
        if not _armed():
            return
        for modname in ("puppetmaster.adapters.agentic", "puppetmaster.agentic"):
            try:
                __import__(modname)
                _wrap(sys.modules[modname])
            except Exception:
                pass
        # Import watcher for late agentic load
        try:
            import builtins
            real = builtins.__import__
            def _imp(name, globals=None, locals=None, fromlist=(), level=0):
                mod = real(name, globals, locals, fromlist, level)
                try:
                    if "agentic" in name and name in sys.modules:
                        _wrap(sys.modules[name])
                except Exception:
                    pass
                return mod
            builtins.__import__ = _imp
        except Exception:
            pass

    _boot()
    """
).lstrip()


# --- Live bridge inject -----------------------------------------------------

_REMOTE_GATE_BRIDGE_INJECT = textwrap.dedent(
    r"""
    import os, sys, json, time, threading, uuid, base64
    _LOCK = threading.Lock()
    _PATCHED = set()
    _READ = frozenset({
        "read", "read_file", "readfile", "read_offload", "list_dir", "listdir",
        "search_code", "graph_search", "graph_context",
    })
    _ASK = frozenset({
        "ask", "askuserquestion", "ask_user", "ask_user_question",
    })
    _PLAN = frozenset({
        "exitplanmode", "exit_plan_mode", "presentplan", "present_plan",
        "plan_ready", "planready",
    })

    def _armed():
        return str(os.environ.get("DISCORD_OS_SSH_GATE_BRIDGE") or "").strip().lower() in {
            "1", "true", "yes", "on", "bridge",
        }

    def _gate_dir():
        return str(os.environ.get("DISCORD_OS_SSH_GATE_DIR") or "").strip()

    def _run_id():
        return str(os.environ.get("DISCORD_OS_RUN_ID") or "").strip()

    def _timeout():
        raw = str(os.environ.get("DISCORD_OS_GATE_TIMEOUT_SECONDS") or "").strip()
        if raw:
            try:
                return max(1.0, float(raw))
            except Exception:
                pass
        return 20 * 60

    def _norm(name):
        return (name or "").strip().lower().replace("-", "_")

    def _is_read(name):
        return _norm(name) in _READ

    def _kind(name, args):
        t = _norm(name)
        if t in _ASK or t.endswith("askuserquestion"):
            return "ask_user"
        if t in _PLAN or "plan_status" in (args or {}) or (isinstance(args, dict) and str(args.get("plan_status") or "").lower() == "ready"):
            return "plan"
        return "tool_class"

    def _detail(args):
        if isinstance(args, str):
            return args[:500]
        if not isinstance(args, dict):
            return str(args or "")[:500]
        for k in ("command", "path", "file_path", "url", "query", "detail", "plan", "question"):
            v = args.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()[:500]
        try:
            return json.dumps(args, sort_keys=True)[:500]
        except Exception:
            return str(args)[:500]

    def _ask_fields(args):
        if not isinstance(args, dict):
            return "", [], False
        q = str(args.get("question") or args.get("prompt") or args.get("text") or "").strip()
        raw = args.get("options") or args.get("choices") or []
        if isinstance(raw, str):
            opts = [raw]
        elif isinstance(raw, (list, tuple)):
            opts = list(raw)
        else:
            opts = []
        multi = args.get("allow_multiple", args.get("allowMultiple", args.get("multiSelect", False)))
        if isinstance(multi, str):
            multi = multi.strip().lower() in {"1", "true", "yes", "on"}
        return q, opts, bool(multi)

    def _ensure(dirpath):
        os.makedirs(os.path.join(dirpath, "pending"), exist_ok=True)
        os.makedirs(os.path.join(dirpath, "results"), exist_ok=True)

    def _atomic_write(path, payload):
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".%s.tmp" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)

    def _emit_pending(payload):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        b64 = base64.b64encode(raw).decode("ascii")
        line = "DISCORD_OS_GATE_PENDING=%s\n" % b64
        try:
            sys.stdout.write(line)
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.write(line)
            sys.stderr.flush()
        except Exception:
            pass

    def _wait_result(dirpath, request_id, timeout_s):
        result_path = os.path.join(dirpath, "results", request_id + ".json")
        deadline = time.time() + float(timeout_s)
        while time.time() < deadline:
            if os.path.isfile(result_path):
                try:
                    with open(result_path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
            time.sleep(0.05)
        return {
            "request_id": request_id,
            "decision": "deny",
            "gate_result": "deny",
            "reason": "timeout",
        }

    def _hold(name, args):
        dirpath = _gate_dir()
        rid = _run_id()
        if not dirpath or not rid:
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": "SSH gate bridge not armed (missing gate dir or run_id)",
            }
        if _is_read(name):
            return {"permissionDecision": "allow", "permissionDecisionReason": "read passthrough"}
        _ensure(dirpath)
        req_id = uuid.uuid4().hex
        kind = _kind(name, args if isinstance(args, dict) else {})
        question, options, allow_multiple = _ask_fields(args if isinstance(args, dict) else {})
        detail = _detail(args)
        if kind == "plan" and not detail.strip():
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": "unknown plan",
            }
        payload = {
            "v": 1,
            "request_id": req_id,
            "run_id": rid,
            "tool_name": str(name or ""),
            "tool_class": str(name or ""),
            "detail": detail,
            "kind": kind,
            "question": question,
            "options": options,
            "allow_multiple": allow_multiple,
            "created_at_ms": int(time.time() * 1000),
            "remote_gate_dir": dirpath,
            "ssh_bridge": True,
        }
        _atomic_write(os.path.join(dirpath, "pending", req_id + ".json"), payload)
        _emit_pending(payload)
        result = _wait_result(dirpath, req_id, _timeout())
        decision = str(
            result.get("decision") or result.get("gate_result") or "deny"
        ).strip().lower()
        if decision in {"allow", "always"}:
            return {
                "permissionDecision": "allow",
                "permissionDecisionReason": str(result.get("reason") or "Allowed."),
                "gate_result": decision,
                "gate_answer": str(result.get("gate_answer") or ""),
            }
        return {
            "permissionDecision": "deny",
            "permissionDecisionReason": str(
                result.get("reason") or "Denied. Tool was not allowed."
            ),
            "gate_result": "deny",
            "gate_answer": str(result.get("gate_answer") or ""),
        }

    def _deny_msg(held, name):
        reason = str(
            held.get("permissionDecisionReason") or held.get("reason") or "Denied."
        ).strip()
        return "error: tool %r denied by discord-os ssh gate bridge (%s)" % (
            name or "tool",
            reason,
        )

    def _wrap(mod):
        mid = id(mod)
        with _LOCK:
            if mid in _PATCHED:
                return
            _PATCHED.add(mid)
        adapter = getattr(mod, "AgenticAdapter", None)
        if adapter is None:
            return
        orig = getattr(adapter, "_execute_tool", None)
        if not callable(orig):
            return
        if getattr(orig, "_discord_os_ssh_bridge_patched", False):
            return

        def _execute_tool(self, name, args=None, cwd=None, implement=False, task=None, *a, **kw):
            if not _armed():
                return orig(self, name, args, cwd, implement, task, *a, **kw)
            held = _hold(str(name or ""), args if isinstance(args, dict) else {})
            decision = str(
                held.get("permissionDecision") or held.get("gate_result") or "deny"
            ).strip().lower()
            if decision in {"allow", "always"}:
                return orig(self, name, args, cwd, implement, task, *a, **kw)
            return _deny_msg(held, str(name or ""))

        _execute_tool._discord_os_ssh_bridge_patched = True
        adapter._execute_tool = _execute_tool

    def _boot():
        if not _armed():
            return
        if not _gate_dir() or not _run_id():
            return
        for modname in ("puppetmaster.adapters.agentic", "puppetmaster.agentic"):
            try:
                __import__(modname)
                _wrap(sys.modules[modname])
            except Exception:
                pass
        try:
            import builtins
            real = builtins.__import__
            def _imp(name, globals=None, locals=None, fromlist=(), level=0):
                mod = real(name, globals, locals, fromlist, level)
                try:
                    if name == "puppetmaster.adapters.agentic" or (
                        name == "puppetmaster.adapters" and fromlist and "agentic" in fromlist
                    ):
                        _wrap(sys.modules.get("puppetmaster.adapters.agentic") or mod)
                    elif "agentic" in sys.modules:
                        _wrap(sys.modules["puppetmaster.adapters.agentic"]) if "puppetmaster.adapters.agentic" in sys.modules else None
                except Exception:
                    pass
                return mod
            builtins.__import__ = _imp
        except Exception:
            pass

    _boot()
    """
).lstrip()


def remote_gate_inject_script() -> str:
    """Python source for remote Deny-only sitecustomize (gap mode)."""

    return _REMOTE_GATE_DENY_INJECT


def remote_gate_bridge_inject_script() -> str:
    """Python source for remote live-bridge sitecustomize."""

    return _REMOTE_GATE_BRIDGE_INJECT


def wrap_remote_argv_with_ssh_gate(
    remote_argv: Sequence[str],
    *,
    enabled: bool,
) -> list[str]:
    """When enabled, wrap remote argv so gated tools Deny with spoken Need (gap)."""

    if not enabled or not remote_argv:
        return list(remote_argv)
    raw = remote_gate_inject_script().encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    inner = " ".join(shlex.quote(str(p)) for p in remote_argv)
    script = (
        "set -e; "
        "d=$(mktemp -d /tmp/discord-os-ssh-gate.XXXXXX); "
        f"echo {shlex.quote(b64)} | base64 -d > \"$d/sitecustomize.py\"; "
        "export PYTHONPATH=\"$d${PYTHONPATH:+:$PYTHONPATH}\"; "
        "export DISCORD_OS_SSH_WRITE_GATE=1; "
        f"exec {inner}"
    )
    return ["bash", "-lc", script]


def wrap_remote_argv_with_ssh_gate_bridge(
    remote_argv: Sequence[str],
    *,
    run_id: str,
    remote_gate_dir: str = "",
    timeout_seconds: float = 20 * 60,
) -> list[str]:
    """Wrap remote argv for live Discord Allow/Deny bridge across SSH.

    Fail closed: empty run_id → empty list (caller must Deny, not cook ungated).
    """

    rid = (run_id or "").strip()
    if not remote_argv or not rid:
        return []
    gate_dir = (remote_gate_dir or "").strip() or remote_gate_dir_for_run(rid)
    raw = remote_gate_bridge_inject_script().encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    inner = " ".join(shlex.quote(str(p)) for p in remote_argv)
    timeout = max(1.0, float(timeout_seconds))
    script = (
        "set -e; "
        f"d={shlex.quote(gate_dir)}; "
        "mkdir -p \"$d/pending\" \"$d/results\"; "
        "inj=$(mktemp -d /tmp/discord-os-ssh-bridge-inj.XXXXXX); "
        f"echo {shlex.quote(b64)} | base64 -d > \"$inj/sitecustomize.py\"; "
        "export PYTHONPATH=\"$inj${PYTHONPATH:+:$PYTHONPATH}\"; "
        "export DISCORD_OS_SSH_GATE_BRIDGE=1; "
        f"export DISCORD_OS_SSH_GATE_DIR={shlex.quote(gate_dir)}; "
        f"export DISCORD_OS_RUN_ID={shlex.quote(rid)}; "
        f"export DISCORD_OS_GATE_TIMEOUT_SECONDS={shlex.quote(str(timeout))}; "
        f"exec {inner}"
    )
    return ["bash", "-lc", script]


def parse_gate_pending_line(line: str) -> Optional[dict[str, Any]]:
    """Decode a ``DISCORD_OS_GATE_PENDING=`` progress line into a request dict."""

    text = (line or "").strip()
    if GATE_PENDING_MARKER not in text:
        return None
    try:
        raw_b64 = text.split(GATE_PENDING_MARKER, 1)[1].split()[0]
    except (IndexError, ValueError):
        return None
    try:
        blob = base64.b64decode(raw_b64.encode("ascii"), validate=False)
        data = json.loads(blob.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if not str(data.get("request_id") or "").strip():
        return None
    if not str(data.get("run_id") or "").strip():
        return None
    return data


def encode_gate_pending_line(payload: Mapping[str, Any]) -> str:
    """Encode a pending payload as a progress-pipe marker line (no trailing NL)."""

    raw = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    return f"{GATE_PENDING_MARKER}{b64}"


def mirror_gate_pending_to_local(
    payload: Mapping[str, Any],
    *,
    gate_root: Optional[Path | str] = None,
    workspace: Optional[Path | str] = None,
    store: Any = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Write a remote bridge pending request into this Mac's gate queue."""

    from agent_discord.orchestration.gate_hook import (
        GateRequest,
        enqueue_request,
        ensure_run_gate_dir,
        resolve_run_gate_dir,
        run_gate_dir,
    )

    def _safe_run_id(run_id: str) -> str:
        text = (run_id or "").strip() or "unknown"
        cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)
        return cleaned[:80] or "unknown"

    request_id = str(payload.get("request_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    if not request_id or not run_id:
        return None
    options = payload.get("options") if isinstance(payload.get("options"), list) else []
    created = payload.get("created_at_ms") or 0
    try:
        created_ms = int(created)
    except (TypeError, ValueError):
        created_ms = int(time.time() * 1000)
    kind = str(payload.get("kind") or "tool_class")
    req = GateRequest(
        request_id=request_id,
        run_id=run_id,
        tool_name=str(payload.get("tool_name") or ""),
        tool_class=str(payload.get("tool_class") or payload.get("tool_name") or ""),
        detail=str(payload.get("detail") or "")[:500],
        kind=kind,
        question=str(payload.get("question") or ""),
        options=tuple(options),
        allow_multiple=bool(payload.get("allow_multiple")),
        created_at_ms=created_ms,
    )
    source = env if env is not None else os.environ
    if gate_root is not None:
        root_path = Path(gate_root)
        if (root_path / "pending").is_dir() or root_path.name == _safe_run_id(run_id):
            run_dir = ensure_run_gate_dir(root_path)
        else:
            run_dir = ensure_run_gate_dir(run_gate_dir(root_path, run_id))
    else:
        run_dir = ensure_run_gate_dir(
            resolve_run_gate_dir(
                run_id=run_id, workspace=workspace, store=store, env=source
            )
        )
    # Sidecar so writeback knows the remote path.
    remote_dir = str(payload.get("remote_gate_dir") or "").strip()
    if remote_dir:
        try:
            meta_path = Path(run_dir) / "pending" / f".{request_id}.ssh_bridge.json"
            meta_path.write_text(
                json.dumps(
                    {
                        "remote_gate_dir": remote_dir,
                        "request_id": request_id,
                        "run_id": run_id,
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
    return enqueue_request(run_dir, req)


def ssh_write_gate_result(
    target: str,
    remote_gate_dir: str,
    result: Mapping[str, Any],
    *,
    control_path: str = "",
    exec_fn: Optional[ExecFn] = None,
    timeout_seconds: float = 15.0,
) -> bool:
    """Push one gate result JSON onto the remote queue via BatchMode SSH."""

    tgt = (target or "").strip()
    remote_dir = (remote_gate_dir or "").strip()
    request_id = str(result.get("request_id") or "").strip()
    if not tgt or not remote_dir or not request_id:
        return False
    # Refuse path traversal / shell metacharacters in remote path pieces.
    if any(ch in remote_dir for ch in ("\n", "\r", ";", "|", "&", "`", "$", " ", "\t")):
        # Allow only simple /tmp/... paths
        if not remote_dir.startswith("/tmp/discord-os-ssh-gate-"):
            return False
    if any(ch in request_id for ch in ("/", "\\", "\n", "\r", ";", " ", "\t")):
        return False
    payload = dict(result)
    payload.setdefault("decision", payload.get("gate_result") or "deny")
    payload.setdefault("gate_result", payload["decision"])
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    results_dir = f"{remote_dir.rstrip('/')}/results"
    out_path = f"{results_dir}/{request_id}.json"
    remote_cmd = (
        f"mkdir -p {shlex.quote(results_dir)} && "
        f"echo {shlex.quote(b64)} | base64 -d > {shlex.quote(out_path)}"
    )
    argv = ["ssh", "-o", "BatchMode=yes"]
    cpath = (control_path or "").strip()
    if cpath:
        # Stale multiplex socket → writeback hang / lost Allow. Clear first.
        try:
            from agent_discord.puppetmaster.cancel_honesty import (
                ensure_ssh_controlmaster_fresh,
            )

            ensure_ssh_controlmaster_fresh(
                tgt, control_path=cpath, exec_fn=exec_fn, timeout_seconds=5.0
            )
        except Exception:
            pass
        argv.extend(
            [
                "-o",
                "ControlMaster=auto",
                "-o",
                f"ControlPath={cpath}",
                "-o",
                "ControlPersist=60",
            ]
        )
    argv.extend([tgt, remote_cmd])
    try:
        if exec_fn is not None:
            proc = exec_fn(argv, timeout_seconds=float(timeout_seconds))
            return int(getattr(proc, "returncode", 1) or 0) == 0
        import subprocess

        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
            check=False,
        )
        return completed.returncode == 0
    except Exception:
        return False


def flush_bridge_writebacks(
    *,
    run_id: str,
    host_target: str,
    pending_remote: Mapping[str, str],
    gate_root: Optional[Path | str] = None,
    workspace: Optional[Path | str] = None,
    store: Any = None,
    control_path: str = "",
    exec_fn: Optional[ExecFn] = None,
    env: Optional[Mapping[str, str]] = None,
) -> list[str]:
    """For bridged request_ids with a local result, SSH-push to remote. Returns written ids."""

    from agent_discord.orchestration.gate_hook import (
        read_result,
        resolve_run_gate_dir,
        ensure_run_gate_dir,
        run_gate_dir,
    )

    if not pending_remote:
        return []
    source = env if env is not None else os.environ
    if gate_root is not None:
        root = Path(gate_root)
        if (root / "pending").is_dir():
            run_dir = root
        else:
            run_dir = ensure_run_gate_dir(run_gate_dir(root, run_id))
    else:
        run_dir = ensure_run_gate_dir(
            resolve_run_gate_dir(
                run_id=run_id, workspace=workspace, store=store, env=source
            )
        )
    written: list[str] = []
    for request_id, remote_dir in list(pending_remote.items()):
        held = read_result(run_dir, request_id)
        if held is None:
            continue
        ok = ssh_write_gate_result(
            host_target,
            remote_dir,
            held.to_payload(),
            control_path=control_path,
            exec_fn=exec_fn,
        )
        if ok:
            written.append(request_id)
    return written
