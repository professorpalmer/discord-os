"""Host coherence checks: workspace, LaunchAgent, pid, gateway."""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
from pathlib import Path
from typing import Any, Optional, Sequence

from agent_discord import __version__
from agent_discord.config import (
    AppConfig,
    apply_runtime_secrets,
    discord_token_source,
    load_config,
)
from agent_discord.host.install import SERVICE_LABEL, launchd_plist_path
from agent_discord.host.service import read_host_meta, running_host_pid
from agent_discord.persistence.sqlite import SQLiteStore

_PID_IN_OWNER = re.compile(r"(?:^|\D)(\d{2,})(?:\D|$)")


def preferred_live_workspace(home: Optional[Path] = None) -> Optional[Path]:
    root = Path(home) if home is not None else Path.home()
    candidate = root / "discord-os" / ".agent-discord"
    return candidate if candidate.is_dir() else None


def run_doctor(
    *,
    workspace: Optional[Path] = None,
    fix: bool = False,
    plist_path: Optional[Path] = None,
    home: Optional[Path] = None,
    config: Optional[AppConfig] = None,
) -> tuple[int, list[str]]:
    """Return (exit_code, lines). Exit 1 when any FAIL line is present."""

    lines: list[str] = []
    fails = 0
    cfg = config or apply_runtime_secrets(load_config())
    ws = Path(workspace) if workspace is not None else Path(cfg.workspace)
    lines.append(f"OK version {__version__}")

    if not ws.exists():
        lines.append(f"FAIL workspace missing: {ws}")
        fails += 1
    else:
        if os.access(ws, os.W_OK):
            lines.append(f"OK workspace writable: {ws}")
        else:
            lines.append(f"FAIL workspace not writable: {ws}")
            fails += 1

    preferred = preferred_live_workspace(home)
    if preferred is not None and ws.resolve() != preferred.resolve():
        lines.append(
            f"WARN workspace is {ws}; preferred live runtime is {preferred}"
        )

    meta = read_host_meta(ws) if ws.exists() else {}
    pid_file = running_host_pid(ws) if ws.exists() else None
    live_pids = _host_run_pids()
    if pid_file is not None:
        alive = _pid_alive(pid_file)
        if alive:
            lines.append(f"OK host.pid alive pid={pid_file}")
        else:
            lines.append(f"FAIL host.pid stale pid={pid_file}")
            fails += 1
        if live_pids and pid_file not in live_pids:
            lines.append(
                f"WARN host.pid {pid_file} does not match live host run pids {live_pids}"
            )
    elif live_pids:
        lines.append(f"WARN host.pid missing but live host run pids={live_pids}")
    else:
        lines.append("OK no host process (stopped)")

    channel_id = str(meta.get("channel_id") or "")
    if channel_id:
        lines.append(f"OK host channel {channel_id}")

    plist = Path(plist_path) if plist_path is not None else None
    if plist is None and (home is not None or os.uname().sysname == "Darwin"):
        base = Path(home) if home is not None else Path.home()
        plist = base / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    if plist is not None and plist.is_file():
        fails += _check_plist(plist, ws, preferred, lines)
    elif plist is not None:
        lines.append(f"WARN LaunchAgent plist missing: {plist}")

    token_cfg = apply_runtime_secrets(cfg)
    source = discord_token_source(token_cfg)
    if source == "empty":
        lines.append("FAIL discord bot token not resolvable")
        fails += 1
    else:
        lines.append(f"OK discord token source={source}")

    fails += _check_host_allowlist(lines)
    _warn_voice_join(lines)

    db = ws / "agent_discord.sqlite3" if ws.exists() else None
    if db is not None and db.is_file():
        fails += _check_operators(db, lines)
        fails += _check_gateway(db, fix=fix, lines=lines, channel_id=channel_id)
        fails += _check_gateway_ws(ws, lines)
    else:
        lines.append("WARN sqlite database missing; skip gateway/power checks")
        fails += _check_operators(None, lines)
        fails += _check_gateway_ws(ws, lines)

    return (1 if fails else 0, lines)



def _interactions_public() -> bool:
    """True when slash Interactions endpoint is opted in (public HTTPS path)."""

    from agent_discord.orchestration.service import interactions_public

    return interactions_public()


def _check_operators(db: Optional[Path], lines: list[str]) -> int:
    """FAIL when REQUIRE_OPERATORS is on (or interactions public) and empty.

    Single-user Mac (interactions off, require unset): stay workable — OK / WARN
    recommend only. Public interactions escalate WARN→FAIL even when require is
    unset (phone-visible slash surface).
    """

    from agent_discord.orchestration.service import (
        REQUIRE_ALLOWLIST_ENV,
        REQUIRE_OPERATORS_ENV,
        operators_configured,
        require_operators,
    )

    public = _interactions_public()
    required = require_operators()
    flag = REQUIRE_OPERATORS_ENV
    if _truthy_env(REQUIRE_ALLOWLIST_ENV) and not _truthy_env(REQUIRE_OPERATORS_ENV):
        flag = REQUIRE_ALLOWLIST_ENV

    ops_count = 0
    configured = False
    if db is not None and db.is_file():
        store = SQLiteStore(db)
        store.initialize()
        try:
            configured = operators_configured(store)
            if configured:
                ops_count = len(store.list_operators())
        finally:
            store.close()

    if configured:
        if required:
            lines.append(f"OK operators {ops_count} ({flag}=1)")
        elif public:
            lines.append(
                f"OK operators {ops_count} (interactions public; {flag} recommended)"
            )
        else:
            lines.append(
                f"OK operators {ops_count} ({REQUIRE_OPERATORS_ENV} unset; "
                "desk single-user OK)"
            )
        return 0

    # Empty operators
    if required:
        if public and not _truthy_env(REQUIRE_OPERATORS_ENV) and not _truthy_env(
            REQUIRE_ALLOWLIST_ENV
        ):
            # Auto-required because interactions are exposed.
            if db is None or not db.is_file():
                lines.append(
                    "FAIL operators empty while AGENT_DISCORD_INTERACTIONS is "
                    "public (no sqlite)"
                )
            else:
                lines.append(
                    "FAIL operators empty while AGENT_DISCORD_INTERACTIONS is "
                    f"public — pair via Pair / discord-os pair / DISCORD_OWNER_ID "
                    f"before slash dispatch (or set {REQUIRE_OPERATORS_ENV}=1)"
                )
            return 1
        if db is None or not db.is_file():
            lines.append(f"FAIL operators empty while {flag}=1 (no sqlite)")
        else:
            lines.append(
                f"FAIL operators empty while {flag}=1 — pair via Pair / "
                f"discord-os pair / DISCORD_OWNER_ID before dispatch"
            )
        return 1

    if public:
        lines.append(
            "FAIL operators empty while AGENT_DISCORD_INTERACTIONS is public — "
            f"set {REQUIRE_OPERATORS_ENV}=1 and pair before slash dispatch "
            "(desk-only Mac can leave interactions=off)"
        )
        return 1

    lines.append(
        f"WARN operators empty — recommend {REQUIRE_OPERATORS_ENV}=1 when "
        "sharing the bot or enabling public interactions; desk single-user "
        "may seed on first On / Pair"
    )
    return 0


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }



def _check_host_allowlist(lines: list[str]) -> int:
    """Report allowlist status. Refuse unsafe configs (FAIL)."""

    from agent_discord.host.remote_cook import (
        SSH_COOK_UNREACHABLE,
        SSH_REMOTE_CLI_MISSING,
        SSH_REMOTE_OPENROUTER_MISSING,
        SSH_REMOTE_OPENROUTER_VAULT_SEALED,
        probe_ssh_remote_ready,
        ssh_cook_enabled,
    )
    from agent_discord.host.runners import (
        load_host_allowlist,
        validate_host_allowlist,
    )

    hosts = load_host_allowlist()
    if not hosts:
        lines.append("OK host allowlist empty (single-host)")
        return 0
    ids = ",".join(host.id for host in hosts)
    lines.append(f"OK host allowlist {len(hosts)}: {ids}")
    problems = validate_host_allowlist(hosts)
    fails = 0
    for problem in problems:
        lines.append(f"FAIL host allowlist: {problem}")
        fails += 1
    ssh_hosts = [
        host for host in hosts if (host.kind or "").strip().lower() == "ssh"
    ]
    if ssh_hosts:
        if not ssh_cook_enabled():
            ids_csv = ",".join(host.id for host in ssh_hosts)
            lines.append(
                f"WARN host ssh {ids_csv}: remote cook disabled "
                "(DISCORD_OS_SSH_COOK=0) — cook Denies"
            )
        else:
            for host in ssh_hosts:
                result = probe_ssh_remote_ready(host)
                if result.ok:
                    lines.append(
                        f"OK host ssh {host.id}: cook-capable ({result.summary})"
                    )
                    from agent_discord.orchestration.ssh_gate import ssh_gates_cross

                    if ssh_gates_cross():
                        lines.append(
                            f"OK host ssh {host.id}: SSH gate bridge armed "
                            "(DISCORD_OS_SSH_GATES=bridge — phone Allow/Deny "
                            "across Path A)"
                        )
                    else:
                        lines.append(
                            f"WARN host ssh {host.id}: gates do not cross SSH yet "
                            "(write-gate holds local-only; remote writes Deny when "
                            "write-gate on; set DISCORD_OS_SSH_GATES=bridge for "
                            "live phone cards)"
                        )
                else:
                    # Honest Need/WARN before cook-time Deny — never print secrets.
                    reason = result.reason or SSH_COOK_UNREACHABLE
                    detail = (result.detail or "").strip()
                    if reason in {
                        SSH_REMOTE_CLI_MISSING,
                        SSH_REMOTE_OPENROUTER_MISSING,
                        SSH_REMOTE_OPENROUTER_VAULT_SEALED,
                        SSH_COOK_UNREACHABLE,
                    }:
                        suffix = f" ({detail})" if detail else ""
                        lines.append(f"WARN host ssh {host.id}: {reason}{suffix}")
                    else:
                        lines.append(
                            f"WARN host ssh {host.id}: {SSH_COOK_UNREACHABLE} "
                            f"({result.summary})"
                        )
    local_ids = [
        host.id for host in hosts if (host.kind or "").strip().lower() == "local"
    ]
    if local_ids:
        lines.append(
            f"OK host local {','.join(local_ids)}: cook may use path cwd on this Mac"
        )
    return fails


def _check_plist(
    plist: Path,
    workspace: Path,
    preferred: Optional[Path],
    lines: list[str],
) -> int:
    fails = 0
    try:
        data = plistlib.loads(plist.read_bytes())
    except Exception as exc:  # noqa: BLE001
        lines.append(f"FAIL LaunchAgent unreadable: {exc}")
        return 1
    env = dict(data.get("EnvironmentVariables") or {})
    agent_ws = str(env.get("AGENT_DISCORD_WORKSPACE") or "").strip()
    wd = str(data.get("WorkingDirectory") or "").strip()
    args = list(data.get("ProgramArguments") or [])
    if not agent_ws:
        lines.append("FAIL LaunchAgent missing AGENT_DISCORD_WORKSPACE")
        fails += 1
    else:
        agent_path = Path(agent_ws)
        if agent_path.resolve() == workspace.resolve():
            lines.append(f"OK LaunchAgent workspace={agent_ws}")
        else:
            lines.append(
                f"FAIL LaunchAgent AGENT_DISCORD_WORKSPACE={agent_ws} != {workspace}"
            )
            fails += 1
        if preferred is not None and agent_path.resolve() != preferred.resolve():
            lines.append(
                f"WARN LaunchAgent workspace {agent_ws} != preferred {preferred}"
            )
    if wd:
        wd_path = Path(wd).resolve()
        ws_path = workspace.resolve()
        coherent = ws_path == wd_path or ws_path.parent == wd_path or wd_path in ws_path.parents
        if coherent:
            lines.append(f"OK LaunchAgent WorkingDirectory={wd}")
        else:
            lines.append(
                f"WARN LaunchAgent WorkingDirectory={wd} not parent of {workspace}"
            )
    else:
        lines.append("FAIL LaunchAgent missing WorkingDirectory")
        fails += 1
    if args:
        prog = Path(str(args[0]))
        if prog.is_file():
            lines.append(f"OK LaunchAgent python={prog}")
        else:
            lines.append(f"FAIL LaunchAgent python missing: {prog}")
            fails += 1
    else:
        lines.append("FAIL LaunchAgent empty ProgramArguments")
        fails += 1
    return fails


def _check_gateway(
    db: Path,
    *,
    fix: bool,
    lines: list[str],
    channel_id: str,
) -> int:
    fails = 0
    store = SQLiteStore(db)
    store.initialize()
    try:
        conn = store._connection()
        rows = list(conn.execute("SELECT bot_token_fingerprint, owner_id, claimed_at FROM gateway_owners"))
        stale: list[tuple[str, str]] = []
        for row in rows:
            owner = str(row["owner_id"] or "")
            pid = _owner_pid(owner)
            if pid is not None and not _pid_alive(pid):
                stale.append((str(row["bot_token_fingerprint"]), owner))
        if not rows:
            lines.append("OK gateway_owners empty")
        elif not stale:
            lines.append(f"OK gateway_owners live ({len(rows)})")
        else:
            lines.append(f"FAIL gateway_owners stale: {stale}")
            fails += 1
            if fix:
                for fingerprint, owner in stale:
                    conn.execute(
                        "DELETE FROM gateway_owners WHERE bot_token_fingerprint=? AND owner_id=?",
                        (fingerprint, owner),
                    )
                conn.commit()
                lines.append(f"OK cleared {len(stale)} stale gateway owner(s)")
                fails = max(0, fails - 1)
        if channel_id:
            armed = store.host_is_armed(channel_id, default=False)
            lines.append(f"OK power {'on' if armed else 'off'} channel={channel_id}")
    finally:
        store.close()
    return fails




def _check_gateway_ws(workspace: Path, lines: list[str]) -> int:
    """FAIL when persisted Gateway WS ACK health is unhealthy (REST ≠ receiving)."""

    try:
        from agent_discord.discord.gateway_health import (
            load_gateway_health,
            snapshot_gateway_health,
        )
    except Exception:
        lines.append("WARN gateway WS health module unavailable")
        return 0

    live = snapshot_gateway_health()
    health = live
    if health.ok and not health.ready:
        cached = load_gateway_health(workspace) if workspace.exists() else None
        if cached is not None:
            health = cached
    if not health.ready:
        lines.append("OK gateway WS not READY this process (REST intake OK; buttons need panel)")
        return 0
    if health.ok:
        age = health.ack_age_s
        tip = f"ack_age={age:.0f}s" if age is not None else "ack fresh"
        lines.append(f"OK gateway WS READY ({tip})")
        return 0
    reason = health.reason or "heartbeat ACK stale / socket unhealthy"
    lines.append(
        f"FAIL gateway WS unhealthy — {reason} "
        "(REST-up ≠ receiving; On/Off buttons need ACK liveness)"
    )
    return 1

def _owner_pid(owner_id: str) -> Optional[int]:
    # Typical owner: discord-os-cli-28914-de4ae580
    parts = (owner_id or "").split("-")
    for part in reversed(parts):
        if part.isdigit() and len(part) >= 2:
            return int(part)
    match = _PID_IN_OWNER.search(owner_id or "")
    if match:
        return int(match.group(1))
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _host_run_pids() -> list[int]:
    try:
        out = subprocess.check_output(
            ["ps", "-ax", "-o", "pid=,command="],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    found: list[int] = []
    for line in out.splitlines():
        if "agent_discord host run" not in line and "discord-os host run" not in line:
            continue
        if "rg " in line or "grep " in line:
            continue
        try:
            pid = int(line.strip().split(None, 1)[0])
        except ValueError:
            continue
        found.append(pid)
    return found


def _warn_voice_join(lines: list[str]) -> None:
    """WARN when DISCORD_OS_VOICE_JOIN is set — DAVE not shipped; not an unlock."""

    from agent_discord.discord.tts import (
        DAVE_REQUIRED_SINCE,
        ENV_VOICE_JOIN,
        VOICE_CLOSE_DAVE_REQUIRED,
    )

    raw = str(os.environ.get(ENV_VOICE_JOIN) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        lines.append(
            f"WARN {ENV_VOICE_JOIN}={raw} marks join intent — still Deny "
            f"(Discord DAVE E2EE required since {DAVE_REQUIRED_SINCE}, "
            f"close {VOICE_CLOSE_DAVE_REQUIRED}; no libdave / voice UDP; "
            "unset to silence this WARN)"
        )
