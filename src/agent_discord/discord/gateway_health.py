"""Gateway WS ACK liveness (Hermes-shaped).

REST-up is not the same as receiving Gateway events. On/Off buttons need
the WS heartbeat ACK path. This module tracks:

* READY seen
* last heartbeat ACK (op 11) age
* socket connected / closed

HOST Need + doctor + optional channel post when unhealthy. Fail closed with
low false-positives: cold start / intentional REST-only stays quiet until
the panel gateway is *expected* (``note_gateway_expected``). Once expected,
never-READY past grace → spoken Need (quiet forever is a real fault).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

STATE_NAME = "gateway_health.json"
# Discord heartbeat intervals are ~41s; allow ~2.5 intervals before FAIL.
DEFAULT_ACK_STALE_S = 120.0
# After READY, require first ACK within this window (low FP).
DEFAULT_READY_GRACE_S = 90.0
# Panel gateway started but never READY → Need after this grace (low FP).
DEFAULT_NEVER_READY_GRACE_S = 90.0

_lock = threading.Lock()
_state: dict[str, Any] = {
    "ready": False,
    "connected": False,
    "last_ack_at": 0.0,
    "last_heartbeat_sent_at": 0.0,
    "heartbeat_interval_ms": 41250,
    "ready_at": 0.0,
    "closed_at": 0.0,
    "close_reason": "",
    "expected": False,
    "expected_at": 0.0,
}


@dataclass(frozen=True)
class GatewayHealth:
    """Public gateway socket health. No tokens."""

    ready: bool
    connected: bool
    ack_age_s: Optional[float]
    ok: bool
    reason: str = ""
    checked_at: float = 0.0

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "connected": self.connected,
            "ack_age_s": self.ack_age_s,
            "ok": self.ok,
            "reason": self.reason,
            "checked_at": self.checked_at,
        }


def gateway_health_path(workspace: Path) -> Path:
    return Path(workspace) / STATE_NAME


def note_connected() -> None:
    with _lock:
        _state["connected"] = True
        _state["closed_at"] = 0.0
        _state["close_reason"] = ""


def note_gateway_expected(*, now: Optional[float] = None) -> None:
    """Mark that this process intends a panel Gateway (not REST-only).

    Cold start without this stays quiet (low FP). After expected, never-READY
    past grace → Need on phone/status.

    Does **not** set connected/ready — only ``note_connected`` / ``note_ready``
    after a real WS session. Expecting a gateway is not fake READY.
    """

    ts = float(now if now is not None else time.time())
    with _lock:
        if not _state["expected"]:
            _state["expected"] = True
            _state["expected_at"] = ts


def note_ready(*, now: Optional[float] = None) -> None:
    ts = float(now if now is not None else time.time())
    with _lock:
        _state["ready"] = True
        _state["connected"] = True
        _state["ready_at"] = ts
        # Treat READY as an initial liveness signal until first ACK arrives.
        if not _state["last_ack_at"]:
            _state["last_ack_at"] = ts


def note_heartbeat_interval(interval_ms: int) -> None:
    try:
        ms = int(interval_ms)
    except (TypeError, ValueError):
        return
    if ms <= 0:
        return
    with _lock:
        _state["heartbeat_interval_ms"] = ms


def note_heartbeat_sent(*, now: Optional[float] = None) -> None:
    with _lock:
        _state["last_heartbeat_sent_at"] = float(
            now if now is not None else time.time()
        )


def note_heartbeat_ack(*, now: Optional[float] = None) -> None:
    with _lock:
        _state["last_ack_at"] = float(now if now is not None else time.time())
        _state["connected"] = True


def note_closed(reason: str = "", *, now: Optional[float] = None) -> None:
    with _lock:
        _state["connected"] = False
        _state["closed_at"] = float(now if now is not None else time.time())
        _state["close_reason"] = (reason or "")[:200]


def reset_gateway_health_for_tests() -> None:
    with _lock:
        _state.update(
            {
                "ready": False,
                "connected": False,
                "last_ack_at": 0.0,
                "last_heartbeat_sent_at": 0.0,
                "heartbeat_interval_ms": 41250,
                "ready_at": 0.0,
                "closed_at": 0.0,
                "close_reason": "",
                "expected": False,
                "expected_at": 0.0,
            }
        )


def snapshot_gateway_health(
    *,
    now: Optional[float] = None,
    ack_stale_s: float = DEFAULT_ACK_STALE_S,
    ready_grace_s: float = DEFAULT_READY_GRACE_S,
    never_ready_grace_s: float = DEFAULT_NEVER_READY_GRACE_S,
) -> GatewayHealth:
    """Compute health from in-process state.

    REST-only / never expected → ok=True (low FP).
    Expected but never READY past grace → Need (quiet forever is a fault).
    After READY: missing ACK past stale window or socket closed → not ok.
    """

    ts = float(now if now is not None else time.time())
    with _lock:
        ready = bool(_state["ready"])
        connected = bool(_state["connected"])
        last_ack = float(_state["last_ack_at"] or 0.0)
        ready_at = float(_state["ready_at"] or 0.0)
        interval_ms = int(_state["heartbeat_interval_ms"] or 41250)
        close_reason = str(_state["close_reason"] or "")
        expected = bool(_state["expected"])
        expected_at = float(_state["expected_at"] or 0.0)

    # Scale stale threshold with heartbeat interval (Hermes-shaped).
    scaled = max(float(ack_stale_s), (interval_ms / 1000.0) * 2.5)
    ack_age: Optional[float] = None
    if last_ack > 0:
        ack_age = max(0.0, ts - last_ack)

    if not ready:
        if expected and expected_at and (ts - expected_at) >= float(never_ready_grace_s):
            return GatewayHealth(
                ready=False,
                connected=connected,
                ack_age_s=ack_age,
                ok=False,
                reason="gateway never READY",
                checked_at=ts,
            )
        return GatewayHealth(
            ready=False,
            connected=connected,
            ack_age_s=ack_age,
            ok=True,
            reason="",
            checked_at=ts,
        )

    if not connected:
        return GatewayHealth(
            ready=True,
            connected=False,
            ack_age_s=ack_age,
            ok=False,
            reason=close_reason or "gateway socket closed",
            checked_at=ts,
        )

    if ready_at and (ts - ready_at) < float(ready_grace_s) and (
        ack_age is None or ack_age < scaled
    ):
        return GatewayHealth(
            ready=True,
            connected=True,
            ack_age_s=ack_age,
            ok=True,
            reason="",
            checked_at=ts,
        )

    if ack_age is None or ack_age > scaled:
        return GatewayHealth(
            ready=True,
            connected=True,
            ack_age_s=ack_age,
            ok=False,
            reason=f"heartbeat ACK stale age={ack_age if ack_age is not None else 'none'}s",
            checked_at=ts,
        )

    return GatewayHealth(
        ready=True,
        connected=True,
        ack_age_s=ack_age,
        ok=True,
        reason="",
        checked_at=ts,
    )


def persist_gateway_health(workspace: Path, health: Optional[GatewayHealth] = None) -> None:
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    snap = health or snapshot_gateway_health()
    payload = snap.to_public_dict()
    with _lock:
        payload["heartbeat_interval_ms"] = int(_state["heartbeat_interval_ms"] or 0)
        payload["last_ack_at"] = float(_state["last_ack_at"] or 0.0)
        payload["ready_at"] = float(_state["ready_at"] or 0.0)
        payload["expected"] = bool(_state["expected"])
        payload["expected_at"] = float(_state["expected_at"] or 0.0)
    gateway_health_path(ws).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def load_gateway_health(workspace: Path) -> Optional[GatewayHealth]:
    path = gateway_health_path(workspace)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return GatewayHealth(
            ready=bool(data.get("ready")),
            connected=bool(data.get("connected")),
            ack_age_s=(
                float(data["ack_age_s"])
                if data.get("ack_age_s") is not None
                else None
            ),
            ok=bool(data.get("ok", True)),
            reason=str(data.get("reason") or ""),
            checked_at=float(data.get("checked_at") or 0.0),
        )
    except (TypeError, ValueError):
        return None


def gateway_need_fragment(health: Optional[GatewayHealth]) -> Optional[str]:
    """Short Need fragment when WS ACK path is unhealthy. None when OK/quiet."""

    if health is None or health.ok:
        return None
    tip = (health.reason or "gateway WS unhealthy").strip()
    if len(tip) > 80:
        tip = tip[:77] + "..."
    return f"gateway {tip}"
