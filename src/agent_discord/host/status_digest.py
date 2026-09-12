"""Discord RO status digest from dashboard data (P2.7).

Loopback dashboard HTML will not leave the desk; the phone needs the same
read-only facts (power / spend / jobs / allowlist ids) in Discord.

Reuses ``build_status_snapshot`` (no secrets, no SSH targets). Debounced on
signature change — same posture as host liveness. Fail closed: **read-only**;
this path never mutates On/Off / power / Halt.

Puppetmaster is the cook backend — unused here; the digest is inline.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from agent_discord.redaction import redact_text_markers

PREF_SIG_KEY = "host_status_digest_sig"
STATE_NAME = "host_status_digest.json"
MIN_CHECK_INTERVAL_S = 60.0
ENV_STATUS_THREAD = "DISCORD_OS_STATUS_THREAD_ID"
ENV_DIGEST_INTERVAL = "DISCORD_OS_STATUS_DIGEST_INTERVAL_S"

_SECRET_MARKERS = (
    "token=",
    "bot_token",
    "authorization",
    "password=",
    "api_key=",
    "begin private",
    "sk-",
    "@",  # scrub accidental user@host if it slips in
)


def status_digest_state_path(workspace: Path) -> Path:
    return Path(workspace) / STATE_NAME


def resolve_status_thread_id(
    *,
    env: Optional[Mapping[str, str]] = None,
    explicit: str = "",
) -> str:
    """Optional Discord thread for the digest. Empty → host channel root."""

    if (explicit or "").strip():
        return explicit.strip()
    source = dict(os.environ if env is None else env)
    return str(source.get(ENV_STATUS_THREAD) or "").strip()


def resolve_min_interval_s(
    *,
    env: Optional[Mapping[str, str]] = None,
    override: Optional[float] = None,
) -> float:
    if override is not None:
        return max(0.0, float(override))
    source = dict(os.environ if env is None else env)
    raw = (source.get(ENV_DIGEST_INTERVAL) or "").strip()
    if not raw:
        return MIN_CHECK_INTERVAL_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return MIN_CHECK_INTERVAL_S


def build_ro_snapshot(
    *,
    workspace: Optional[Path] = None,
    store: Any = None,
    config: Any = None,
    env: Optional[Mapping[str, str]] = None,
    jobs_limit: int = 8,
    include_doctor: bool = False,
) -> dict[str, Any]:
    """Thin wrapper over dashboard builder. Doctor skipped on hot path."""

    from agent_discord.host.dashboard import build_status_snapshot

    return build_status_snapshot(
        workspace=workspace,
        store=store,
        config=config,
        env=env,
        jobs_limit=jobs_limit,
        include_doctor=include_doctor,
    )


def digest_signature(snapshot: Mapping[str, Any]) -> str:
    """Stable signature over phone-visible RO fields only."""

    host = snapshot.get("host") if isinstance(snapshot.get("host"), Mapping) else {}
    spend = snapshot.get("spend") if isinstance(snapshot.get("spend"), Mapping) else {}
    jobs = snapshot.get("jobs") if isinstance(snapshot.get("jobs"), list) else []
    hosts = snapshot.get("hosts") if isinstance(snapshot.get("hosts"), list) else []

    armed = host.get("armed")
    power = "on" if armed else "off" if armed is False else "na"
    running = "1" if host.get("running") else "0"
    spent = spend.get("spend_usd")
    try:
        spend_s = f"{float(spent):.4f}"
    except (TypeError, ValueError):
        spend_s = "0.0000"
    cap = spend.get("cap_usd")
    try:
        cap_s = f"{float(cap):.4f}" if cap is not None else "none"
    except (TypeError, ValueError):
        cap_s = "none"
    halted = "1" if spend.get("halted") else "0"
    job_bits: list[str] = []
    for job in jobs[:8]:
        if not isinstance(job, Mapping):
            continue
        code = str(job.get("job_code") or "").strip() or "?"
        status = str(job.get("status") or "").strip() or "?"
        job_bits.append(f"{code}:{status}")
    host_ids = [
        str(item.get("id") or "").strip()
        for item in hosts
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    ]
    return (
        f"p={power}|r={running}|s={spend_s}/{cap_s}/h={halted}"
        f"|j={','.join(job_bits) or 'none'}"
        f"|a={','.join(host_ids) or 'single'}"
    )


def format_status_digest(snapshot: Mapping[str, Any]) -> str:
    """Spoken / phone-preview line. No tokens, no SSH targets."""

    from agent_discord.discord.voice import mobile_push_suffix

    host = snapshot.get("host") if isinstance(snapshot.get("host"), Mapping) else {}
    spend = snapshot.get("spend") if isinstance(snapshot.get("spend"), Mapping) else {}
    jobs = snapshot.get("jobs") if isinstance(snapshot.get("jobs"), list) else []
    hosts = snapshot.get("hosts") if isinstance(snapshot.get("hosts"), list) else []
    version = str(snapshot.get("version") or "").strip()

    armed = host.get("armed")
    power = "on" if armed else "off" if armed is False else "n/a"
    running = "running" if host.get("running") else "stopped"
    spent = spend.get("spend_usd")
    try:
        spend_s = f"{float(spent):.4f}"
    except (TypeError, ValueError):
        spend_s = "0.0000"
    cap = spend.get("cap_usd")
    try:
        cap_s = f"{float(cap):.4f}" if cap is not None else "none"
    except (TypeError, ValueError):
        cap_s = "none"
    halted = " halted" if spend.get("halted") else ""

    job_bits: list[str] = []
    for job in jobs[:5]:
        if not isinstance(job, Mapping):
            continue
        code = str(job.get("job_code") or "").strip()
        status = str(job.get("status") or "").strip()
        if code and status:
            job_bits.append(f"{code}:{status}")
        elif code:
            job_bits.append(code)
        elif status:
            job_bits.append(status)
    jobs_s = ", ".join(job_bits) if job_bits else "none"

    host_ids = [
        str(item.get("id") or "").strip()
        for item in hosts
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    ]
    hosts_s = ", ".join(host_ids) if host_ids else "(single-host)"

    bits = [
        "Discord OS status",
        f"power {power}",
        running,
        f"spend {spend_s}/{cap_s}{halted}",
        f"jobs {jobs_s}",
        f"hosts {hosts_s}",
    ]
    if version:
        bits.insert(1, f"v{version}")
    body = " · ".join(bits) + mobile_push_suffix()
    return redact_text_markers(_scrub_secrets(body))


def should_announce(
    signature: str,
    previous_signature: str = "",
    *,
    force: bool = False,
) -> bool:
    """Post on force or signature change. Skip first quiet baseline + repeats."""

    if force:
        return True
    prev = (previous_signature or "").strip()
    sig = (signature or "").strip()
    if not sig:
        return False
    if sig == prev:
        return False
    if not prev:
        # First observation — persist baseline quietly (like liveness OK).
        return False
    return True


def load_digest_state(workspace: Path) -> dict[str, Any]:
    path = status_digest_state_path(workspace)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_digest_state(
    workspace: Path,
    *,
    signature: str,
    snapshot: Optional[Mapping[str, Any]] = None,
    posted: bool = False,
    checked_at: Optional[float] = None,
) -> None:
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    host = {}
    spend = {}
    if isinstance(snapshot, Mapping):
        raw_host = snapshot.get("host")
        raw_spend = snapshot.get("spend")
        if isinstance(raw_host, Mapping):
            host = {
                "armed": raw_host.get("armed"),
                "running": raw_host.get("running"),
                "pid": raw_host.get("pid"),
            }
        if isinstance(raw_spend, Mapping):
            spend = {
                "spend_usd": raw_spend.get("spend_usd"),
                "cap_usd": raw_spend.get("cap_usd"),
                "halted": raw_spend.get("halted"),
            }
    payload = {
        "signature": signature,
        "posted": bool(posted),
        "checked_at": float(checked_at if checked_at is not None else time.time()),
        "host": host,
        "spend": spend,
        "readonly": True,
    }
    status_digest_state_path(ws).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def remember_signature(store: Any, workspace_id: str, signature: str) -> None:
    setter = getattr(store, "set_preference", None) if store is not None else None
    if not callable(setter):
        return
    try:
        setter(workspace_id or "default", PREF_SIG_KEY, signature, kind="preference")
    except Exception:
        pass


def recalled_signature(store: Any, workspace_id: str) -> str:
    getter = getattr(store, "get_preference", None) if store is not None else None
    if not callable(getter):
        return ""
    try:
        return str(getter(workspace_id or "default", PREF_SIG_KEY) or "")
    except Exception:
        return ""


def tick_status_digest(
    discord: Any,
    *,
    workspace: Path,
    channel_id: str,
    store: Any = None,
    workspace_id: str = "default",
    force: bool = False,
    min_interval_s: Optional[float] = None,
    now: Optional[float] = None,
    config: Any = None,
    env: Optional[Mapping[str, str]] = None,
    thread_id: str = "",
    snapshot: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Compute RO snapshot; post spoken digest on change / force.

    Returns posted body, else None. Best-effort — never raises; never mutates power.
    """

    try:
        return _tick_status_digest(
            discord,
            workspace=workspace,
            channel_id=channel_id,
            store=store,
            workspace_id=workspace_id,
            force=force,
            min_interval_s=min_interval_s,
            now=now,
            config=config,
            env=env,
            thread_id=thread_id,
            snapshot=snapshot,
        )
    except Exception:
        return None


def _tick_status_digest(
    discord: Any,
    *,
    workspace: Path,
    channel_id: str,
    store: Any,
    workspace_id: str,
    force: bool,
    min_interval_s: Optional[float],
    now: Optional[float],
    config: Any,
    env: Optional[Mapping[str, str]],
    thread_id: str,
    snapshot: Optional[Mapping[str, Any]],
) -> Optional[str]:
    ws = Path(workspace)
    checked_now = float(now if now is not None else time.time())
    interval = resolve_min_interval_s(env=env, override=min_interval_s)
    prior = load_digest_state(ws)
    last_checked = float(prior.get("checked_at") or 0.0)
    if (
        not force
        and snapshot is None
        and last_checked > 0
        and (checked_now - last_checked) < float(interval)
    ):
        return None

    snap: Mapping[str, Any]
    if snapshot is not None:
        snap = snapshot
    else:
        snap = build_ro_snapshot(
            workspace=ws,
            store=store,
            config=config,
            env=env,
            include_doctor=False,
        )

    # Fail closed: refuse to proceed if the payload claims writable.
    if snap.get("readonly") is False:
        return None

    sig = digest_signature(snap)
    prev_sig = recalled_signature(store, workspace_id) or str(prior.get("signature") or "")
    announce = should_announce(sig, prev_sig, force=force)

    save_digest_state(
        ws,
        signature=sig,
        snapshot=snap,
        posted=False,
        checked_at=checked_now,
    )
    remember_signature(store, workspace_id, sig)

    if not announce:
        return None
    cid = (channel_id or "").strip()
    if not cid:
        return None

    body = format_status_digest(snap)
    dest_thread = resolve_status_thread_id(env=env, explicit=thread_id)
    posted = _post_status(discord, cid, body, thread_id=dest_thread or None)
    if posted:
        save_digest_state(
            ws,
            signature=sig,
            snapshot=snap,
            posted=True,
            checked_at=checked_now,
        )
        return body
    return None


def post_status_on_power_on(
    discord: Any,
    *,
    workspace: Path,
    channel_id: str,
    store: Any = None,
    workspace_id: str = "default",
    config: Any = None,
    env: Optional[Mapping[str, str]] = None,
    thread_id: str = "",
) -> Optional[str]:
    """Force RO digest when HOST is armed (On). Never mutates power itself."""

    return tick_status_digest(
        discord,
        workspace=workspace,
        channel_id=channel_id,
        store=store,
        workspace_id=workspace_id,
        force=True,
        min_interval_s=0,
        config=config,
        env=env,
        thread_id=thread_id,
    )


def _post_status(
    discord: Any,
    channel_id: str,
    body: str,
    *,
    thread_id: Optional[str] = None,
) -> bool:
    send = getattr(discord, "send_message", None)
    if not callable(send):
        return False
    tid = (thread_id or "").strip() or None
    try:
        if tid:
            send(channel_id, body, thread_id=tid)
        else:
            send(channel_id, body)
        return True
    except TypeError:
        try:
            send(channel_id, body, thread_id=tid)
            return True
        except Exception:
            return False
    except Exception:
        return False


def _scrub_secrets(text: str) -> str:
    lowered = (text or "").lower()
    # Allow the product suffix and version; scrub credential-shaped fragments.
    for marker in _SECRET_MARKERS:
        if marker == "@":
            # Only scrub email/ssh-looking tokens, not "Discord OS".
            if " @" in f" {lowered}" or lowered.count("@") > 0 and (
                ".local" in lowered or "ssh" in lowered
            ):
                # Drop host-looking segments rather than nuking the whole line.
                parts = []
                for bit in (text or "").split(" · "):
                    if "@" in bit and (".local" in bit.lower() or "ssh" in bit.lower()):
                        parts.append("[redacted]")
                    else:
                        parts.append(bit)
                return " · ".join(parts)
            continue
        if marker in lowered and "token source=" not in lowered:
            return "[redacted]"
    return text


__all__ = [
    "ENV_STATUS_THREAD",
    "MIN_CHECK_INTERVAL_S",
    "PREF_SIG_KEY",
    "build_ro_snapshot",
    "digest_signature",
    "format_status_digest",
    "load_digest_state",
    "post_status_on_power_on",
    "resolve_status_thread_id",
    "save_digest_state",
    "should_announce",
    "tick_status_digest",
]
