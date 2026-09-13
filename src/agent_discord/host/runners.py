"""Multi-host runners — fail-closed allowlist seam.

Empty ``DISCORD_OS_HOSTS`` keeps today's single-host behavior (this Mac).
Unknown host ids are Denied; there is no silent local fallback to a
stranger host. Off / On / status stay on the control-plane Mac. SSH argv
never carries tokens or passwords (agent / ssh config only).

``kind=ssh`` cooks via Path A remote cook (``host_runner_argv`` + SSH
``BatchMode=yes`` → remote ``puppetmaster agentic``). Unreachable / disabled
SSH is spoken Deny — never a silent local cook on the control-plane Mac.
``kind=local`` / path hosts still supply a local cwd on this Mac.
"""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from agent_discord.host.realms import binding_metadata

HOST_KINDS = frozenset({"local", "ssh"})
_CREDENTIAL_MARKERS = (
    "token",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "BEGIN ",
)


class HostAllowlistError(ValueError):
    """Unknown or unsafe host routing — fail closed, spoken Deny."""

    def __init__(self, message: str, *, host_id: str = "") -> None:
        super().__init__(message)
        self.host_id = (host_id or "").strip()
        self.spoken = str(message)


@dataclass(frozen=True)
class RemoteHost:
    id: str
    label: str
    kind: str  # local | ssh
    target: str  # local path root OR ssh user@host
    channel_ids: tuple[str, ...] = ()
    workdir: str = ""


def power_stays_local() -> bool:
    """HOST On / Off / status never route to a remote runner."""

    return True


def spoken_host_deny(host_id: str, *, reason: str = "not allowlisted") -> str:
    key = (host_id or "").strip() or "(empty)"
    why = (reason or "not allowlisted").strip() or "not allowlisted"
    return f"Denied. Host '{key}' is {why}."


# Legacy Deny string (kill-switch / docs). Path A capable status lives in remote_cook.
SSH_COOK_STATUS = "routing only / Deny until remote cook"


def spoken_ssh_cook_deny(host_id: str) -> str:
    """Spoken Deny when ssh remote cook is disabled or not ready."""

    return spoken_host_deny(host_id, reason=SSH_COOK_STATUS)


def assert_host_cook_allowed(host: Optional[RemoteHost]) -> None:
    """Validate host kind for cook. ``kind=ssh`` is allowed (remote cook path).

    ``None`` and ``kind=local`` cook on this Mac. Unknown kinds Deny.
    Reachability / kill-switch for ssh is enforced by ``remote_cook``
    (spoken Deny; never silent local cook).
    """

    if host is None:
        return
    kind = (host.kind or "").strip().lower()
    if kind == "path":
        kind = "local"
    if kind == "ssh":
        if not (host.target or "").strip():
            raise HostAllowlistError(
                spoken_host_deny(host.id, reason="missing ssh target"),
                host_id=host.id,
            )
        return
    if kind and kind not in HOST_KINDS:
        raise HostAllowlistError(
            spoken_host_deny(host.id, reason=f"has unknown kind {kind!r}"),
            host_id=host.id,
        )


def load_host_allowlist(
    *,
    env: Optional[Mapping[str, str]] = None,
) -> tuple[RemoteHost, ...]:
    """Parse ``DISCORD_OS_HOSTS``. Empty / unset → single-host (no remotes)."""

    source = dict(os.environ if env is None else env)
    raw = (source.get("DISCORD_OS_HOSTS") or "").strip()
    if not raw:
        return ()
    if raw.startswith("["):
        return _parse_hosts_json(raw)
    return _parse_hosts_csv(raw)


def get_host(host_id: str, allowlist: Sequence[RemoteHost]) -> RemoteHost:
    key = (host_id or "").strip().lower()
    if not key:
        raise HostAllowlistError(spoken_host_deny("", reason="missing"), host_id="")
    for host in allowlist:
        if host.id.lower() == key:
            return host
    raise HostAllowlistError(spoken_host_deny(key), host_id=key)


def resolve_channel_host(
    store: Any,
    channel_id: str,
    *,
    workspace_id: str = "default",
    allowlist: Sequence[RemoteHost] = (),
    requested_host_id: Optional[str] = None,
) -> Optional[RemoteHost]:
    """Prefer an allowlisted host for this channel. Unknown → raise (fail closed).

    Returns ``None`` only when routing stays on the local control-plane host
    (empty allowlist and no requested/bound host id).
    """

    requested = (requested_host_id or "").strip().lower()
    bound = _bound_host_id(store, workspace_id, channel_id)
    target = requested or bound
    hosts = tuple(allowlist)

    if target:
        if not hosts:
            raise HostAllowlistError(
                spoken_host_deny(target, reason="not allowlisted"),
                host_id=target,
            )
        return get_host(target, hosts)

    if not hosts:
        return None

    channel = str(channel_id or "").strip()
    if not channel:
        return None
    claimed = [host for host in hosts if channel in host.channel_ids]
    if len(claimed) > 1:
        ids = ", ".join(item.id for item in claimed)
        raise HostAllowlistError(
            spoken_host_deny(
                channel,
                reason=f"claimed by multiple hosts ({ids})",
            ),
            host_id=channel,
        )
    if len(claimed) == 1:
        return claimed[0]
    return None


def bind_channel_host(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    host_id: str,
    allowlist: Sequence[RemoteHost],
) -> RemoteHost:
    chosen = get_host(host_id, allowlist)
    writer = getattr(store, "merge_binding_metadata", None)
    if callable(writer):
        writer(
            workspace_id,
            channel_id,
            {"host_id": chosen.id, "host_label": chosen.label},
        )
    return chosen


def host_runner_argv(
    host: RemoteHost,
    remote_command: Sequence[str],
    *,
    control_path: str = "",
) -> list[str]:
    """Build ssh/local argv for remote cook (Path A). Never puts credentials in argv.

    Used by ``host.remote_cook`` to invoke remote ``puppetmaster agentic`` over
    SSH ``BatchMode=yes`` (agent / ``~/.ssh/config`` only). When ``control_path``
    is set, enable ControlMaster=auto so Cancel can ``ssh -O exit`` best-effort.
    """

    cmd = [str(part) for part in remote_command]
    _refuse_credential_argv(cmd)
    kind = (host.kind or "").strip().lower()
    if kind == "local":
        return list(cmd)
    if kind != "ssh":
        raise HostAllowlistError(
            spoken_host_deny(host.id, reason=f"has unknown kind {kind!r}"),
            host_id=host.id,
        )
    target = (host.target or "").strip()
    if not target:
        raise HostAllowlistError(
            spoken_host_deny(host.id, reason="missing ssh target"),
            host_id=host.id,
        )
    _refuse_credential_argv([target])
    argv = ["ssh", "-o", "BatchMode=yes"]
    cpath = (control_path or "").strip()
    if cpath:
        _refuse_credential_argv([cpath])
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
    argv.append(target)
    workdir = (host.workdir or "").strip()
    if workdir:
        _refuse_credential_argv([workdir])
        remote = (
            "cd "
            + shlex.quote(workdir)
            + " && "
            + " ".join(shlex.quote(part) for part in cmd)
        )
        argv.append(remote)
    else:
        argv.extend(cmd)
    _refuse_credential_argv(argv)
    return argv


def parse_host_bind_command(text: str) -> str:
    """Return host id for ``bind host <id>`` / ``/bind host <id>``; else \"\"."""

    parts = (text or "").strip().split()
    if len(parts) < 3:
        return ""
    first = parts[0].lower().lstrip("/!")
    if first not in {"bind", "realm"}:
        return ""
    if parts[1].strip().lower() != "host":
        return ""
    return parts[2].strip().lower()


def is_host_bind_command(text: str) -> bool:
    return bool(parse_host_bind_command(text))


def validate_host_allowlist(hosts: Sequence[RemoteHost]) -> list[str]:
    """Return doctor FAIL reasons. Empty list means the allowlist is coherent."""

    problems: list[str] = []
    seen: dict[str, int] = {}
    for host in hosts:
        key = (host.id or "").strip().lower()
        if not key:
            problems.append("host entry missing id")
            continue
        seen[key] = seen.get(key, 0) + 1
        kind = (host.kind or "").strip().lower()
        if kind not in HOST_KINDS:
            problems.append(f"host {key!r} kind must be local|ssh, got {host.kind!r}")
        target = (host.target or "").strip()
        if not target:
            problems.append(f"host {key!r} missing target")
        elif kind == "ssh" and _unsafe_ssh_target(target):
            problems.append(
                f"host {key!r} ssh target looks unsafe "
                "(no passwords, -i, or inline secrets)"
            )
    for key, count in seen.items():
        if count > 1:
            problems.append(f"duplicate host id {key!r}")
    return problems


def _bound_host_id(store: Any, workspace_id: str, channel_id: str) -> str:
    reader = getattr(store, "get_binding", None)
    if not callable(reader):
        return ""
    try:
        row = reader(workspace_id, channel_id)
    except Exception:
        return ""
    meta = binding_metadata(row)
    return str(meta.get("host_id") or "").strip().lower()


def _parse_hosts_json(raw: str) -> tuple[RemoteHost, ...]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    found: list[RemoteHost] = []
    for item in parsed:
        if not isinstance(item, Mapping):
            continue
        host = _host_from_mapping(item)
        if host is not None:
            found.append(host)
    return tuple(found)


def _parse_hosts_csv(raw: str) -> tuple[RemoteHost, ...]:
    found: list[RemoteHost] = []
    for item in raw.split(","):
        chunk = item.strip()
        if not chunk:
            continue
        parts = chunk.split(":", 2)
        if len(parts) < 3:
            continue
        host_id, kind, target = (parts[0].strip(), parts[1].strip().lower(), parts[2].strip())
        if not host_id or not target:
            continue
        if kind == "path":
            kind = "local"
        if kind not in HOST_KINDS:
            continue
        found.append(
            RemoteHost(
                id=host_id.lower(),
                label=host_id,
                kind=kind,
                target=target,
            )
        )
    return tuple(found)


def _host_from_mapping(item: Mapping[str, Any]) -> Optional[RemoteHost]:
    host_id = str(item.get("id") or "").strip().lower()
    if not host_id:
        return None
    label = str(item.get("label") or host_id).strip() or host_id
    workdir = str(item.get("workdir") or "").strip()
    channels_raw = item.get("channels") or item.get("channel_ids") or ()
    channel_ids: list[str] = []
    if isinstance(channels_raw, str) and channels_raw.strip():
        channel_ids = [bit.strip() for bit in channels_raw.split(",") if bit.strip()]
    elif isinstance(channels_raw, (list, tuple)):
        channel_ids = [str(bit).strip() for bit in channels_raw if str(bit).strip()]

    ssh = str(item.get("ssh") or "").strip()
    path = str(item.get("path") or "").strip()
    target = str(item.get("target") or "").strip()
    kind = str(item.get("kind") or "").strip().lower()
    if ssh:
        kind = "ssh"
        target = ssh
    elif path:
        kind = "local"
        target = path
    elif not kind:
        if target.startswith("ssh:") or "@" in target:
            kind = "ssh"
            if target.startswith("ssh:"):
                target = target[4:].lstrip("/")
        elif target:
            kind = "local"
    if kind not in HOST_KINDS or not target:
        return None
    return RemoteHost(
        id=host_id,
        label=label,
        kind=kind,
        target=target,
        channel_ids=tuple(channel_ids),
        workdir=workdir,
    )


def _unsafe_ssh_target(target: str) -> bool:
    text = target or ""
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in _CREDENTIAL_MARKERS):
        return True
    # Disallow flag soup / inline identity that belongs in ssh config.
    tokens = text.split()
    if len(tokens) != 1:
        return True
    if tokens[0].startswith("-"):
        return True
    return False


def _refuse_credential_argv(parts: Sequence[str]) -> None:
    for part in parts:
        text = str(part or "")
        lowered = text.lower()
        if any(marker.lower() in lowered for marker in _CREDENTIAL_MARKERS if marker != "BEGIN "):
            # Allow benign words like "BatchMode"; only refuse obvious secret material.
            if "token=" in lowered or "password=" in lowered or "secret=" in lowered:
                raise HostAllowlistError(
                    "Denied. Credentials must not appear in runner argv.",
                    host_id="",
                )
            if "ghp_" in text or "gho_" in text or "sk-" in text:
                raise HostAllowlistError(
                    "Denied. Credentials must not appear in runner argv.",
                    host_id="",
                )
        if "BEGIN " in text and "PRIVATE KEY" in text.upper():
            raise HostAllowlistError(
                "Denied. Credentials must not appear in runner argv.",
                host_id="",
            )
