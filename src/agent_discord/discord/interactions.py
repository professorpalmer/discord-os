"""Opt-in Discord Interactions HTTP engine.

Default listen stays message-prefix (poverty path). This module is the same
host verbs behind slash chrome. It does not open a second Gateway.

Discord requires a public HTTPS URL and a 3s ACK. Bind loopback; tunnel if
you opt in. Slash ``/connect`` never accepts a secret option.

P2.9 / Discord-half EXTRAS: slash aliases ``/bind`` ``/status`` ``/on``
``/off`` ``/stop`` plus read-only ``/job`` and ``/clear-needs`` when
``AGENT_DISCORD_INTERACTIONS=http`` and commands are registered. Opt-in
autocomplete enriches ``/bind`` names and ``/job`` ``DOS-*`` codes.

When Interactions are exposed (``AGENT_DISCORD_INTERACTIONS=http`` / public),
the listen host **self-heals** slash registration (same as
``discord-os interactions --register``): version-aware — re-registers when the
installed package version or command-set stamp changes. Missing
``DISCORD_APPLICATION_ID`` / bot token / public key fails soft (WARN / doctor
honesty; host does not crash). Manual ``--register`` remains available.
Text + HOST panel remain the default. No slash ``/add``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
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
CLEAR_NEEDS_COMMAND = {
    "name": "clear-needs",
    "description": "Dismiss failed Needs (same as HOST More / jobs clear-needs --failed)",
    "type": 1,
    "options": [
        {
            "name": "failed",
            "description": "Required confirm — must be True (fail-closed)",
            "type": 5,
            "required": True,
        },
        {
            "name": "dry_run",
            "description": "Count matches only (default false)",
            "type": 5,
            "required": False,
        },
    ],
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
    CLEAR_NEEDS_COMMAND,
)

SLASH_REGISTRATION_STATE = "slash_registration.json"
_INTERACTIONS_EXPOSED = frozenset({"http", "https", "public", "on", "1", "true", "yes"})


@dataclass(frozen=True)
class SlashHealResult:
    """Outcome of version-aware slash self-heal. Never raises to the host."""

    attempted: bool = False
    registered: bool = False
    skipped: bool = True
    reason: str = ""
    names: tuple[str, ...] = ()
    package_version: str = ""
    command_stamp: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


def command_set_stamp(commands: Sequence[Mapping[str, Any]] | None = None) -> str:
    """Stable fingerprint of the opt-in slash command set (names + options)."""

    payload = list(commands) if commands is not None else list(OPT_IN_COMMANDS)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def slash_registration_state_path(workspace: Path) -> Path:
    return Path(workspace) / SLASH_REGISTRATION_STATE


def load_slash_registration_state(workspace: Path) -> dict[str, Any]:
    path = slash_registration_state_path(workspace)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_slash_registration_state(
    workspace: Path,
    *,
    package_version: str,
    command_stamp: str,
    names: Sequence[str],
    guild_id: str = "",
) -> None:
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    payload = {
        "package_version": str(package_version or "").strip(),
        "command_stamp": str(command_stamp or "").strip(),
        "registered_names": [str(n) for n in names],
        "guild_id": str(guild_id or "").strip(),
    }
    slash_registration_state_path(ws).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def interactions_exposed(
    interactions: str = "",
    *,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """True when slash Interactions are opted in (http/public path)."""

    raw = str(interactions or "").strip().lower()
    if raw:
        return raw in _INTERACTIONS_EXPOSED
    source = env if env is not None else os.environ
    return str(source.get("AGENT_DISCORD_INTERACTIONS") or "").strip().lower() in (
        _INTERACTIONS_EXPOSED
    )


def maybe_self_heal_slash_registration(
    *,
    workspace: Path,
    token: str = "",
    application_id: str = "",
    public_key: str = "",
    interactions: str = "",
    guild_id: str = "",
    package_version: str = "",
    env: Optional[Mapping[str, str]] = None,
    opener: Optional[Callable[..., Any]] = None,
    register_fn: Optional[Callable[..., list[str]]] = None,
) -> SlashHealResult:
    """Re-register slash commands when version/stamp drifts. Fail soft.

    Equivalent of ``discord-os interactions --register`` for the listen host
    when ``AGENT_DISCORD_INTERACTIONS`` is exposed. Missing application id,
    bot token, or public key does not crash the host — returns warnings for
    doctor / log honesty. Manual ``--register`` still works and updates the
    same stamp file.
    """

    from agent_discord import __version__ as installed_version

    version = str(package_version or installed_version or "").strip()
    stamp = command_set_stamp()
    warnings: list[str] = []

    if not interactions_exposed(interactions, env=env):
        return SlashHealResult(
            attempted=False,
            registered=False,
            skipped=True,
            reason="interactions off",
            package_version=version,
            command_stamp=stamp,
        )

    tok = str(token or "").strip()
    app_id = str(application_id or "").strip()
    pub = str(public_key or "").strip()
    if not tok:
        warnings.append("DISCORD_BOT_TOKEN missing — slash self-heal skipped")
    if not app_id:
        warnings.append("DISCORD_APPLICATION_ID missing — slash self-heal skipped")
    if not pub:
        warnings.append(
            "DISCORD_PUBLIC_KEY missing — slash serve/verify unavailable "
            "(registration still needs token + application id)"
        )
    if not tok or not app_id:
        return SlashHealResult(
            attempted=False,
            registered=False,
            skipped=True,
            reason="missing credentials",
            package_version=version,
            command_stamp=stamp,
            warnings=tuple(warnings),
        )

    prior = load_slash_registration_state(workspace)
    prior_version = str(prior.get("package_version") or "").strip()
    prior_stamp = str(prior.get("command_stamp") or "").strip()
    guild = str(guild_id or "").strip()
    if prior_version == version and prior_stamp == stamp:
        return SlashHealResult(
            attempted=False,
            registered=False,
            skipped=True,
            reason="stamp current",
            names=tuple(str(n) for n in (prior.get("registered_names") or [])),
            package_version=version,
            command_stamp=stamp,
            warnings=tuple(warnings),
        )

    register = register_fn or register_opt_in_commands
    try:
        names = list(
            register(
                token=tok,
                application_id=app_id,
                guild_id=guild,
                opener=opener,
            )
        )
    except Exception as exc:  # noqa: BLE001 — fail soft; host must keep listening
        warnings.append(f"slash self-heal register failed: {exc}")
        return SlashHealResult(
            attempted=True,
            registered=False,
            skipped=False,
            reason=f"register failed: {exc}",
            package_version=version,
            command_stamp=stamp,
            warnings=tuple(warnings),
        )

    try:
        save_slash_registration_state(
            workspace,
            package_version=version,
            command_stamp=stamp,
            names=names,
            guild_id=guild,
        )
    except OSError as exc:
        warnings.append(f"slash stamp save failed: {exc}")

    return SlashHealResult(
        attempted=True,
        registered=True,
        skipped=False,
        reason="registered",
        names=tuple(names),
        package_version=version,
        command_stamp=stamp,
        warnings=tuple(warnings),
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
    if name == "clear-needs":
        return _handle_clear_needs_slash(payload, workspace=workspace)
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
        channel = str(task.get("channel_id") or "").strip()
        thread = str(task.get("thread_id") or "").strip()
        summary = str(task.get("intake_text") or "").strip().replace("\n", " ")
        if len(summary) > 160:
            summary = summary[:159].rstrip() + "…"
        tip = ""
        run_status = ""
        run_summary = ""
        try:
            rows = store._connection().execute(
                """
                SELECT run_id, status, summary FROM runs
                WHERE task_id=?
                ORDER BY created_at DESC, run_id DESC
                LIMIT 1
                """,
                (str(task.get("task_id") or ""),),
            ).fetchone()
            if rows:
                tip = str(rows["run_id"] or "").strip()
                run_status = str(rows["status"] or "").strip()
                run_summary = str(rows["summary"] or "").strip().replace("\n", " ")
                if len(run_summary) > 120:
                    run_summary = run_summary[:119].rstrip() + "…"
        except Exception:
            pass
        lines = [f"{job_code} · task:{status}"]
        if run_status:
            lines.append(f"run:{run_status}" + (f" · {tip}" if tip else ""))
        if summary:
            lines.append(f"intake: {summary}")
        if run_summary:
            lines.append(f"settle: {run_summary}")
        dest_bits = []
        if channel:
            dest_bits.append(f"#{channel}")
        if thread:
            dest_bits.append(f"thread {thread}")
        if dest_bits:
            lines.append(" · ".join(dest_bits))
        return _ephemeral("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        return _ephemeral(f"job failed: {exc}")
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def _handle_clear_needs_slash(
    payload: Mapping[str, Any],
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Bulk dismiss failed Needs. Requires failed=true (fail-closed)."""

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    options = data.get("options") if isinstance(data, dict) else None
    failed = False
    dry_run = False
    if isinstance(options, list):
        for opt in options:
            if not isinstance(opt, dict):
                continue
            oname = str(opt.get("name") or "")
            if oname == "failed":
                failed = bool(opt.get("value"))
            elif oname == "dry_run":
                dry_run = bool(opt.get("value"))
    if not failed:
        return _ephemeral(
            "refused: set failed=True (same fail-closed as jobs clear-needs --failed)"
        )
    channel_id = _channel_id(payload)
    store = None
    try:
        store = _open_store(workspace)
        from agent_discord.host.panel import _store_clear_failed_needs

        if dry_run:
            lister = getattr(store, "list_dismissable_needs", None)
            matched = 0
            if callable(lister):
                matched = len(lister(channel_id=channel_id) or [])
            return _ephemeral(f"clear-needs dry-run matched={matched}")
        result = _store_clear_failed_needs(store, channel_id=channel_id)
        cleared = int(result.get("cleared") or 0)
        matched = int(result.get("matched") or cleared)
        return _ephemeral(f"clear-needs cleared={cleared} matched={matched}")
    except Exception as exc:  # noqa: BLE001
        return _ephemeral(f"clear-needs failed: {exc}")
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
