"""Phone-visible host liveness / status Need (P0.2).

Desk ``doctor`` and the loopback dashboard do not wake the phone when the
LaunchAgent / pid dies mid-cowork, or when Gateway WS ACK goes stale.
This module keeps a thin digest (power / pid / doctor / gateway) and
surfaces it as:

* a HOST **Need** line on the Jobs ranking / HOST card description
* an on-change spoken status post in the host channel (Discord mobile already
  pushes on channel posts — not a second push vendor)

Debounced on signature change. No tokens in posts. No dashboard write API.
Puppetmaster is the cook backend — unused here; liveness is inline.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from agent_discord.host.doctor import run_doctor
from agent_discord.host.service import read_host_meta, running_host_pid
from agent_discord.redaction import redact_text_markers

PREF_SIG_KEY = "host_liveness_sig"
STATE_NAME = "host_liveness.json"
MIN_CHECK_INTERVAL_S = 60.0
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


def liveness_state_path(workspace: Path) -> Path:
    return Path(workspace) / STATE_NAME


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

    power = POWER_OFF
    cid = (channel_id or "").strip()
    if not cid and ws is not None:
        cid = str(read_host_meta(ws).get("channel_id") or "").strip()
    if store is not None and cid:
        reader = getattr(store, "host_is_armed", None)
        if callable(reader):
            try:
                power = POWER_OK if reader(cid, default=False) else POWER_OFF
            except TypeError:
                try:
                    power = POWER_OK if reader(cid) else POWER_OFF
                except Exception:
                    power = POWER_OFF
            except Exception:
                power = POWER_OFF

    pid_state = PID_NONE
    if ws is not None and ws.exists():
        live = running_host_pid(ws)
        meta = read_host_meta(ws)
        raw_pid = meta.get("pid")
        if live is not None:
            pid_state = PID_OK
        elif raw_pid is not None:
            pid_state = PID_DEAD
        else:
            pid_file = ws / "host.pid"
            if pid_file.is_file():
                pid_state = PID_DEAD
            else:
                pid_state = PID_NONE

    lines: list[str]
    code: int
    if doctor_lines is not None and doctor_code is not None:
        lines = [str(line) for line in doctor_lines]
        code = int(doctor_code)
    else:
        code, lines = run_doctor(workspace=ws, config=config)

    # Pid dead from meta is also a doctor-style failure for phone Need.
    doctor_state = DOCTOR_OK if code == 0 else DOCTOR_FAIL
    if pid_state == PID_DEAD:
        doctor_state = DOCTOR_FAIL

    fails = [line for line in lines if str(line).startswith("FAIL ")]
    if pid_state == PID_DEAD and not any("host.pid" in line for line in fails):
        fails = [f"FAIL host.pid dead"] + fails
    summary = "; ".join(_safe_fail_fragment(line) for line in fails[:3])
    if len(summary) > 120:
        summary = summary[:117] + "..."

    gateway_state = GATEWAY_NA
    try:
        from agent_discord.discord.gateway_health import (
            gateway_need_fragment,
            load_gateway_health,
            persist_gateway_health,
            snapshot_gateway_health,
        )

        live = snapshot_gateway_health(now=checked)
        if ws is not None:
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
        if health.ready and not health.ok:
            gateway_state = GATEWAY_BAD
            frag = gateway_need_fragment(health)
            if frag and frag not in summary:
                fails = ([f"FAIL {frag}"] + fails) if fails is not None else [f"FAIL {frag}"]
                # rebuild summary tip
                extra = frag
                summary = "; ".join(
                    part
                    for part in (
                        summary,
                        extra,
                    )
                    if part
                )
                if len(summary) > 120:
                    summary = summary[:117] + "..."
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
    if getattr(digest, "gateway", GATEWAY_NA) == GATEWAY_BAD:
        bits.append(f"gateway {digest.gateway}")
    head = "Need: HOST " + " · ".join(bits)
    if digest.fail_summary:
        return f"{head} · {digest.fail_summary}"
    return head


def digest_spoken_message(digest: HostDigest) -> str:
    """Thin #agent-status-style digest for the host channel. No tokens."""

    from agent_discord.discord.voice import mobile_push_suffix

    bits = [
        "Discord OS host",
        f"power {digest.power}",
        f"pid {digest.pid}",
        f"doctor {digest.doctor}",
    ]
    if getattr(digest, "gateway", GATEWAY_NA) == GATEWAY_BAD:
        bits.append(f"gateway {digest.gateway}")
    if not digest.ok and digest.fail_summary:
        bits.append(digest.fail_summary)
    body = " · ".join(bits) + mobile_push_suffix()
    return redact_text_markers(_scrub_secrets(body))


def should_announce(
    digest: HostDigest,
    previous_signature: str = "",
    *,
    force: bool = False,
) -> bool:
    """Post only on signature change (or force). Skip repeated OK spam."""

    if force:
        return True
    prev = (previous_signature or "").strip()
    if digest.signature == prev:
        return False
    if digest.ok and not prev:
        # First healthy observation — stay quiet.
        return False
    if (
        digest.ok
        and prev
        and "doctor=FAIL" not in prev
        and "pid=DEAD" not in prev
        and "gateway=BAD" not in prev
    ):
        # Healthy → healthy (field shuffle only) — quiet.
        return False
    return True


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


def load_liveness_state(workspace: Path) -> dict[str, Any]:
    path = liveness_state_path(workspace)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_liveness_state(workspace: Path, digest: HostDigest, *, posted: bool = False) -> None:
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    payload = digest.to_public_dict()
    payload["posted"] = bool(posted)
    liveness_state_path(ws).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def last_digest_from_state(workspace: Path) -> Optional[HostDigest]:
    data = load_liveness_state(workspace)
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


def tick_host_liveness(
    discord: Any,
    *,
    workspace: Path,
    channel_id: str,
    store: Any = None,
    workspace_id: str = "default",
    force: bool = False,
    min_interval_s: float = MIN_CHECK_INTERVAL_S,
    now: Optional[float] = None,
    config: Any = None,
    doctor_lines: Optional[Sequence[str]] = None,
    doctor_code: Optional[int] = None,
) -> Optional[str]:
    """Compute digest; post spoken status on change; persist Need state.

    Returns the posted message body when a channel post happened, else None.
    Best-effort — never raises on the listen path.
    """

    try:
        return _tick_host_liveness(
            discord,
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
    discord: Any,
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
    prior = load_liveness_state(ws)
    last_checked = float(prior.get("checked_at") or 0.0)
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
    prev_sig = recalled_signature(store, workspace_id) or str(prior.get("signature") or "")
    announce = should_announce(digest, prev_sig, force=force and not digest.ok)
    # Always persist latest digest so HOST Need ranking stays current.
    save_liveness_state(ws, digest, posted=False)
    remember_signature(store, workspace_id, digest.signature)

    if not announce:
        return None
    if not (channel_id or "").strip():
        return None

    body = digest_spoken_message(digest)
    posted = _post_status(discord, channel_id, body)
    if posted:
        save_liveness_state(ws, digest, posted=True)
        return body
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
    """Desk ``doctor --notify``: post FAIL digest to the host channel."""

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
        save_liveness_state(workspace, digest, posted=False)
        remember_signature(store, workspace_id, digest.signature)
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

    pid_state = PID_NONE
    if ws.exists():
        live = running_host_pid(ws)
        meta = read_host_meta(ws)
        if live is not None:
            pid_state = PID_OK
        elif meta.get("pid") is not None or (ws / "host.pid").is_file():
            pid_state = PID_DEAD

    power = POWER_OFF
    cid = (channel_id or "").strip()
    if not cid:
        cid = str(read_host_meta(ws).get("channel_id") or "").strip()
    if store is not None and cid:
        reader = getattr(store, "host_is_armed", None)
        if callable(reader):
            try:
                power = POWER_OK if reader(cid, default=False) else POWER_OFF
            except TypeError:
                try:
                    power = POWER_OK if reader(cid) else POWER_OFF
                except Exception:
                    power = POWER_OFF
            except Exception:
                power = POWER_OFF

    if pid_state == PID_DEAD:
        summary = (cached.fail_summary if cached else "") or "host.pid dead"
        return HostDigest(
            power=power,
            pid=PID_DEAD,
            doctor=DOCTOR_FAIL,
            fail_summary=summary,
            checked_at=time.time(),
            gateway=getattr(cached, "gateway", GATEWAY_NA) if cached else GATEWAY_NA,
        )
    if cached is None:
        return None
    # Overlay gateway health from live snapshot / persisted file.
    gateway = getattr(cached, "gateway", GATEWAY_NA)
    try:
        from agent_discord.discord.gateway_health import (
            load_gateway_health,
            snapshot_gateway_health,
        )

        live = snapshot_gateway_health()
        if live.ready and not live.ok:
            gateway = GATEWAY_BAD
        elif live.ready and live.ok:
            gateway = GATEWAY_OK
        elif ws.exists():
            file_h = load_gateway_health(ws)
            if file_h is not None and file_h.ready and not file_h.ok:
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


def _post_status(discord: Any, channel_id: str, body: str) -> bool:
    send = getattr(discord, "send_message", None)
    if not callable(send):
        return False
    try:
        send(channel_id, body)
        return True
    except TypeError:
        try:
            send(channel_id, body, thread_id=None)
            return True
        except Exception:
            return False
    except Exception:
        return False


def _safe_fail_fragment(line: str) -> str:
    text = _scrub_secrets(str(line or "").strip())
    # Drop leading FAIL tag for the compact summary.
    if text.startswith("FAIL "):
        text = text[5:]
    return text


def _scrub_secrets(text: str) -> str:
    lowered = (text or "").lower()
    markers = (
        "token=",
        "bot_token",
        "authorization",
        "password=",
        "api_key=",
        "begin private",
        "sk-",
    )
    if any(marker in lowered for marker in markers) and "token source=" not in lowered:
        return "[redacted]"
    return text
