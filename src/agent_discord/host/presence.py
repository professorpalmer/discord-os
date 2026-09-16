"""Mac-side Discord Rich Presence (Band B) via optional pypresence.

Independent of the bot gateway presence payloads. Discord desktop IPC only.
Fail soft if the extra is missing, Discord desktop is not running, or IPC
dies — never crash the host.

Install: ``pip install discord-os[presence]``.
Disable: ``DISCORD_OS_PRESENCE=0``. Default ON when the extra is available.
Client id: ``DISCORD_APPLICATION_ID`` (same application id as invite / slash).
"""

from __future__ import annotations

import os
import time
from typing import Any, Mapping, Optional

ENV_PRESENCE = "DISCORD_OS_PRESENCE"
ENV_APPLICATION_ID = "DISCORD_APPLICATION_ID"
IDLE_DETAILS = "idle"
STATE_ON = "On"
STATE_OFF = "Off"
STATE_HALT = "Halt"
_LIVE_STATUSES = frozenset({"running", "progress"})
_DETAILS_MAX = 128
_STATE_MAX = 128
_RETRY_S = 60.0
_FALSEY = frozenset({"0", "false", "off", "no"})

_SESSION: Optional["RichPresence"] = None


def presence_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Feature flag. Default ON. Set ``DISCORD_OS_PRESENCE=0`` to disable."""

    source = env if env is not None else os.environ
    raw = str(source.get(ENV_PRESENCE) or "1").strip().lower()
    return raw not in _FALSEY


def pypresence_available() -> bool:
    try:
        import pypresence  # noqa: F401

        return True
    except Exception:
        return False


def resolve_application_id(
    env: Optional[Mapping[str, str]] = None,
    *,
    config: Any = None,
) -> str:
    if config is not None:
        cid = str(getattr(config, "discord_application_id", "") or "").strip()
        if cid:
            return cid
    source = env if env is not None else os.environ
    return str(source.get(ENV_APPLICATION_ID) or "").strip()


def host_power_state(*, armed: bool, halted: bool) -> str:
    """HOST mode for Rich Presence ``state``: On / Off / Halt."""

    if halted:
        return STATE_HALT
    return STATE_ON if armed else STATE_OFF


def job_details(title: str = "") -> str:
    """Job label for ``details``, or ``idle`` when nothing is cooking."""

    clip = " ".join((title or "").split())
    if not clip:
        return IDLE_DETAILS
    return clip[:_DETAILS_MAX]


def presence_payload(*, details: str, state: str) -> dict[str, str]:
    label = (state or STATE_OFF).strip() or STATE_OFF
    return {"details": job_details(details), "state": label[:_STATE_MAX]}


def cheap_job_title(store: Any, channel_id: str = "") -> str:
    """First live (running/progress) job code + intake, else empty → idle."""

    lister = getattr(store, "list_recent_jobs", None)
    if not callable(lister):
        return ""
    try:
        rows = lister(str(channel_id or ""), limit=8) or []
    except Exception:
        return ""
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "").strip().lower()
        if status not in _LIVE_STATUSES:
            continue
        code = str(row.get("job_code") or "").strip()
        intake = " ".join(str(row.get("intake_text") or "").split())
        if code and intake:
            return f"{code} · {intake}"
        if code or intake:
            return code or intake
    return ""


def snapshot_presence(
    store: Any,
    *,
    channel_id: str = "",
    workspace_id: str = "",
    armed: Optional[bool] = None,
) -> dict[str, str]:
    halted = False
    try:
        from agent_discord.orchestration.service import is_spend_halted

        halted = bool(is_spend_halted(store, workspace_id))
    except Exception:
        halted = False
    if armed is None:
        reader = getattr(store, "host_is_armed", None)
        try:
            if callable(reader) and channel_id:
                armed = bool(reader(channel_id))
            else:
                armed = False
        except Exception:
            armed = False
    return presence_payload(
        details=cheap_job_title(store, channel_id),
        state=host_power_state(armed=bool(armed), halted=halted),
    )


class RichPresence:
    """Fail-soft pypresence session. Never raises to the host loop."""

    def __init__(
        self,
        *,
        client: Any = None,
        application_id: str = "",
        env: Optional[Mapping[str, str]] = None,
        retry_s: float = _RETRY_S,
    ) -> None:
        self._client = client
        self._application_id = str(application_id or "").strip()
        self._env = env
        self._retry_s = float(retry_s)
        self._last: Optional[tuple[str, str]] = None
        self._connected = False
        self._retry_at = 0.0
        self._quiet = False

    def tick(self, payload: Mapping[str, str]) -> bool:
        if not presence_enabled(self._env):
            return False
        details = job_details(str(payload.get("details") or ""))
        state = str(payload.get("state") or STATE_OFF).strip() or STATE_OFF
        key = (details, state[:_STATE_MAX])
        if self._connected and key == self._last:
            return True
        now = time.monotonic()
        if self._retry_at and now < self._retry_at:
            return False
        if not self._ensure_client():
            return False
        try:
            if not self._connected:
                connect = getattr(self._client, "connect", None)
                if callable(connect):
                    connect()
                self._connected = True
            updater = getattr(self._client, "update", None)
            if callable(updater):
                updater(details=key[0], state=key[1])
            self._last = key
            self._retry_at = 0.0
            return True
        except Exception as exc:
            self._connected = False
            self._last = None
            self._retry_at = now + self._retry_s
            if not self._quiet:
                self._quiet = True
                print(f"presence skipped: {exc}", flush=True)
            return False

    def close(self) -> None:
        client = self._client
        self._client = None
        self._connected = False
        self._last = None
        if client is None:
            return
        try:
            closer = getattr(client, "close", None)
            if callable(closer):
                closer()
        except Exception:
            return

    def _ensure_client(self) -> bool:
        if self._client is not None:
            return True
        app_id = self._application_id or resolve_application_id(self._env)
        if not app_id:
            return False
        if not pypresence_available():
            return False
        try:
            from pypresence import Presence

            self._client = Presence(app_id)
            return True
        except Exception as exc:
            if not self._quiet:
                self._quiet = True
                print(f"presence skipped: {exc}", flush=True)
            return False


def tick_rich_presence(
    store: Any,
    *,
    channel_id: str = "",
    workspace_id: str = "",
    armed: Optional[bool] = None,
    env: Optional[Mapping[str, str]] = None,
    client: Any = None,
    application_id: str = "",
) -> bool:
    """Update Mac Rich Presence from HOST power + a cheap live job label."""

    global _SESSION
    if not presence_enabled(env):
        return False
    if _SESSION is None:
        _SESSION = RichPresence(
            client=client,
            application_id=application_id,
            env=env,
        )
    elif client is not None and _SESSION._client is None:
        _SESSION._client = client
    try:
        payload = snapshot_presence(
            store,
            channel_id=channel_id,
            workspace_id=workspace_id,
            armed=armed,
        )
        return _SESSION.tick(payload)
    except Exception:
        return False


def close_rich_presence() -> None:
    global _SESSION
    session = _SESSION
    _SESSION = None
    if session is None:
        return
    try:
        session.close()
    except Exception:
        return


def reset_rich_presence_for_tests() -> None:
    close_rich_presence()
