"""Opt-in Discord Interactions HTTP engine.

Default listen stays message-prefix (poverty path). This module is the same
host verbs behind slash chrome. It does not open a second Gateway.

Discord requires a public HTTPS URL and a 3s ACK. Bind loopback; tunnel if
you opt in. Slash ``/connect`` never accepts a secret option.

P2.9 / Discord-half P2: thin slash aliases ``/bind`` ``/status`` ``/on``
``/off`` ``/stop`` plus read-only ``/job`` mirror text verbs when
``AGENT_DISCORD_INTERACTIONS=http`` and commands are registered. Opt-in
autocomplete enriches ``/bind`` names and ``/job`` ``DOS-*`` codes.
Text + HOST panel remain the default. No slash ``/add``.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlparse

from agent_discord.host.verbs import handle_open_message
from agent_discord.keys.connect import handle_connect_message


INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2
INTERACTION_APPLICATION_COMMAND_AUTOCOMPLETE = 4
RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE = 4
RESPONSE_AUTOCOMPLETE = 8
EPHEMERAL = 64
MAX_AUTOCOMPLETE_CHOICES = 25

CONNECT_COMMAND = {
    "name": "connect",
    "description": "Bind an OpenRouter key on the listen host (no secret in Discord)",
    "type": 1,
}
OPEN_COMMAND = {
    "name": "open",
    "description": "Open Terminal, files, or an allowlisted URL here or on the host",
    "type": 1,
    "options": [
        {
            "name": "surface",
            "description": "Surface to open",
            "type": 3,
            "required": True,
            "choices": [
                {"name": "terminal", "value": "terminal"},
                {"name": "files", "value": "files"},
                {"name": "browser", "value": "browser"},
            ],
        },
        {
            "name": "target",
            "description": "Workspace-relative path, or allowlisted http(s) URL",
            "type": 3,
            "required": False,
        },
        {
            "name": "dest",
            "description": "here = Discord (this phone). host = listen machine GUI",
            "type": 3,
            "required": False,
            "choices": [
                {"name": "here", "value": "remote"},
                {"name": "host", "value": "host"},
            ],
        },
    ],
}
BIND_COMMAND = {
    "name": "bind",
    "description": "Bind this channel to a realm, memory, or host id (same as text bind)",
    "type": 1,
    "options": [
        {
            "name": "name",
            "description": "Realm name, memory, or host <id> (e.g. puppetmaster / memory / host lab)",
            "type": 3,
            "required": False,
            "autocomplete": True,
        },
    ],
}
JOB_COMMAND = {
    "name": "job",
    "description": "Read-only lookup for a DOS-* job code (phone autocomplete)",
    "type": 1,
    "options": [
        {
            "name": "code",
            "description": "Speakable job code (DOS-10001)",
            "type": 3,
            "required": True,
            "autocomplete": True,
        },
    ],
}
STATUS_COMMAND = {
    "name": "status",
    "description": "Read-only host power / spend / jobs digest (same as text /status)",
    "type": 1,
}
ON_COMMAND = {
    "name": "on",
    "description": "Arm this channel (same as text /on)",
    "type": 1,
}
OFF_COMMAND = {
    "name": "off",
    "description": "Disarm this channel (same as text /off)",
    "type": 1,
}
STOP_COMMAND = {
    "name": "stop",
    "description": "Disarm this channel (alias of /off)",
    "type": 1,
}

OPT_IN_COMMANDS = (
    CONNECT_COMMAND,
    OPEN_COMMAND,
    BIND_COMMAND,
    JOB_COMMAND,
    STATUS_COMMAND,
    ON_COMMAND,
    OFF_COMMAND,
    STOP_COMMAND,
)


class InteractionError(ValueError):
    """Bad signature, payload, or missing opt-in config."""


def verify_ed25519(
    *,
    public_key_hex: str,
    timestamp: str,
    signature_hex: str,
    body: bytes,
    verify_fn: Optional[Callable[[bytes, bytes, bytes], bool]] = None,
) -> bool:
    message = timestamp.encode("utf-8") + body
    try:
        signature = bytes.fromhex(signature_hex)
        public_key = bytes.fromhex(public_key_hex)
    except ValueError as exc:
        raise InteractionError("invalid signature encoding") from exc
    if verify_fn is not None:
        return bool(verify_fn(public_key, message, signature))
    try:
        from nacl.exceptions import BadSignatureError
        from nacl.signing import VerifyKey
    except ImportError as exc:
        raise InteractionError(
            "PyNaCl is required for interactions; pip install 'discord-os[interactions]'"
        ) from exc
    try:
        VerifyKey(public_key).verify(message, signature)
    except BadSignatureError:
        return False
    return True


def handle_interaction_payload(
    payload: Mapping[str, Any],
    *,
    workspace: Path,
    roots: Sequence[Path],
    env: Optional[Mapping[str, str]] = None,
    runner: Optional[Callable[..., object]] = None,
    browser_open: Optional[Callable[[str], object]] = None,
) -> dict[str, Any]:
    kind = int(payload.get("type") or 0)
    if kind == INTERACTION_PING:
        return {"type": RESPONSE_PONG}
    if kind == INTERACTION_APPLICATION_COMMAND_AUTOCOMPLETE:
        return _handle_autocomplete(payload, workspace=workspace, env=env)
    if kind != INTERACTION_APPLICATION_COMMAND:
        return _ephemeral("unsupported interaction")
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    name = str(data.get("name") or "").lower()
    if name == "connect":
        result = handle_connect_message("/connect", workspace=workspace, env=env)
        return _ephemeral(result.card or result.error or "connect")
    if name == "open":
        options = _option_map(data.get("options"))
        surface = str(options.get("surface") or "files")
        target = str(options.get("target") or ".")
        dest = str(options.get("dest") or "").strip()
        command = f"/open {dest} {surface} {target}".strip() if dest else f"/open {surface} {target}".strip()
        opened = handle_open_message(
            command,
            roots=roots,
            runner=runner,
            browser_open=browser_open,
        )
        return _ephemeral(opened.card or opened.error or "open")
    if name in {"on", "off", "stop", "status"}:
        return _handle_power_slash(payload, name=name, workspace=workspace)
    if name == "bind":
        options = _option_map(data.get("options"))
        return _handle_bind_slash(
            payload,
            name_opt=str(options.get("name") or "").strip(),
            workspace=workspace,
            env=env,
        )
    if name == "job":
        options = _option_map(data.get("options"))
        return _handle_job_slash(
            payload,
            code=str(options.get("code") or "").strip(),
            workspace=workspace,
        )
    return _ephemeral("unknown command")


def register_opt_in_commands(
    *,
    token: str,
    application_id: str,
    guild_id: str = "",
    opener: Optional[Callable[..., Any]] = None,
) -> list[str]:
    from agent_discord.discord.rest import call_discord_json

    app_id = (application_id or "").strip()
    if not app_id:
        raise InteractionError("DISCORD_APPLICATION_ID is required to register slash commands")
    guild = (guild_id or "").strip()
    if guild:
        path = f"/applications/{app_id}/guilds/{guild}/commands"
    else:
        path = f"/applications/{app_id}/commands"
    names: list[str] = []
    for command in OPT_IN_COMMANDS:
        result = call_discord_json(
            token, "POST", path, payload=command, opener=opener
        )
        names.append(str((result or {}).get("name") or command["name"]))
    return names


def serve_interactions(
    *,
    public_key_hex: str,
    workspace: Path,
    roots: Sequence[Path],
    host: str = "127.0.0.1",
    port: int = 8743,
    env: Optional[Mapping[str, str]] = None,
    verify_fn: Optional[Callable[[bytes, bytes, bytes], bool]] = None,
    runner: Optional[Callable[..., object]] = None,
    browser_open: Optional[Callable[[str], object]] = None,
) -> ThreadingHTTPServer:
    key = public_key_hex

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/health":
                self.send_error(404)
                return
            self._write(200, {"ok": True})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/interactions":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b"{}"
            timestamp = self.headers.get("X-Signature-Timestamp") or ""
            signature = self.headers.get("X-Signature-Ed25519") or ""
            try:
                ok = verify_ed25519(
                    public_key_hex=key,
                    timestamp=timestamp,
                    signature_hex=signature,
                    body=body,
                    verify_fn=verify_fn,
                )
            except InteractionError as exc:
                self._write(401, {"error": str(exc)})
                return
            if not ok:
                self._write(401, {"error": "bad signature"})
                return
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                self._write(400, {"error": "invalid json"})
                return
            if not isinstance(payload, dict):
                self._write(400, {"error": "invalid json"})
                return
            response = handle_interaction_payload(
                payload,
                workspace=workspace,
                roots=roots,
                env=env,
                runner=runner,
                browser_open=browser_open,
            )
            self._write(200, response)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _write(self, status: int, payload: Mapping[str, Any]) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return ThreadingHTTPServer((host, port), Handler)


def _option_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return {}
    out: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        out[name] = str(item.get("value") or "")
    return out


def _ephemeral(content: str) -> dict[str, Any]:
    return {
        "type": RESPONSE_CHANNEL_MESSAGE,
        "data": {"content": content[:2000], "flags": EPHEMERAL},
    }


def _channel_id(payload: Mapping[str, Any]) -> str:
    raw = payload.get("channel_id")
    if raw:
        return str(raw).strip()
    channel = payload.get("channel")
    if isinstance(channel, Mapping) and channel.get("id"):
        return str(channel.get("id")).strip()
    return ""


def _author_id(payload: Mapping[str, Any]) -> str:
    member = payload.get("member")
    if isinstance(member, Mapping):
        user = member.get("user")
        if isinstance(user, Mapping) and user.get("id"):
            return str(user.get("id")).strip()
    user = payload.get("user")
    if isinstance(user, Mapping) and user.get("id"):
        return str(user.get("id")).strip()
    return ""


def _open_store(workspace: Path):
    from agent_discord.persistence.sqlite import SQLiteStore

    db = Path(workspace) / "agent_discord.sqlite3"
    store = SQLiteStore(db)
    store.initialize()
    return store


def _handle_power_slash(
    payload: Mapping[str, Any],
    *,
    name: str,
    workspace: Path,
) -> dict[str, Any]:
    from agent_discord.host.power import parse_power_command

    channel_id = _channel_id(payload)
    if not channel_id:
        return _ephemeral("missing channel_id")

    # /stop is phone autocomplete alias for /off (disarm).
    verb = "off" if name == "stop" else name
    parsed = parse_power_command(f"/{verb}")
    store = None
    try:
        store = _open_store(workspace)
        if parsed.action == "on":
            from agent_discord.orchestration.service import seed_owner_if_empty

            seed_owner_if_empty(store, _author_id(payload) or None)
            writer = getattr(store, "set_host_control", None)
            if callable(writer):
                writer(channel_id, armed=True)
            return _ephemeral("On")
        if parsed.action == "off":
            writer = getattr(store, "set_host_control", None)
            if callable(writer):
                writer(channel_id, armed=False)
            label = "Stopped" if name == "stop" else "Off"
            return _ephemeral(label)
        # status — read-only; never mutates power
        armed = bool(store.host_is_armed(channel_id))
        line = _status_line(workspace=workspace, store=store, armed=armed)
        return _ephemeral(line)
    except Exception as exc:  # noqa: BLE001 — ephemeral fail-closed
        return _ephemeral(f"power failed: {exc}")
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def _status_line(*, workspace: Path, store: object, armed: bool) -> str:
    power = "on" if armed else "off"
    try:
        from agent_discord.host.dashboard import build_status_snapshot
        from agent_discord.host.status_digest import format_status_digest

        snap = build_status_snapshot(workspace=workspace)
        if isinstance(snap, Mapping):
            # Prefer dashboard armed if present; else inject channel armed.
            host = snap.get("host") if isinstance(snap.get("host"), Mapping) else {}
            if "armed" not in host:
                host = dict(host)
                host["armed"] = armed
                snap = dict(snap)
                snap["host"] = host
            return format_status_digest(snap)
    except Exception:
        pass
    return f"Discord OS status · power {power}"


def _handle_bind_slash(
    payload: Mapping[str, Any],
    *,
    name_opt: str,
    workspace: Path,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    from agent_discord.host.memory import bind_memory_channel, is_memory_bind
    from agent_discord.host.realms import (
        bind_channel_realm,
        parse_bind_command,
    )
    from agent_discord.host.repos import load_host_repos
    from agent_discord.host.runners import (
        HostAllowlistError,
        bind_channel_host,
        is_host_bind_command,
        load_host_allowlist,
        parse_host_bind_command,
    )

    channel_id = _channel_id(payload)
    if not channel_id:
        return _ephemeral("missing channel_id")

    raw = (name_opt or "").strip()
    if not raw:
        return _ephemeral("bind needs a name (realm, memory, or host <id>)")

    # Accept "host lab" or bare realm / memory.
    text = f"/bind {raw}".strip()
    workspace_id = "default"
    store = None
    try:
        store = _open_store(workspace)
        if is_host_bind_command(text):
            host_id = parse_host_bind_command(text)
            allowlist = load_host_allowlist(env=env) if env is not None else load_host_allowlist()
            try:
                chosen = bind_channel_host(
                    store,
                    workspace_id=workspace_id,
                    channel_id=channel_id,
                    host_id=host_id,
                    allowlist=allowlist,
                )
            except HostAllowlistError as exc:
                return _ephemeral(str(getattr(exc, "spoken", None) or exc))
            return _ephemeral(f"Bound host {chosen.id}")

        name = parse_bind_command(text)
        if is_memory_bind(name):
            bind_memory_channel(
                store,
                workspace_id=workspace_id,
                channel_id=channel_id,
            )
            return _ephemeral("Bound memory")
        if not name:
            return _ephemeral("bind needs a name (realm, memory, or host <id>)")
        repos = list(load_host_repos(env=env) if env is not None else load_host_repos())
        chosen = bind_channel_realm(
            store,
            workspace_id=workspace_id,
            channel_id=channel_id,
            name=name,
            repos=repos,
        )
        if chosen is not None:
            return _ephemeral(f"Bound {chosen.name}")
        # Still record the requested name via merge if bind_channel_realm returned None
        # (unknown realm) — match text absorb which still publishes with the typed name.
        writer = getattr(store, "merge_binding_metadata", None)
        if callable(writer):
            writer(workspace_id, channel_id, {"repo": name})
        return _ephemeral(f"Bound {name}")
    except Exception as exc:  # noqa: BLE001
        return _ephemeral(f"bind failed: {exc}")
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def _handle_autocomplete(
    payload: Mapping[str, Any],
    *,
    workspace: Path,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Discord type-4 autocomplete for /bind name and /job code."""

    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    name = str(data.get("name") or "").lower()
    focused = _focused_option(data.get("options"))
    needle = str(focused.get("value") or "").strip().lower()
    if name == "bind" and focused.get("name") == "name":
        choices = _bind_autocomplete_choices(needle, workspace=workspace, env=env)
        return {"type": RESPONSE_AUTOCOMPLETE, "data": {"choices": choices}}
    if name == "job" and focused.get("name") == "code":
        channel_id = _channel_id(payload)
        choices = _job_autocomplete_choices(
            needle, workspace=workspace, channel_id=channel_id
        )
        return {"type": RESPONSE_AUTOCOMPLETE, "data": {"choices": choices}}
    return {"type": RESPONSE_AUTOCOMPLETE, "data": {"choices": []}}


def _focused_option(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        if item.get("focused"):
            return {
                "name": str(item.get("name") or ""),
                "value": str(item.get("value") or ""),
            }
    for item in raw:
        if isinstance(item, Mapping) and item.get("name"):
            return {
                "name": str(item.get("name") or ""),
                "value": str(item.get("value") or ""),
            }
    return {}


def _bind_autocomplete_choices(
    needle: str,
    *,
    workspace: Path,
    env: Optional[Mapping[str, str]] = None,
) -> list[dict[str, str]]:
    from agent_discord.host.repos import load_host_repos
    from agent_discord.host.runners import load_host_allowlist

    _ = workspace  # reserved if bindings later seed suggestions
    suggestions: list[str] = ["memory"]
    try:
        repos = load_host_repos(env=env) if env is not None else load_host_repos()
        for repo in repos:
            suggestions.append(repo.name)
            for alias in repo.aliases or ():
                if alias and alias.lower() not in {s.lower() for s in suggestions}:
                    suggestions.append(str(alias))
    except Exception:
        pass
    try:
        allow = load_host_allowlist(env=env) if env is not None else load_host_allowlist()
        for host in allow or ():
            hid = str(getattr(host, "id", "") or "").strip()
            if hid:
                suggestions.append(f"host {hid}")
    except Exception:
        pass
    seen: set[str] = set()
    ordered: list[str] = []
    for item in suggestions:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    if needle:
        ordered = [s for s in ordered if needle in s.lower()]
    return [
        {"name": label[:100], "value": label[:100]}
        for label in ordered[:MAX_AUTOCOMPLETE_CHOICES]
    ]


def _job_autocomplete_choices(
    needle: str,
    *,
    workspace: Path,
    channel_id: str = "",
) -> list[dict[str, str]]:
    store = None
    try:
        store = _open_store(workspace)
        lister = getattr(store, "list_recent_jobs", None)
        if not callable(lister):
            return []
        rows = lister(channel_id or "", limit=25) or []
        out: list[dict[str, str]] = []
        for row in rows:
            code = str(row.get("job_code") or "").strip()
            if not code:
                continue
            status = str(row.get("status") or "").strip()
            label = f"{code} · {status}" if status else code
            if needle and needle not in code.lower() and needle not in label.lower():
                continue
            out.append({"name": label[:100], "value": code[:100]})
            if len(out) >= MAX_AUTOCOMPLETE_CHOICES:
                break
        return out
    except Exception:
        return []
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def _handle_job_slash(
    payload: Mapping[str, Any],
    *,
    code: str,
    workspace: Path,
) -> dict[str, Any]:
    """Read-only DOS-* lookup. Never mutates job state."""

    _ = payload
    raw = (code or "").strip()
    if not raw:
        return _ephemeral("job needs a DOS-* code")
    store = None
    try:
        store = _open_store(workspace)
        getter = getattr(store, "get_task_by_job_code", None)
        if not callable(getter):
            return _ephemeral("job lookup unavailable")
        task = getter(raw) or {}
        if not task:
            return _ephemeral(f"No job for {raw}")
        job_code = str(task.get("job_code") or raw).strip()
        status = str(task.get("status") or "").strip() or "unknown"
        summary = str(task.get("intake_text") or "").strip().replace("\n", " ")
        if len(summary) > 120:
            summary = summary[:119].rstrip() + "…"
        line = f"{job_code} · {status}"
        if summary:
            line += f" · {summary}"
        return _ephemeral(line)
    except Exception as exc:  # noqa: BLE001
        return _ephemeral(f"job failed: {exc}")
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
