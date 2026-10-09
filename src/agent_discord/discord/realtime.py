"""Discord Gateway for button clicks. No public URL. Does not poll messages."""

from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.request import Request, urlopen

from agent_discord.discord.errors import ToolInvocationError
from agent_discord.discord.layout import presence_update
from agent_discord.discord.rest import DISCORD_API_BASE, USER_AGENT
from agent_discord.discord.ws import WebSocketClient, WebSocketError


DispatchHandler = Callable[[str, dict[str, Any]], None]
PresenceSender = Callable[[str, str], None]
JsonSocket = Any

INTENTS_GUILDS = 1
# Nothing a reconnect can fix: bad token, bad intents, bad shard/API version.
FATAL_CLOSE_CODES = frozenset({4004, 4010, 4011, 4012, 4013, 4014})
# Reconnectable, but the session is gone — re-IDENTIFY instead of RESUME.
REIDENTIFY_CLOSE_CODES = frozenset({4007, 4009})

# Reconnect pacing. Full jitter so a fleet of hosts does not sync up, and a
# floor so an offline Mac cannot spin on fast-failing DNS.
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 60.0
BACKOFF_FLOOR_S = 0.25
# op 9 Invalid Session: Discord asks for a 1-5s pause before re-auth.
INVALID_SESSION_MIN_S = 1.0
INVALID_SESSION_MAX_S = 5.0
# A socket that completes the handshake but never dispatches READY is a
# zombie the old code waited on forever.
DEFAULT_READY_DEADLINE_S = 30.0


class GatewayClosed(RuntimeError):
    """Gateway session ended. Fatal closes should stop work."""

    def __init__(
        self,
        reason: str,
        *,
        fatal: bool = False,
        close_code: Optional[int] = None,
    ) -> None:
        super().__init__(reason)
        self.fatal = fatal
        self.close_code = close_code


@dataclass
class GatewaySession:
    """RESUME state carried across reconnects by the panel loop.

    One instance lives longer than one socket: ``run_discord_gateway`` fills
    it from READY and reads it back on the next connect.
    """

    session_id: str = ""
    seq: Optional[int] = None
    resume_url: str = ""
    _ready_seen: bool = field(default=False, repr=False)

    def can_resume(self) -> bool:
        return bool(self.session_id and self.seq is not None)

    def note_ready(self, *, session_id: str, resume_url: str) -> None:
        if session_id:
            self.session_id = session_id
        if resume_url:
            self.resume_url = resume_url
        self._ready_seen = True

    def note_resumed(self) -> None:
        self._ready_seen = True

    def consume_ready(self) -> bool:
        """True once per session that reached READY/RESUMED. Resets backoff."""

        seen = self._ready_seen
        self._ready_seen = False
        return seen

    def invalidate(self) -> None:
        self.session_id = ""
        self.seq = None
        self.resume_url = ""


def gateway_backoff_delay(
    attempt: int,
    *,
    base_s: float = BACKOFF_BASE_S,
    cap_s: float = BACKOFF_CAP_S,
    rand: Optional[Callable[[], float]] = None,
) -> float:
    """Exponential backoff with full jitter. ``attempt`` is 1-based."""

    steps = max(0, int(attempt) - 1)
    ceiling = min(float(cap_s), float(base_s) * (2.0**steps))
    draw = (rand or random.random)()
    return max(BACKOFF_FLOOR_S, draw * ceiling)


def close_code_is_fatal(close_code: Optional[int]) -> bool:
    """Only the listed codes stop work. An unknown close reconnects."""

    return close_code in FATAL_CLOSE_CODES


def _invalid_session_delay() -> float:
    return random.uniform(INVALID_SESSION_MIN_S, INVALID_SESSION_MAX_S)


def _with_gateway_query(url: str) -> str:
    text = str(url or "").strip()
    if "encoding=" in text:
        return text
    sep = "&" if "?" in text else "?"
    return f"{text}{sep}v=10&encoding=json"


def fetch_gateway_url(*, opener: Optional[Callable[..., Any]] = None) -> str:
    request = Request(
        f"{DISCORD_API_BASE}/gateway",
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    do_open = opener or urlopen
    try:
        with do_open(request, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise ToolInvocationError("Discord gateway URL lookup failed") from exc
    url = str((raw or {}).get("url") or "").strip()
    if not url.startswith("wss://"):
        raise ToolInvocationError("Discord gateway URL was missing")
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v=10&encoding=json"


def run_discord_gateway(
    token: str,
    on_dispatch: DispatchHandler,
    *,
    stop: Optional[threading.Event] = None,
    connect: Optional[Callable[[str], JsonSocket]] = None,
    gateway_url: Optional[str] = None,
    heartbeat_scale: float = 0.9,
    on_connected: Optional[Callable[[PresenceSender], None]] = None,
    presence_status: str = "idle",
    presence_name: str = "Discord OS",
    ack_stale_s: Optional[float] = None,
    ready_grace_s: Optional[float] = None,
    session: Optional[GatewaySession] = None,
    ready_deadline_s: float = DEFAULT_READY_DEADLINE_S,
) -> None:
    """Identify or resume, heartbeat, and forward DISPATCH events.

    Returns on ``stop``; otherwise raises ``GatewayClosed``. Only a fatal
    close code means stop trying — everything else is the caller's cue to
    reconnect with backoff, resuming when ``session`` still holds a session.

    Message intake stays on REST. This socket exists so On/Off buttons work
    without a public Interactions URL.
    """

    halt = stop or threading.Event()
    state = session if session is not None else GatewaySession()
    resuming = state.can_resume()
    try:
        if resuming and state.resume_url:
            url = _with_gateway_query(state.resume_url)
        else:
            url = gateway_url or fetch_gateway_url()
        opener = connect or WebSocketClient.connect
        sock = opener(url)
    except GatewayClosed:
        raise
    except Exception as exc:
        raise GatewayClosed(str(exc), fatal=False) from exc
    try:
        from agent_discord.discord.gateway_health import note_connected

        note_connected()
    except Exception:
        pass
    seq: Optional[int] = state.seq
    ready = False
    ready_deadline: Optional[float] = None
    beat_stop = threading.Event()
    beater: Optional[threading.Thread] = None
    send_lock = threading.Lock()

    def send(payload: dict[str, Any]) -> None:
        text = json.dumps(payload, separators=(",", ":"))
        # Heartbeat thread and this thread share one socket.
        with send_lock:
            sock.send_text(text)

    try:
        while not halt.is_set():
            raw = sock.recv_text(timeout=1.0)
            if (
                raw is None
                and not ready
                and ready_deadline is not None
                and time.monotonic() >= ready_deadline
            ):
                # Handshake fine, Hello taken, then silence: there is no ACK
                # to go stale, so nothing else would ever reconnect this.
                reason = "gateway never READY after Hello"
                print("panel gateway stalled before READY — reconnecting", flush=True)
                try:
                    from agent_discord.discord.gateway_health import note_closed

                    note_closed(reason)
                except Exception:
                    pass
                raise GatewayClosed(reason, fatal=False)
            if raw is None:
                # Zombie WS: TCP still up but Discord stopped ACKing. Force
                # reconnect so the outer panel loop opens a fresh socket
                # (REST-up ≠ receiving; On/Off buttons need ACK live).
                try:
                    from agent_discord.discord.gateway_health import (
                        DEFAULT_ACK_STALE_S,
                        DEFAULT_READY_GRACE_S,
                        note_closed,
                        snapshot_gateway_health,
                    )

                    health = snapshot_gateway_health(
                        ack_stale_s=(
                            DEFAULT_ACK_STALE_S
                            if ack_stale_s is None
                            else float(ack_stale_s)
                        ),
                        ready_grace_s=(
                            DEFAULT_READY_GRACE_S
                            if ready_grace_s is None
                            else float(ready_grace_s)
                        ),
                    )
                    if (
                        health.ready
                        and health.connected
                        and not health.ok
                        and "ACK stale" in (health.reason or "")
                    ):
                        reason = health.reason or "heartbeat ACK stale"
                        print(f"panel gateway ACK stale — reconnecting: {reason}", flush=True)
                        try:
                            note_closed(reason)
                        except Exception:
                            pass
                        raise GatewayClosed(reason, fatal=False)
                except GatewayClosed:
                    raise
                except Exception:
                    pass
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            op = message.get("op")
            data = message.get("d")
            if message.get("s") is not None:
                try:
                    seq = int(message["s"])
                    state.seq = seq
                except (TypeError, ValueError):
                    pass
            if op == 10:
                interval_ms = 41250
                if isinstance(data, dict):
                    try:
                        interval_ms = int(data.get("heartbeat_interval") or interval_ms)
                    except (TypeError, ValueError):
                        pass
                try:
                    from agent_discord.discord.gateway_health import (
                        note_heartbeat_interval,
                    )

                    note_heartbeat_interval(interval_ms)
                except Exception:
                    pass
                if beater is None:
                    beater = threading.Thread(
                        target=_heartbeat_loop,
                        args=(send, beat_stop, interval_ms, lambda: seq, heartbeat_scale),
                        daemon=True,
                    )
                    beater.start()
                if ready_deadline is None and not ready:
                    ready_deadline = time.monotonic() + max(0.0, float(ready_deadline_s))
                if resuming:
                    send(
                        {
                            "op": 6,
                            "d": {
                                "token": token,
                                "session_id": state.session_id,
                                "seq": state.seq,
                            },
                        }
                    )
                    continue
                send(
                    {
                        "op": 2,
                        "d": {
                            "token": token,
                            "intents": INTENTS_GUILDS,
                            "properties": {
                                "os": "unknown",
                                "browser": "discord-os",
                                "device": "discord-os",
                            },
                            "presence": presence_update(
                                status=presence_status,
                                name=presence_name,
                            )["d"],
                        },
                    }
                )
                continue
            if op == 7:
                # Discord asks us to move. Keep the session so we resume.
                raise GatewayClosed("gateway asked for reconnect", fatal=False)
            if op == 9:
                resumable = data is True
                if not resumable:
                    state.invalidate()
                reason = (
                    "invalid session — resuming"
                    if resumable
                    else "invalid session — re-identifying"
                )
                print(f"panel gateway {reason}", flush=True)
                # Discord requires a 1-5s pause before re-auth.
                halt.wait(_invalid_session_delay())
                raise GatewayClosed(reason, fatal=False)
            if op == 11:
                try:
                    from agent_discord.discord.gateway_health import note_heartbeat_ack

                    note_heartbeat_ack()
                except Exception:
                    pass
                continue
            if op == 0:
                event = str(message.get("t") or "")
                payload = data if isinstance(data, dict) else {}
                if event in {"READY", "RESUMED"}:
                    ready = True
                    ready_deadline = None
                    if event == "READY":
                        state.note_ready(
                            session_id=str(payload.get("session_id") or ""),
                            resume_url=str(payload.get("resume_gateway_url") or ""),
                        )
                        print("panel gateway ready", flush=True)
                    else:
                        state.note_resumed()
                        print("panel gateway resumed", flush=True)
                    try:
                        from agent_discord.discord.gateway_health import note_ready

                        note_ready()
                    except Exception:
                        pass
                    if on_connected is not None:
                        def _set_presence(status: str, name: str) -> None:
                            try:
                                send(presence_update(status=status, name=name))
                            except Exception:
                                pass

                        try:
                            on_connected(_set_presence)
                        except Exception:
                            pass
                try:
                    on_dispatch(event, payload)
                except Exception as exc:
                    print(f"panel dispatch failed: {exc}", flush=True)
    except WebSocketError as exc:
        close_code = getattr(exc, "close_code", None)
        fatal = close_code_is_fatal(close_code)
        if fatal or close_code in REIDENTIFY_CLOSE_CODES:
            state.invalidate()
        try:
            from agent_discord.discord.gateway_health import note_closed

            note_closed(str(exc))
        except Exception:
            pass
        raise GatewayClosed(str(exc), fatal=fatal, close_code=close_code) from exc
    except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError) as exc:
        try:
            from agent_discord.discord.gateway_health import note_closed

            note_closed(str(exc))
        except Exception:
            pass
        raise GatewayClosed(str(exc), fatal=False) from exc
    finally:
        beat_stop.set()
        try:
            from agent_discord.discord.gateway_health import note_closed

            note_closed("gateway loop ended")
        except Exception:
            pass
        closer = getattr(sock, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass


def _heartbeat_loop(
    send: Callable[[dict[str, Any]], None],
    stop: threading.Event,
    interval_ms: int,
    seq_reader: Callable[[], Optional[int]],
    scale: float,
) -> None:
    delay = max(1.0, (interval_ms / 1000.0) * float(scale))
    while not stop.wait(delay):
        try:
            send({"op": 1, "d": seq_reader()})
            try:
                from agent_discord.discord.gateway_health import note_heartbeat_sent

                note_heartbeat_sent()
            except Exception:
                pass
        except Exception:
            return
        time.sleep(0)
