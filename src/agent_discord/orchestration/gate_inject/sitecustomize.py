"""Discord OS PreToolUse inject — makes gate-hook really fire under agentic.

Puppetmaster agentic 1.27 runs tools inside ``AgenticAdapter._execute_tool`` and
never consults a host PreToolUse hook. Discord OS stamps ``DISCORD_OS_GATE_*``
on every local agentic spawn and prepends this directory to ``PYTHONPATH`` so
CPython loads this ``sitecustomize`` and wraps ``_execute_tool``.

Each tool call then runs ``discord-os gate-hook`` (stdin JSON → stdout
``permissionDecision``, always exit 0). Deny / timeout / hook failure → tool
does not run (fail closed). Allow / Always → original tool runs.

Stdlib only: the puppetmaster pipx venv may not import ``agent_discord``.
Path A SSH cooks do not share this Mac's gate queue — see ask-gate residual.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import threading
from typing import Any, Optional

_PATCH_LOCK = threading.Lock()
_PATCHED_MODULES: set[int] = set()

_ENV_DIR = "DISCORD_OS_GATE_DIR"
_ENV_HOOK = "DISCORD_OS_GATE_HOOK"
_ENV_RUN = "DISCORD_OS_RUN_ID"
_ENV_TIMEOUT = "DISCORD_OS_GATE_TIMEOUT_SECONDS"
_ENV_INJECT = "DISCORD_OS_GATE_INJECT"


def gate_env_armed(env: Optional[dict[str, str]] = None) -> bool:
    source = env if env is not None else os.environ
    if str(source.get(_ENV_INJECT) or "").strip() in {"0", "false", "no", "off"}:
        return False
    return bool(
        str(source.get(_ENV_DIR) or "").strip()
        or str(source.get(_ENV_HOOK) or "").strip()
        or str(source.get(_ENV_RUN) or "").strip()
    )


def _hook_argv(env: Optional[dict[str, str]] = None) -> list[str]:
    source = env if env is not None else os.environ
    raw = str(source.get(_ENV_HOOK) or "discord-os gate-hook").strip()
    parts = raw.split()
    if not parts:
        parts = ["discord-os", "gate-hook"]
    # Never invent flags; only resolve the executable on PATH.
    exe = shutil.which(parts[0]) or parts[0]
    return [exe, *parts[1:]]


def _timeout_seconds(env: Optional[dict[str, str]] = None) -> float:
    source = env if env is not None else os.environ
    raw = str(source.get(_ENV_TIMEOUT) or "").strip()
    if raw:
        try:
            return max(1.0, float(raw) + 5.0)
        except ValueError:
            pass
    # Match product default approval timeout (+ small CLI overhead).
    return (20 * 60) + 30.0


def _parse_hook_stdout(text: str) -> dict[str, Any]:
    blob = (text or "").strip()
    if not blob:
        return {}
    # Hook prints one JSON object; tolerate trailing noise.
    for line in reversed(blob.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def invoke_gate_hook(
    tool_name: str,
    tool_input: Any = None,
    *,
    env: Optional[dict[str, str]] = None,
    runner: Any = None,
) -> dict[str, Any]:
    """Run PreToolUse-shaped ``discord-os gate-hook``. Fail closed."""

    source = dict(env if env is not None else os.environ)
    payload = {
        "hookEventName": "PreToolUse",
        "tool_name": tool_name,
        "toolName": tool_name,
        "tool_input": tool_input if tool_input is not None else {},
        "run_id": str(source.get(_ENV_RUN) or "").strip(),
    }
    argv = _hook_argv(source)
    run = runner or subprocess.run
    try:
        proc = run(
            argv,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=_timeout_seconds(source),
            env=source,
        )
    except Exception as exc:  # noqa: BLE001 — fail closed, never crash worker
        return {
            "permissionDecision": "deny",
            "permissionDecisionReason": f"hook invoke failed: {type(exc).__name__}",
            "continue": False,
        }
    data = _parse_hook_stdout(getattr(proc, "stdout", "") or "")
    if not data:
        return {
            "permissionDecision": "deny",
            "permissionDecisionReason": "hook returned no decision",
            "continue": False,
        }
    return data


def decision_allows(payload: dict[str, Any]) -> bool:
    decision = str(
        payload.get("permissionDecision")
        or payload.get("permission")
        or payload.get("gate_result")
        or ""
    ).strip().lower()
    if decision in {"allow", "always"}:
        return True
    if payload.get("continue") is True and decision not in {"deny", "block", "denied"}:
        return True
    return False


def deny_message(payload: dict[str, Any], tool_name: str) -> str:
    reason = str(
        payload.get("permissionDecisionReason")
        or payload.get("reason")
        or "Denied. Tool was not allowed."
    ).strip()
    return f"error: tool {tool_name!r} denied by discord-os gate-hook ({reason})"


def patch_execute_tool(adapter_cls: Any, *, runner: Any = None) -> bool:
    """Wrap ``adapter_cls._execute_tool`` once. Returns True when newly patched."""

    if adapter_cls is None:
        return False
    orig = getattr(adapter_cls, "_execute_tool", None)
    if not callable(orig):
        return False
    if getattr(orig, "_discord_os_gate_patched", False):
        return False

    def _wrapped(self: Any, name: str, args: dict, cwd: Any, implement: bool, task: Any) -> str:
        if not gate_env_armed():
            return orig(self, name, args, cwd, implement, task)
        held = invoke_gate_hook(name, args if isinstance(args, dict) else {}, runner=runner)
        if not decision_allows(held):
            return deny_message(held, name)
        return orig(self, name, args, cwd, implement, task)

    _wrapped._discord_os_gate_patched = True  # type: ignore[attr-defined]
    _wrapped._discord_os_gate_original = orig  # type: ignore[attr-defined]
    adapter_cls._execute_tool = _wrapped
    return True


def install_agentic_pretool_patch(*, runner: Any = None) -> bool:
    """Patch puppetmaster ``AgenticAdapter`` if importable and gate env is armed."""

    if not gate_env_armed():
        return False
    try:
        mod = importlib.import_module("puppetmaster.adapters.agentic")
    except Exception:
        return False
    cls = getattr(mod, "AgenticAdapter", None)
    if cls is None:
        return False
    with _PATCH_LOCK:
        marker = id(cls)
        if marker in _PATCHED_MODULES and getattr(
            getattr(cls, "_execute_tool", None), "_discord_os_gate_patched", False
        ):
            return False
        applied = patch_execute_tool(cls, runner=runner)
        if applied:
            _PATCHED_MODULES.add(marker)
        return applied


class _AgenticImportFinder:
    """After ``puppetmaster.adapters.agentic`` loads, install the PreToolUse wrap."""

    def find_module(self, fullname: str, path: Any = None):  # pragma: no cover - py2 API
        return None

    def find_spec(self, fullname: str, path: Any = None, target: Any = None):
        if fullname == "puppetmaster.adapters.agentic":
            # Defer: let the normal finder load, then patch on next opportunity.
            # We schedule via a meta path wrapper on the loaded module below.
            pass
        return None


class _AgenticLoadWatcher:
    """``sys.meta_path`` shim that patches once the agentic module appears."""

    def __init__(self) -> None:
        self._done = False

    def find_spec(self, fullname: str, path: Any = None, target: Any = None):
        if self._done:
            return None
        if fullname == "puppetmaster.adapters.agentic" or (
            fullname == "puppetmaster.adapters" and path is not None
        ):
            # Continue normal import; patch after via exec_module wrap is heavy.
            # Instead poll after import completes using a path hook on the package.
            return None
        if fullname.startswith("puppetmaster.") and "agentic" in sys.modules:
            try:
                if install_agentic_pretool_patch():
                    self._done = True
            except Exception:
                pass
        return None


def _install_import_watcher() -> None:
    # Prefer wrapping builtins.__import__ — reliable across CPython versions.
    if getattr(sys, "_discord_os_gate_import_wrapped", False):
        return
    try:
        import builtins
    except Exception:
        return
    real_import = builtins.__import__

    def _gated_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        mod = real_import(name, globals, locals, fromlist, level)
        try:
            if name == "puppetmaster.adapters.agentic" or (
                name == "puppetmaster.adapters"
                and fromlist
                and "agentic" in fromlist
            ):
                install_agentic_pretool_patch()
            elif name.startswith("puppetmaster") and "puppetmaster.adapters.agentic" in sys.modules:
                install_agentic_pretool_patch()
        except Exception:
            pass
        return mod

    builtins.__import__ = _gated_import  # type: ignore[assignment]
    sys._discord_os_gate_import_wrapped = True  # type: ignore[attr-defined]


def _bootstrap() -> None:
    if not gate_env_armed():
        return
    _install_import_watcher()
    # If agentic is already imported (unusual at sitecustomize time), patch now.
    if "puppetmaster.adapters.agentic" in sys.modules:
        try:
            install_agentic_pretool_patch()
        except Exception:
            pass


_bootstrap()
