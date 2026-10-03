"""Host status: liveness Need line and the read-only status digest.

Both halves are reachable only through the HOST panel repaint and the desk
``doctor`` verb, so they live in one module with one digest type:

* **Liveness** — a thin ``HostDigest`` (power / pid / doctor / gateway) that
  ranks as a HOST **Need** row. It never posts to Discord (0.5.87); the listen
  tick and ``doctor --notify`` refresh state only.
* **Status digest** — the read-only facts (power / spend / jobs / allowlist
  ids) the panel speaks on **On** and ``/status``, debounced on signature
  change. Read-only: this path never mutates power.

No tokens, SSH targets, or credentials in either surface. Puppetmaster is the
cook backend — unused here; both paths are inline.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from agent_discord.host.doctor import run_doctor
from agent_discord.host.service import read_host_meta, running_host_pid
from agent_discord.redaction import redact_text_markers

# --- liveness ---------------------------------------------------------------

LIVENESS_PREF_SIG_KEY = "host_liveness_sig"
LIVENESS_STATE_NAME = "host_liveness.json"
LIVENESS_MIN_CHECK_INTERVAL_S = 60.0
HOST_NEED_TASK_ID = "host-liveness"

# Digest field vocab — keep short for phone notification previews.
POWER_OK = "OK"
POWER_OFF = "OFF"
PID_OK = "OK"
PID_DEAD = "DEAD"
PID_NONE = "NONE"
DOCTOR_OK = "OK"
DOCTOR_FAIL = "FAIL"

GATEWAY_OK = "OK"
GATEWAY_BAD = "BAD"
GATEWAY_NA = "NA"

# --- status digest ----------------------------------------------------------

DIGEST_PREF_SIG_KEY = "host_status_digest_sig"
DIGEST_STATE_NAME = "host_status_digest.json"
DIGEST_MIN_CHECK_INTERVAL_S = 120.0
ENV_STATUS_THREAD = "DISCORD_OS_STATUS_THREAD_ID"
ENV_DIGEST_INTERVAL = "DISCORD_OS_STATUS_DIGEST_INTERVAL_S"

# Terminal / settled jobs churn Discord posts if included in the announce
# signature. Keep them out of digest_signature; live/attention jobs stay.
TERMINAL_JOB_STATUSES = frozenset(
    {
        "cancelled",
        "canceled",
        "succeeded",
        "completed",
        "done",
        "success",
        "failed",
        "error",
        "expired",
        "dismissed",
        "settled",
    }
)

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


@dataclass(frozen=True)
class HostDigest:
    """Thin host health digest. Never carries tokens or SSH targets."""

    power: str
    pid: str
    doctor: str
    fail_summary: str = ""
    checked_at: float = 0.0
    gateway: str = GATEWAY_NA

    @property
    def ok(self) -> bool:
        if self.doctor != DOCTOR_OK or self.pid == PID_DEAD:
            return False
        if self.gateway == GATEWAY_BAD:
            return False
        return True

    @property
    def signature(self) -> str:
        return (
            f"power={self.power}|pid={self.pid}|doctor={self.doctor}"
            f"|gateway={self.gateway}"
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "power": self.power,
            "pid": self.pid,
            "doctor": self.doctor,
            "gateway": self.gateway,
            "ok": self.ok,
            "fail_summary": self.fail_summary,
            "signature": self.signature,
            "checked_at": self.checked_at,
        }


def _state_path(workspace: Path, name: str) -> Path:
    return Path(workspace) / name


def _read_state(workspace: Path, name: str) -> dict[str, Any]:
    path = _state_path(workspace, name)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(workspace: Path, name: str, payload: Mapping[str, Any]) -> None:
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    _state_path(ws, name).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _remember_signature(store: Any, workspace_id: str, signature: str, key: str) -> None:
    setter = getattr(store, "set_preference", None) if store is not None else None
    if not callable(setter):
        return
    try:
        setter(workspace_id or "default", key, signature, kind="preference")
    except Exception:
        pass


def _recalled_signature(store: Any, workspace_id: str, key: str) -> str:
    getter = getattr(store, "get_preference", None) if store is not None else None
    if not callable(getter):
        return ""
    try:
        return str(getter(workspace_id or "default", key) or "")
    except Exception:
        return ""


def _read_power(store: Any, channel_id: str) -> str:
    """POWER_OK when the channel is armed. Unknown / unreadable → POWER_OFF."""

    if store is None or not channel_id:
        return POWER_OFF
    reader = getattr(store, "host_is_armed", None)
    if not callable(reader):
        return POWER_OFF
    try:
        return POWER_OK if reader(channel_id, default=False) else POWER_OFF
    except TypeError:
        try:
            return POWER_OK if reader(channel_id) else POWER_OFF
        except Exception:
            return POWER_OFF
    except Exception:
        return POWER_OFF


def _read_pid_state(workspace: Optional[Path]) -> str:
    if workspace is None or not workspace.exists():
        return PID_NONE
    if running_host_pid(workspace) is not None:
        return PID_OK
    if read_host_meta(workspace).get("pid") is not None:
        return PID_DEAD
    return PID_DEAD if (workspace / "host.pid").is_file() else PID_NONE


def compute_host_digest(
    *,
    workspace: Optional[Path] = None,
    channel_id: str = "",
    store: Any = None,
    doctor_lines: Optional[Sequence[str]] = None,
    doctor_code: Optional[int] = None,
    now: Optional[float] = None,
    config: Any = None,
) -> HostDigest:
    """Build power/pid/doctor digest. Tokens never included."""

    ws = Path(workspace) if workspace is not None else None
    checked = float(now if now is not None else time.time())

    cid = (channel_id or "").strip()
    if not cid and ws is not None:
        cid = str(read_host_meta(ws).get("channel_id") or "").strip()
    power = _read_power(store, cid)
    pid_state = _read_pid_state(ws)

    lines: list[str]
    code: int
    if doctor_lines is not None and doctor_code is not None:
        lines = [str(line) for line in doctor_lines]
        code = int(doctor_code)
    else:
        code, lines = run_doctor(workspace=ws, config=config)

    # Pid dead from meta is also a doctor-style failure for the HOST Need.
    doctor_state = DOCTOR_OK if code == 0 else DOCTOR_FAIL
    if pid_state == PID_DEAD:
        doctor_state = DOCTOR_FAIL

    fails = [line for line in lines if str(line).startswith("FAIL ")]
    if pid_state == PID_DEAD and not any("host.pid" in line for line in fails):
        fails = ["FAIL host.pid dead"] + fails
    summary = _clip_summary("; ".join(_safe_fail_fragment(line) for line in fails[:3]))

    gateway_state = GATEWAY_NA
    try:
        from agent_discord.discord.gateway_health import (
            gateway_is_expected,
            gateway_need_fragment,
            load_gateway_health,
            persist_gateway_health,
            snapshot_gateway_health,
        )

        live = snapshot_gateway_health(now=checked)
        # Only the process that owns the panel gateway may write the file.
        # The doctor --notify LaunchAgent used to stamp its own never-READY
        # ok=True snapshot over the host's verdict every two minutes.
        if ws is not None and gateway_is_expected():
            try:
                persist_gateway_health(ws, live)
            except Exception:
                pass
        # Prefer live process snapshot; fall back to persisted file (desk --notify).
        health = live
        if health.ok and not health.ready and ws is not None:
            cached = load_gateway_health(ws)
            if cached is not None and not cached.ok:
                health = cached
        if not health.ok:
            gateway_state = GATEWAY_BAD
            frag = gateway_need_fragment(health)
            if frag and frag not in summary:
                summary = _clip_summary("; ".join(part for part in (summary, frag) if part))
                doctor_state = DOCTOR_FAIL
        elif health.ready and health.ok:
            gateway_state = GATEWAY_OK
    except Exception:
        gateway_state = GATEWAY_NA

    return HostDigest(
        power=power,
        pid=pid_state,
        doctor=doctor_state,
        fail_summary=summary,
        checked_at=checked,
        gateway=gateway_state,
    )


def host_need_line(digest: HostDigest) -> Optional[str]:
    """HOST Jobs / card Need line when unhealthy. None when healthy."""

    if digest.ok:
        return None
    bits = [f"power {digest.power}", f"pid {digest.pid}", f"doctor {digest.doctor}"]
    if digest.gateway == GATEWAY_BAD:
        bits.append(f"gateway {digest.gateway}")
    head = "Need: HOST " + " · ".join(bits)
    if digest.fail_summary:
        return f"{head} · {digest.fail_summary}"
    return head


def synthetic_host_need_job(digest: HostDigest) -> Optional[dict[str, Any]]:
    """Fake job row so HOST Jobs ranking shows Need first."""

    line = host_need_line(digest)
    if not line:
        return None
    # Strip "Need: " — briefing_line adds the Need prefix from attention/status.
    summary = line[6:].strip() if line.startswith("Need: ") else line
    return {
        "task_id": HOST_NEED_TASK_ID,
        "run_id": "",
        "job_code": "",
        "status": "failed",
        "attention": "need",
        "summary": summary,
        "intake_text": "host liveness",
        "channel_id": "",
    }


def merge_host_need_jobs(
    jobs: Sequence[Mapping[str, Any]] | None,
    digest: Optional[HostDigest],
) -> list[dict[str, Any]]:
    """Prepend HOST Need row when digest is unhealthy."""

    rows = [dict(job) for job in (jobs or ())]
    rows = [row for row in rows if str(row.get("task_id") or "") != HOST_NEED_TASK_ID]
    if digest is None:
        return rows
    synthetic = synthetic_host_need_job(digest)
    if synthetic is None:
        return rows
    return [synthetic, *rows]


def _save_liveness_state(workspace: Path, digest: HostDigest) -> None:
    _write_state(workspace, LIVENESS_STATE_NAME, digest.to_public_dict())


def last_digest_from_state(workspace: Path) -> Optional[HostDigest]:
    data = _read_state(Path(workspace), LIVENESS_STATE_NAME)
    if not data:
        return None
    try:
        return HostDigest(
            power=str(data.get("power") or POWER_OFF),
            pid=str(data.get("pid") or PID_NONE),
            doctor=str(data.get("doctor") or DOCTOR_OK),
            fail_summary=str(data.get("fail_summary") or ""),
            checked_at=float(data.get("checked_at") or 0.0),
            gateway=str(data.get("gateway") or GATEWAY_NA),
        )
    except (TypeError, ValueError):
        return None


def tick_host_liveness(
    discord: Any,
    *,
    workspace: Path,
    channel_id: str,
    store: Any = None,
    workspace_id: str = "default",
    force: bool = False,
    min_interval_s: float = LIVENESS_MIN_CHECK_INTERVAL_S,
    now: Optional[float] = None,
    config: Any = None,
    doctor_lines: Optional[Sequence[str]] = None,
    doctor_code: Optional[int] = None,
) -> Optional[str]:
    """Compute digest and persist Need state. Never posts to Discord.

    Returns None. Best-effort — never raises on the listen path.
    """

    try:
        return _tick_host_liveness(
            workspace=workspace,
            channel_id=channel_id,
            store=store,
            workspace_id=workspace_id,
            force=force,
            min_interval_s=min_interval_s,
            now=now,
            config=config,
            doctor_lines=doctor_lines,
            doctor_code=doctor_code,
        )
    except Exception:
        return None


def _tick_host_liveness(
    *,
    workspace: Path,
    channel_id: str,
    store: Any,
    workspace_id: str,
    force: bool,
    min_interval_s: float,
    now: Optional[float],
    config: Any,
    doctor_lines: Optional[Sequence[str]],
    doctor_code: Optional[int],
) -> Optional[str]:
    ws = Path(workspace)
    checked_now = float(now if now is not None else time.time())
    last_checked = float(_read_state(ws, LIVENESS_STATE_NAME).get("checked_at") or 0.0)
    if (
        not force
        and doctor_lines is None
        and last_checked > 0
        and (checked_now - last_checked) < float(min_interval_s)
    ):
        return None

    digest = compute_host_digest(
        workspace=ws,
        channel_id=channel_id,
        store=store,
        doctor_lines=doctor_lines,
        doctor_code=doctor_code,
        now=checked_now,
        config=config,
    )
    _save_liveness_state(ws, digest)
    _remember_signature(store, workspace_id, digest.signature, LIVENESS_PREF_SIG_KEY)
    return None


def notify_doctor_failure(
    discord: Any,
    *,
    workspace: Path,
    channel_id: str = "",
    store: Any = None,
    doctor_lines: Sequence[str],
    doctor_code: int,
    workspace_id: str = "default",
    config: Any = None,
) -> Optional[str]:
    """Desk ``doctor --notify``: refresh digest state. Never channel-posts."""

    cid = (channel_id or "").strip()
    if not cid:
        cid = str(read_host_meta(workspace).get("channel_id") or "").strip()
    if doctor_code == 0 and not any(
        str(line).startswith("FAIL ") for line in doctor_lines
    ):
        # Still refresh state so Need clears; do not spam OK.
        digest = compute_host_digest(
            workspace=workspace,
            channel_id=cid,
            store=store,
            doctor_lines=doctor_lines,
            doctor_code=doctor_code,
            config=config,
        )
        _save_liveness_state(workspace, digest)
        _remember_signature(store, workspace_id, digest.signature, LIVENESS_PREF_SIG_KEY)
        return None
    return tick_host_liveness(
        discord,
        workspace=workspace,
        channel_id=cid,
        store=store,
        workspace_id=workspace_id,
        force=True,
        min_interval_s=0,
        config=config,
        doctor_lines=doctor_lines,
        doctor_code=doctor_code,
    )


def resolve_digest_for_panel(
    *,
    workspace: Optional[Path] = None,
    store: Any = None,
    channel_id: str = "",
) -> Optional[HostDigest]:
    """HOST panel Need without re-running full doctor every paint.

    Prefer the last listen/doctor digest. Overlay a cheap pid check so a
    dead ``host.pid`` still ranks as Need before the next debounced tick.
    """

    if workspace is None:
        return None
    ws = Path(workspace)
    cached = last_digest_from_state(ws)
    pid_state = _read_pid_state(ws)

    cid = (channel_id or "").strip()
    if not cid:
        cid = str(read_host_meta(ws).get("channel_id") or "").strip()
    power = _read_power(store, cid)

    if pid_state == PID_DEAD:
        summary = (cached.fail_summary if cached else "") or "host.pid dead"
        return HostDigest(
            power=power,
            pid=PID_DEAD,
            doctor=DOCTOR_FAIL,
            fail_summary=summary,
            checked_at=time.time(),
            gateway=cached.gateway if cached else GATEWAY_NA,
        )
    if cached is None:
        return None
    # Overlay gateway health from live snapshot / persisted file.
    gateway = cached.gateway
    try:
        from agent_discord.discord.gateway_health import (
            load_gateway_health,
            snapshot_gateway_health,
        )

        live = snapshot_gateway_health()
        if not live.ok:
            gateway = GATEWAY_BAD
        elif live.ready:
            gateway = GATEWAY_OK
        elif ws.exists():
            file_h = load_gateway_health(ws)
            if file_h is not None and not file_h.ok:
                gateway = GATEWAY_BAD
    except Exception:
        pass
    doctor = cached.doctor
    summary = cached.fail_summary
    if gateway == GATEWAY_BAD and doctor == DOCTOR_OK:
        doctor = DOCTOR_FAIL
        if "gateway" not in summary:
            summary = (summary + "; gateway WS unhealthy").strip("; ")
    return HostDigest(
        power=power,
        pid=pid_state if pid_state != PID_NONE else cached.pid,
        doctor=doctor,
        fail_summary=summary,
        checked_at=cached.checked_at,
        gateway=gateway,
    )


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


def _resolve_digest_interval_s(
    *,
    env: Optional[Mapping[str, str]] = None,
    override: Optional[float] = None,
) -> float:
    if override is not None:
        return max(0.0, float(override))
    source = dict(os.environ if env is None else env)
    raw = (source.get(ENV_DIGEST_INTERVAL) or "").strip()
    if not raw:
        return DIGEST_MIN_CHECK_INTERVAL_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DIGEST_MIN_CHECK_INTERVAL_S


def _active_job_bits(jobs: Sequence[Any], *, limit: int = 8) -> list[str]:
    """job_code:status for non-terminal jobs only (quiet-unless-real)."""

    bits: list[str] = []
    for job in jobs:
        if not isinstance(job, Mapping):
            continue
        status = str(job.get("status") or "").strip()
        if status.lower() in TERMINAL_JOB_STATUSES:
            continue
        code = str(job.get("job_code") or "").strip() or "?"
        bits.append(f"{code}:{status or '?'}")
        if len(bits) >= limit:
            break
    return bits


def _host_allowlist_bits(hosts: Sequence[Any]) -> list[str]:
    """Allowlist ids (plus reach) only — never targets."""

    bits: list[str] = []
    for item in hosts:
        if not isinstance(item, Mapping):
            continue
        hid = str(item.get("id") or "").strip()
        if not hid:
            continue
        reach = item.get("reachable")
        if reach is True:
            bits.append(f"{hid}:ok")
        elif reach is False:
            bits.append(f"{hid}:down")
        else:
            bits.append(hid)
    return bits


def _spend_fields(spend: Mapping[str, Any]) -> tuple[bool, Optional[float], Optional[float]]:
    known = spend.get("spend_known")
    if known is None:
        # Prefer honesty: zero with no recorded provider cost → unknown.
        known = bool(spend.get("spend_usd"))
    spent: Optional[float] = None
    if known:
        try:
            spent = float(spend.get("spend_usd"))
        except (TypeError, ValueError):
            known = False
            spent = None
    cap_raw = spend.get("cap_usd")
    try:
        cap = float(cap_raw) if cap_raw is not None else None
    except (TypeError, ValueError):
        cap = None
    return bool(known), spent, cap


def digest_signature(snapshot: Mapping[str, Any]) -> str:
    """Stable signature over phone-visible RO fields only."""

    host = snapshot.get("host") if isinstance(snapshot.get("host"), Mapping) else {}
    spend = snapshot.get("spend") if isinstance(snapshot.get("spend"), Mapping) else {}
    jobs = snapshot.get("jobs") if isinstance(snapshot.get("jobs"), list) else []
    hosts = snapshot.get("hosts") if isinstance(snapshot.get("hosts"), list) else []

    armed = host.get("armed")
    power = "on" if armed else "off" if armed is False else "na"
    running = "1" if host.get("running") else "0"
    known, spent, cap = _spend_fields(spend)
    spend_s = f"{spent:.4f}" if known and spent is not None else "unknown"
    cap_s = f"{cap:.4f}" if cap is not None else "none"
    halted = "1" if spend.get("halted") else "0"
    job_bits = _active_job_bits(jobs, limit=8)
    host_bits = _host_allowlist_bits(hosts)
    return (
        f"p={power}|r={running}|s={spend_s}/{cap_s}/h={halted}"
        f"|j={','.join(job_bits) or 'none'}"
        f"|a={','.join(host_bits) or 'single'}"
    )


def format_status_digest(snapshot: Mapping[str, Any]) -> str:
    """Spoken / phone-preview line. No tokens, no SSH targets."""

    from agent_discord.discord.voice import mobile_push_suffix
    from agent_discord.orchestration.service import format_spend_meter

    host = snapshot.get("host") if isinstance(snapshot.get("host"), Mapping) else {}
    spend = snapshot.get("spend") if isinstance(snapshot.get("spend"), Mapping) else {}
    jobs = snapshot.get("jobs") if isinstance(snapshot.get("jobs"), list) else []
    hosts = snapshot.get("hosts") if isinstance(snapshot.get("hosts"), list) else []
    version = str(snapshot.get("version") or "").strip()

    armed = host.get("armed")
    power = "on" if armed else "off" if armed is False else "n/a"
    running = "running" if host.get("running") else "stopped"
    known, spent, cap = _spend_fields(spend)
    spend_strip = format_spend_meter(
        spent,
        known=known,
        cap_usd=cap,
        halted=bool(spend.get("halted")),
        width=10,
    )

    job_bits = _active_job_bits(jobs, limit=5)
    host_bits = _host_allowlist_bits(hosts)
    bits = [
        "Discord OS status",
        f"power {power}",
        running,
        f"spend {spend_strip}",
        f"jobs {', '.join(job_bits) if job_bits else 'none'}",
        f"hosts {', '.join(host_bits) if host_bits else '(single-host)'}",
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


def _save_digest_state(
    workspace: Path,
    *,
    signature: str,
    snapshot: Optional[Mapping[str, Any]],
    checked_at: float,
) -> None:
    host: dict[str, Any] = {}
    spend: dict[str, Any] = {}
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
                "spend_known": raw_spend.get("spend_known"),
                "cap_usd": raw_spend.get("cap_usd"),
                "halted": raw_spend.get("halted"),
            }
    _write_state(
        workspace,
        DIGEST_STATE_NAME,
        {
            "signature": signature,
            "checked_at": float(checked_at),
            "host": host,
            "spend": spend,
            "readonly": True,
        },
    )


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
    interval = _resolve_digest_interval_s(env=env, override=min_interval_s)
    prior = _read_state(ws, DIGEST_STATE_NAME)
    last_checked = float(prior.get("checked_at") or 0.0)
    if (
        not force
        and snapshot is None
        and last_checked > 0
        and (checked_now - last_checked) < interval
    ):
        return None

    snap: Mapping[str, Any]
    if snapshot is not None:
        snap = snapshot
    else:
        from agent_discord.host.dashboard import build_status_snapshot

        snap = build_status_snapshot(
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
    prev_sig = _recalled_signature(store, workspace_id, DIGEST_PREF_SIG_KEY) or str(
        prior.get("signature") or ""
    )
    announce = should_announce(sig, prev_sig, force=force)

    _save_digest_state(ws, signature=sig, snapshot=snap, checked_at=checked_now)
    _remember_signature(store, workspace_id, sig, DIGEST_PREF_SIG_KEY)

    if not announce:
        return None
    cid = (channel_id or "").strip()
    if not cid:
        return None

    body = format_status_digest(snap)
    dest_thread = resolve_status_thread_id(env=env, explicit=thread_id)
    if not _post_status(discord, cid, body, thread_id=dest_thread or None):
        return None
    return body


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


def _clip_summary(summary: str, *, limit: int = 120) -> str:
    return summary if len(summary) <= limit else summary[: limit - 3] + "..."


def _safe_fail_fragment(line: str) -> str:
    text = _scrub_secrets(str(line or "").strip())
    # Drop leading FAIL tag for the compact summary.
    return text[5:] if text.startswith("FAIL ") else text


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
