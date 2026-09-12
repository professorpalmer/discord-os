"""Path A SSH gate parity / honesty.

Local agentic PreToolUse holds on this Mac's ``DISCORD_OS_GATE_*`` file queue.
Remote ``puppetmaster agentic`` over SSH does **not** share that queue, so
phone Allow / Always / Deny cards cannot hold the remote worker the same way.

When HOST write-gate is on:
* Cook emits a spoken **Need** (progress) so the phone knows.
* Remote inject (best-effort) fail-closes write/edit/shell/git/mcp tools with
  an honest Deny reason instead of silently running ungated.

When write-gate is off, SSH cook is unchanged. Full live Discord hold across
SSH remains residual until ``DISCORD_OS_SSH_GATES=bridge``.
"""

from __future__ import annotations

import base64
import os
import shlex
import textwrap
from typing import Any, Mapping, Optional, Sequence

SSH_GATES_GAP = "gates do not cross SSH yet"
SSH_GATES_ENV = "DISCORD_OS_SSH_GATES"


def ssh_gates_cross(*, env: Optional[Mapping[str, str]] = None) -> bool:
    """True only when a live Discord gate bridge across SSH is enabled.

    Default False — honest. Set ``DISCORD_OS_SSH_GATES=bridge`` when Path A
    reverse hold ships; do not pretend today.
    """

    source = env if env is not None else os.environ
    raw = str(source.get(SSH_GATES_ENV) or "").strip().lower()
    return raw in {"bridge", "1", "true", "yes", "on"}


def spoken_ssh_gates_need(host_id: str) -> str:
    hid = (host_id or "ssh").strip() or "ssh"
    return (
        f"Need: {SSH_GATES_GAP} on `{hid}` — write-gate holds are local-only. "
        "Remote write/edit/shell tools Deny until Path A gate bridge; "
        "cook analyze/read on SSH or turn write-gate off for ungated remote writes."
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


_REMOTE_GATE_INJECT = textwrap.dedent(
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

    def _name(tool):
        if isinstance(tool, dict):
            for k in ("name", "tool_name", "toolName"):
                v = tool.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return str(getattr(tool, "name", "") or "").strip()

    def _gated(name: str) -> bool:
        t = (name or "").strip().lower().replace("-", "_")
        if t in _GATED:
            return True
        if "__" in t:
            return t.rsplit("__", 1)[-1] in _GATED
        return False

    def _deny(name: str):
        reason = (
            "Denied. Need: gates do not cross SSH yet — write-gate holds are "
            "local-only. Tool `%s` blocked on Path A until bridge."
        ) % (name or "tool")
        raise RuntimeError(reason)

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

        def _execute_tool(self, *args, **kwargs):
            if _armed():
                tool = args[0] if args else kwargs.get("tool")
                name = _name(tool)
                if _gated(name):
                    _deny(name)
            return orig(self, *args, **kwargs)

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

    _boot()
    """
).lstrip()


def remote_gate_inject_script() -> str:
    """Python source for a remote sitecustomize gate fail-closed shim."""

    return _REMOTE_GATE_INJECT


def wrap_remote_argv_with_ssh_gate(
    remote_argv: Sequence[str],
    *,
    enabled: bool,
) -> list[str]:
    """When enabled, wrap remote argv so gated tools Deny with spoken Need."""

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
