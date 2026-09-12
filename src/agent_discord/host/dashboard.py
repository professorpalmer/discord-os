"""Read-only companion web dashboard for the Discord OS host (P2.12).

Loopback by default. Glance at version / power / spend / jobs / doctor /
allowlist ids — never mutate On/Off, never dump tokens or SSH targets.
"""

from __future__ import annotations

import html
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlparse

from agent_discord import PRODUCT_NAME, __version__
from agent_discord.config import AppConfig, apply_runtime_secrets, load_config
from agent_discord.host.doctor import run_doctor
from agent_discord.host.runners import load_host_allowlist
from agent_discord.host.service import read_host_meta, running_host_pid
from agent_discord.orchestration.service import (
    is_spend_halted,
    seed_spend_cap_from_env,
    session_spend_usd,
    spend_cap_usd,
    spend_cost_known,
)
from agent_discord.persistence.sqlite import SQLiteStore

DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765
ENV_DASHBOARD_HOST = "DISCORD_OS_DASHBOARD_HOST"
ENV_DASHBOARD_PORT = "DISCORD_OS_DASHBOARD_PORT"

_NON_LOOPBACK_REFUSED = frozenset(
    {
        "0.0.0.0",
        "::",
        "[::]",
        "*",
    }
)

_SECRET_MARKERS = (
    "token",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "BEGIN ",
    "authorization",
)


class DashboardBindError(ValueError):
    """Fail-closed bind policy refused a non-loopback (or empty) host."""


def resolve_bind_host(
    requested: Optional[str] = None,
    *,
    allow_non_loopback: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve bind address. Default 127.0.0.1. Refuse wildcards unless allowed."""

    source = dict(os.environ if env is None else env)
    raw = (requested if requested is not None else source.get(ENV_DASHBOARD_HOST) or "").strip()
    host = raw or DEFAULT_DASHBOARD_HOST
    lowered = host.lower()
    if lowered in _NON_LOOPBACK_REFUSED or host == "":
        if not allow_non_loopback:
            raise DashboardBindError(
                f"dashboard: refuse bind host {host!r}; "
                "pass --allow-non-loopback to override (not recommended)"
            )
    if not allow_non_loopback and not _is_loopback(host):
        raise DashboardBindError(
            f"dashboard: refuse non-loopback bind host {host!r}; "
            "pass --allow-non-loopback to override (not recommended)"
        )
    return host


def resolve_bind_port(
    requested: Optional[int] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    source = dict(os.environ if env is None else env)
    if requested is not None:
        port = int(requested)
    else:
        raw = (source.get(ENV_DASHBOARD_PORT) or "").strip()
        port = int(raw) if raw else DEFAULT_DASHBOARD_PORT
    # Port 0 is allowed so tests (and rare callers) can request an ephemeral bind.
    if port != 0 and not (1 <= port <= 65535):
        raise DashboardBindError(f"dashboard: invalid port {port}")
    return port


def _is_loopback(host: str) -> bool:
    key = (host or "").strip().lower().strip("[]")
    if key in {"127.0.0.1", "localhost", "::1"}:
        return True
    if key.startswith("127."):
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            if ipaddress_is_loopback(addr):
                return True
        except ValueError:
            continue
    return False


def ipaddress_is_loopback(addr: str) -> bool:
    import ipaddress

    return ipaddress.ip_address(addr).is_loopback


def build_status_snapshot(
    *,
    workspace: Optional[Path] = None,
    config: Optional[AppConfig] = None,
    store: Optional[SQLiteStore] = None,
    jobs_limit: int = 8,
    include_doctor: bool = True,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Assemble a read-only host status payload (no secrets / no SSH targets)."""

    cfg = config or apply_runtime_secrets(load_config())
    ws = Path(workspace) if workspace is not None else Path(cfg.workspace)
    owns_store = store is None
    db = store
    if db is None:
        db = SQLiteStore(cfg.database_path if ws == Path(cfg.workspace) else ws / "agent_discord.sqlite3")
        db.initialize()
    try:
        meta = read_host_meta(ws) if ws.exists() else {}
        pid = running_host_pid(ws) if ws.exists() else None
        channel_id = str(meta.get("channel_id") or "")
        armed = db.host_is_armed(channel_id, default=True) if channel_id else None
        seed_spend_cap_from_env(db, env=env)
        spent = session_spend_usd(db)
        cap = spend_cap_usd(db)
        halted = is_spend_halted(db)
        jobs = _safe_jobs(db, channel_id, limit=jobs_limit)
        allowlist = [
            {"id": h.id, "label": h.label, "kind": h.kind}
            for h in load_host_allowlist(env=env)
        ]
        doctor: dict[str, Any]
        if include_doctor:
            code, lines = run_doctor(workspace=ws, config=cfg)
            doctor = {"ok": code == 0, "lines": [_redact_line(line) for line in lines]}
        else:
            doctor = {"ok": True, "lines": []}
        try:
            from agent_discord.host.liveness import last_digest_from_state, resolve_digest_for_panel

            digest = resolve_digest_for_panel(
                workspace=ws, store=db, channel_id=channel_id
            )
            if digest is None:
                digest = last_digest_from_state(ws)
            liveness = digest.to_public_dict() if digest is not None else {
                "ok": True,
                "power": "OFF",
                "pid": "NONE",
                "doctor": "OK",
                "fail_summary": "",
                "signature": "",
            }
        except Exception:
            liveness = {"ok": True, "power": "OFF", "pid": "NONE", "doctor": "OK"}
        payload: dict[str, Any] = {
            "product": PRODUCT_NAME,
            "version": __version__,
            "readonly": True,
            "host": {
                "running": pid is not None,
                "pid": pid,
                "channel_id": channel_id or None,
                "armed": armed,
                "workspace": str(ws),
            },
            "spend": {
                "spend_usd": spent,
                "cap_usd": cap,
                "halted": halted,
                "spend_known": spend_cost_known(db),
            },
            "jobs": jobs,
            "doctor": doctor,
            "liveness": liveness,
            "hosts": allowlist,
        }
        return _strip_secrets(payload)
    finally:
        if owns_store and db is not None:
            db.close()


def _safe_jobs(store: SQLiteStore, channel_id: str, *, limit: int) -> list[dict[str, Any]]:
    try:
        rows = store.list_recent_jobs(channel_id, limit=limit)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        intake = str(row.get("intake_text") or "")
        if len(intake) > 160:
            intake = intake[:157] + "..."
        summary = str(row.get("summary") or "")
        if len(summary) > 240:
            summary = summary[:237] + "..."
        out.append(
            {
                "job_code": str(row.get("job_code") or ""),
                "run_id": str(row.get("run_id") or ""),
                "status": str(row.get("status") or ""),
                "summary": summary,
                "attention": bool(row.get("attention")),
                "intake_text": intake,
            }
        )
    return out


def _redact_line(line: str) -> str:
    text = str(line or "")
    lowered = text.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered and "source=" not in lowered:
            # Keep doctor "OK discord token source=…" but scrub accidental dumps.
            if "token source=" in lowered:
                continue
            return "[redacted]"
    return text


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_l = str(key).lower()
            if any(m.lower().replace(" ", "_") in key_l for m in ("token", "password", "secret", "api_key", "private_key")):
                continue
            if key_l in {"target", "ssh", "workdir", "argv"}:
                continue
            out[str(key)] = _strip_secrets(item)
        return out
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(m.lower() in lowered for m in ("begin private", "password=", "api_key=", "authorization:")):
            return "[redacted]"
        return value
    return value


def render_status_html(snapshot: Mapping[str, Any]) -> str:
    host = snapshot.get("host") if isinstance(snapshot.get("host"), Mapping) else {}
    spend = snapshot.get("spend") if isinstance(snapshot.get("spend"), Mapping) else {}
    doctor = snapshot.get("doctor") if isinstance(snapshot.get("doctor"), Mapping) else {}
    jobs = snapshot.get("jobs") if isinstance(snapshot.get("jobs"), list) else []
    hosts = snapshot.get("hosts") if isinstance(snapshot.get("hosts"), list) else []

    running = "running" if host.get("running") else "stopped"
    armed = host.get("armed")
    power = "on" if armed else "off" if armed is False else "n/a"
    cap = spend.get("cap_usd")
    cap_s = f"{cap:.4f}" if isinstance(cap, (int, float)) else "none"
    spent = spend.get("spend_usd")
    spent_s = f"{float(spent):.4f}" if isinstance(spent, (int, float)) else "0"
    halted = " halted" if spend.get("halted") else ""

    job_rows = []
    for job in jobs:
        if not isinstance(job, Mapping):
            continue
        job_rows.append(
            "<tr>"
            f"<td>{html.escape(str(job.get('job_code') or ''))}</td>"
            f"<td>{html.escape(str(job.get('status') or ''))}</td>"
            f"<td>{html.escape(str(job.get('summary') or job.get('intake_text') or ''))}</td>"
            "</tr>"
        )
    host_rows = []
    for item in hosts:
        if not isinstance(item, Mapping):
            continue
        host_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('id') or ''))}</td>"
            f"<td>{html.escape(str(item.get('label') or ''))}</td>"
            f"<td>{html.escape(str(item.get('kind') or ''))}</td>"
            "</tr>"
        )
    doctor_lines = doctor.get("lines") if isinstance(doctor.get("lines"), list) else []
    doctor_html = "".join(f"<li>{html.escape(str(line))}</li>" for line in doctor_lines)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{html.escape(PRODUCT_NAME)} companion</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; color: #111; background: #fafafa; }}
h1 {{ font-size: 1.25rem; margin: 0 0 1rem; }}
h2 {{ font-size: 1rem; margin: 1.5rem 0 0.5rem; }}
table {{ border-collapse: collapse; width: 100%; max-width: 52rem; }}
td, th {{ border: 1px solid #ddd; padding: 0.35rem 0.5rem; text-align: left; font-size: 0.9rem; }}
.meta {{ color: #444; font-size: 0.9rem; }}
.note {{ margin-top: 2rem; color: #666; font-size: 0.85rem; }}
code {{ background: #eee; padding: 0.1rem 0.3rem; }}
</style>
</head>
<body>
<h1>{html.escape(PRODUCT_NAME)} companion <span class="meta">v{html.escape(str(snapshot.get('version') or ''))}</span></h1>
<p class="meta">Read-only glance. Mutating controls stay on the Discord HOST panel.</p>
<h2>Host</h2>
<p>state: <strong>{html.escape(running)}</strong>
{" pid=" + html.escape(str(host.get("pid"))) if host.get("pid") else ""}
 · power: <strong>{html.escape(power)}</strong>
 · channel: <code>{html.escape(str(host.get("channel_id") or "n/a"))}</code></p>
<h2>Spend</h2>
<p>{html.escape(spent_s)} / cap {html.escape(cap_s)}{html.escape(halted)}</p>
<h2>Jobs</h2>
<table><thead><tr><th>code</th><th>status</th><th>summary</th></tr></thead>
<tbody>{''.join(job_rows) or '<tr><td colspan="3">(none)</td></tr>'}</tbody></table>
<h2>Multi-host allowlist</h2>
<table><thead><tr><th>id</th><th>label</th><th>kind</th></tr></thead>
<tbody>{''.join(host_rows) or '<tr><td colspan="3">(empty — single-host)</td></tr>'}</tbody></table>
<h2>Doctor</h2>
<ul>{doctor_html or '<li>(skipped)</li>'}</ul>
<p class="note">JSON: <a href="/api/status"><code>/api/status</code></a>. Bind defaults to loopback only.</p>
</body>
</html>
"""


SnapshotFn = Callable[..., dict[str, Any]]


def make_dashboard_handler(
    *,
    snapshot_fn: Optional[SnapshotFn] = None,
    workspace: Optional[Path] = None,
) -> type[BaseHTTPRequestHandler]:
    build = snapshot_fn or (lambda: build_status_snapshot(workspace=workspace))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._handle_read()

        def do_HEAD(self) -> None:  # noqa: N802
            self._handle_read(body=False)

        def do_POST(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_PUT(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_PATCH(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_DELETE(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def log_message(self, format: str, *args: object) -> None:
            return

        def _method_not_allowed(self) -> None:
            self.send_response(405)
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Type", "application/json")
            raw = b'{"error":"read-only","readonly":true}'
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def _handle_read(self, *, body: bool = True) -> None:
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path in {"/api/status", "/status.json"}:
                try:
                    payload = build()
                except Exception as exc:  # noqa: BLE001 — surface as 500 JSON
                    self._write_bytes(
                        500,
                        json.dumps({"error": str(exc), "readonly": True}).encode("utf-8"),
                        "application/json",
                        body=body,
                    )
                    return
                raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
                self._write_bytes(200, raw, "application/json", body=body)
                return
            if path in {"/", "/health", "/index.html"}:
                try:
                    payload = build()
                except Exception as exc:  # noqa: BLE001
                    text = f"dashboard error: {exc}\n"
                    self._write_bytes(500, text.encode("utf-8"), "text/plain; charset=utf-8", body=body)
                    return
                if path == "/health":
                    raw = json.dumps({"ok": True, "readonly": True, "version": payload.get("version")}).encode(
                        "utf-8"
                    )
                    self._write_bytes(200, raw, "application/json", body=body)
                    return
                html_body = render_status_html(payload).encode("utf-8")
                self._write_bytes(200, html_body, "text/html; charset=utf-8", body=body)
                return
            self.send_error(404)

        def _write_bytes(
            self,
            status: int,
            raw: bytes,
            content_type: str,
            *,
            body: bool,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                self.wfile.write(raw)

    return Handler


def serve_dashboard(
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    allow_non_loopback: bool = False,
    workspace: Optional[Path] = None,
    snapshot_fn: Optional[SnapshotFn] = None,
    env: Optional[Mapping[str, str]] = None,
) -> ThreadingHTTPServer:
    """Create a ThreadingHTTPServer bound per fail-closed policy. Caller serves."""

    bind_host = resolve_bind_host(host, allow_non_loopback=allow_non_loopback, env=env)
    bind_port = resolve_bind_port(port, env=env)
    handler = make_dashboard_handler(snapshot_fn=snapshot_fn, workspace=workspace)
    return ThreadingHTTPServer((bind_host, bind_port), handler)
