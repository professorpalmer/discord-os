"""Panel Gateway reconnect policy: backoff, RESUME, op 7, op 9, close codes.

Fakes only. No live bot token, no real socket.
"""

from __future__ import annotations

import json
from typing import Optional

import pytest

from agent_discord.discord.realtime import (
    BACKOFF_CAP_S,
    FATAL_CLOSE_CODES,
    GatewayClosed,
    GatewaySession,
    close_code_is_fatal,
    gateway_backoff_delay,
    run_discord_gateway,
)
from agent_discord.discord.ws import WebSocketError, decode_frame, encode_frame

HELLO = json.dumps({"op": 10, "d": {"heartbeat_interval": 50}})
READY = json.dumps(
    {
        "op": 0,
        "t": "READY",
        "s": 7,
        "d": {"session_id": "sess-abc", "resume_gateway_url": "wss://resume.test/"},
    }
)
FAKE_URL = "wss://example.test/?v=10&encoding=json"


class _ScriptedSocket:
    """Yields scripted frames, then closes with an optional close code."""

    def __init__(
        self,
        incoming: list[str],
        *,
        close_code: Optional[int] = None,
        close_text: str = "closed",
    ) -> None:
        self.incoming = list(incoming)
        self.sent: list[dict] = []
        self._close_code = close_code
        self._close_text = close_text

    def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def recv_text(self, timeout: float = 1.0) -> str:
        if not self.incoming:
            raise WebSocketError(self._close_text, close_code=self._close_code)
        return self.incoming.pop(0)

    def close(self) -> None:
        return None

    def op(self, code: int) -> Optional[dict]:
        for item in self.sent:
            if item.get("op") == code:
                return item
        return None


def _run(sock, *, session: Optional[GatewaySession] = None, connect=None):
    with pytest.raises(GatewayClosed) as caught:
        run_discord_gateway(
            "tok",
            lambda event, payload: None,
            connect=connect or (lambda url: sock),
            gateway_url=FAKE_URL,
            heartbeat_scale=100.0,
            session=session,
        )
    return caught.value


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """op 9 waits 1-5s in production; keep the suite instant and health clean."""

    from agent_discord.discord.gateway_health import reset_gateway_health_for_tests

    reset_gateway_health_for_tests()
    monkeypatch.setattr(
        "agent_discord.discord.realtime._invalid_session_delay", lambda: 0.0
    )
    yield
    reset_gateway_health_for_tests()


# --- 1. reconnect backoff -------------------------------------------------


def test_backoff_grows_exponentially_and_caps() -> None:
    # Worst-case draw per attempt: base * 2**(n-1), clamped to the cap.
    ceilings = [gateway_backoff_delay(n, rand=lambda: 1.0) for n in range(1, 12)]
    assert ceilings[0] == pytest.approx(1.0)
    assert ceilings[1] == pytest.approx(2.0)
    assert ceilings[2] == pytest.approx(4.0)
    assert ceilings == sorted(ceilings)
    assert ceilings[-1] == pytest.approx(BACKOFF_CAP_S)
    assert max(ceilings) == pytest.approx(BACKOFF_CAP_S)


def test_backoff_is_full_jitter_with_a_floor() -> None:
    assert gateway_backoff_delay(8, rand=lambda: 0.0) >= 0.2
    assert gateway_backoff_delay(8, rand=lambda: 0.25) < gateway_backoff_delay(
        8, rand=lambda: 0.75
    )
    # The old flat 0.4s/1.0s sleep meant ~9k retries an hour while offline.
    # Twenty mean-jitter retries already cost minutes, not seconds.
    assert sum(gateway_backoff_delay(n, rand=lambda: 0.5) for n in range(1, 20)) > 300.0


def test_session_ready_resets_the_backoff_ladder() -> None:
    session = GatewaySession()
    assert not session.consume_ready()
    session.note_ready(session_id="s", resume_url="wss://r.test/")
    assert session.consume_ready()
    assert not session.consume_ready()


# --- 2. RESUME ------------------------------------------------------------


def test_ready_captures_session_id_seq_and_resume_url() -> None:
    session = GatewaySession()
    _run(_ScriptedSocket([HELLO, READY]), session=session)
    assert session.session_id == "sess-abc"
    assert session.seq == 7
    assert session.resume_url == "wss://resume.test/"
    assert session.can_resume()


def test_reconnect_sends_op6_resume_to_resume_url() -> None:
    session = GatewaySession(
        session_id="sess-abc", seq=7, resume_url="wss://resume.test/"
    )
    sock = _ScriptedSocket([HELLO, json.dumps({"op": 0, "t": "RESUMED", "d": {}})])
    seen: list[str] = []

    def connect(url: str):
        seen.append(url)
        return sock

    _run(sock, session=session, connect=connect)
    assert seen == ["wss://resume.test/?v=10&encoding=json"]
    resume = sock.op(6)
    assert resume is not None
    assert resume["d"] == {"token": "tok", "session_id": "sess-abc", "seq": 7}
    assert sock.op(2) is None
    # RESUMED counts as a live session, so backoff resets.
    assert session.consume_ready()


def test_no_session_falls_back_to_identify() -> None:
    sock = _ScriptedSocket([HELLO, READY])
    _run(sock, session=GatewaySession())
    identify = sock.op(2)
    assert identify is not None
    assert identify["d"]["token"] == "tok"
    assert sock.op(6) is None


# --- 3. op 7 Reconnect ----------------------------------------------------


def test_op7_reconnects_and_keeps_the_session() -> None:
    session = GatewaySession()
    exc = _run(
        _ScriptedSocket([HELLO, READY, json.dumps({"op": 7, "d": None})]),
        session=session,
    )
    assert not exc.fatal
    assert "reconnect" in str(exc)
    assert session.can_resume()


# --- 4. op 9 Invalid Session ---------------------------------------------


def test_op9_resumable_is_not_fatal_and_keeps_the_session() -> None:
    session = GatewaySession(
        session_id="sess-abc", seq=7, resume_url="wss://resume.test/"
    )
    exc = _run(
        _ScriptedSocket([HELLO, json.dumps({"op": 9, "d": True})]), session=session
    )
    assert not exc.fatal
    assert session.can_resume()


def test_op9_non_resumable_clears_the_session_but_is_not_fatal() -> None:
    session = GatewaySession(
        session_id="sess-abc", seq=7, resume_url="wss://resume.test/"
    )
    exc = _run(
        _ScriptedSocket([HELLO, json.dumps({"op": 9, "d": False})]), session=session
    )
    assert not exc.fatal
    assert not session.can_resume()
    assert session.session_id == ""


# --- 5. close codes -------------------------------------------------------


def test_close_frame_surfaces_the_code() -> None:
    from agent_discord.discord.ws import _closed_error

    payload = (4004).to_bytes(2, "big") + b"Authentication failed."
    opcode, decoded = decode_frame(bytearray(encode_frame(payload, opcode=8)))
    assert opcode == 8
    assert decoded == payload
    err = _closed_error(payload)
    assert err.close_code == 4004
    assert "4004" in str(err)
    assert "Authentication failed" in str(err)


def test_empty_close_payload_has_no_code() -> None:
    from agent_discord.discord.ws import _closed_error

    assert _closed_error(b"").close_code is None


@pytest.mark.parametrize("code", sorted(FATAL_CLOSE_CODES))
def test_fatal_close_codes_stop_work(code: int) -> None:
    assert close_code_is_fatal(code)
    session = GatewaySession()
    exc = _run(_ScriptedSocket([HELLO, READY], close_code=code), session=session)
    assert exc.fatal
    assert exc.close_code == code
    assert not session.can_resume()


@pytest.mark.parametrize("code", [4000, 4001, 4002, 4003, 4005, 4008, 1006, None])
def test_other_close_codes_reconnect_with_resume(code: Optional[int]) -> None:
    assert not close_code_is_fatal(code)
    session = GatewaySession()
    exc = _run(_ScriptedSocket([HELLO, READY], close_code=code), session=session)
    assert not exc.fatal
    assert exc.close_code == code
    assert session.can_resume()


@pytest.mark.parametrize("code", [4007, 4009])
def test_invalid_seq_close_codes_reidentify(code: int) -> None:
    session = GatewaySession()
    exc = _run(_ScriptedSocket([HELLO, READY], close_code=code), session=session)
    assert not exc.fatal
    # The session is invalid: the next connect must IDENTIFY, not RESUME.
    assert not session.can_resume()
