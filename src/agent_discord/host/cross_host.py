"""Cross-host read-only status glance.

Allowlisted hosts only (``DISCORD_OS_HOSTS``). Never cooks, never returns SSH
targets or secrets. ``kind=ssh`` reachability uses the soft Path A probe;
unreachable is reported honestly — never a silent local cook fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from agent_discord.host.runners import RemoteHost, load_host_allowlist

ExecFn = Callable[..., tuple[int, str, str]]


def public_host_fields(
    host: RemoteHost,
    *,
    reachable: Optional[bool] = None,
    detail: str = "",
) -> dict[str, Any]:
    """Phone/dashboard-safe host row (no target)."""

    row: dict[str, Any] = {
        "id": host.id,
        "label": host.label,
        "kind": host.kind,
    }
    if reachable is not None:
        row["reachable"] = bool(reachable)
    text = (detail or "").strip()
    if text:
        row["detail"] = text[:160]
    return row


def probe_host_ro(
    host: RemoteHost,
    *,
    exec_fn: Optional[ExecFn] = None,
) -> tuple[bool, str]:
    """Read-only reachability. Never dispatches agentic cook."""

    kind = (host.kind or "").strip().lower()
    if kind == "path":
        kind = "local"
    if kind == "local":
        root = Path(host.target or "").expanduser()
        if not str(host.target or "").strip():
            return False, "missing local target"
        if root.exists():
            return True, "local path ok"
        return False, "local path missing"
    if kind == "ssh":
        from agent_discord.host.remote_cook import probe_ssh_host

        return probe_ssh_host(host, exec_fn=exec_fn)
    return False, f"unknown kind {kind!r}"


def cross_host_ro_status(
    *,
    env: Optional[Mapping[str, str]] = None,
    probe: bool = True,
    exec_fn: Optional[ExecFn] = None,
    allowlist: Optional[Sequence[RemoteHost]] = None,
) -> list[dict[str, Any]]:
    """Status rows for every allowlisted host. Empty allowlist → []."""

    hosts = tuple(allowlist) if allowlist is not None else load_host_allowlist(env=env)
    rows: list[dict[str, Any]] = []
    for host in hosts:
        if probe:
            ok, detail = probe_host_ro(host, exec_fn=exec_fn)
            rows.append(public_host_fields(host, reachable=ok, detail=detail))
        else:
            rows.append(public_host_fields(host))
    return rows
