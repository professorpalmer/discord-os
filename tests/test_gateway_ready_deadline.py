"""D4 zombie before READY: Hello then silence must reconnect, not hang."""

from __future__ import annotations

import json

import pytest

from agent_discord.discord.realtime import GatewayClosed, run_discord_gateway
from agent_discord.discord.ws import WebSocketError

HELLO = json.dumps({"op": 10, "d": {"heartbeat_interval": 50}})
READY = json.dumps({"op": 0, "t": "READY", "s": 1, "d": {"session_id": "s"}})
FAKE_URL = "wss://example.test/?v=10&encoding=json"


@pytest.fixture(autouse=True)
def _clean_health():
    from agent_discord.discord.gateway_health import reset_gateway_health_for_tests

    reset_gateway_health_for_tests()
    yield
    reset_gateway_health_for_tests()


def test_never_ready_after_hello_reconnects() -> None:
    class _SilentSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []
            self._n = 0

        def send_text(self, text: str) -> None:
            self.sent.append(json.loads(text))

        def recv_text(self, timeout: float = 1.0):
            self._n += 1
            if self._n == 1:
                return HELLO
            return None  # Hello, then silence forever.

        def close(self) -> None:
            return None

    sock = _SilentSocket()
    with pytest.raises(GatewayClosed) as caught:
        run_discord_gateway(
            "tok",
            lambda event, payload: None,
            connect=lambda url: sock,
            gateway_url=FAKE_URL,
            heartbeat_scale=100.0,
            ready_deadline_s=0.0,
        )
    assert not caught.value.fatal
    assert "never READY" in str(caught.value)
    # We did identify; Discord simply never dispatched READY.
    assert any(item.get("op") == 2 for item in sock.sent)


def test_deadline_only_starts_after_hello() -> None:
    """Before Hello there is no deadline — a slow handshake is not a zombie."""

    class _PreHelloSilence:
        def __init__(self) -> None:
            self._n = 0

        def send_text(self, text: str) -> None:
            return None

        def recv_text(self, timeout: float = 1.0):
            self._n += 1
            if self._n < 4:
                return None
            raise WebSocketError("closed")

        def close(self) -> None:
            return None

    with pytest.raises(GatewayClosed) as caught:
        run_discord_gateway(
            "tok",
            lambda event, payload: None,
            connect=lambda url: _PreHelloSilence(),
            gateway_url=FAKE_URL,
            heartbeat_scale=100.0,
            ready_deadline_s=0.0,
        )
    assert "never READY" not in str(caught.value)


def test_ready_clears_the_deadline() -> None:
    """A session that reached READY is not torn down by the pre-READY deadline."""

    class _IdleAfterReady:
        def __init__(self) -> None:
            self._n = 0

        def send_text(self, text: str) -> None:
            return None

        def recv_text(self, timeout: float = 1.0):
            self._n += 1
            if self._n == 1:
                return HELLO
            if self._n == 2:
                return READY
            if self._n < 5:
                return None  # Idle past the deadline, but we are READY.
            raise WebSocketError("closed")

        def close(self) -> None:
            return None

    with pytest.raises(GatewayClosed) as caught:
        run_discord_gateway(
            "tok",
            lambda event, payload: None,
            connect=lambda url: _IdleAfterReady(),
            gateway_url=FAKE_URL,
            heartbeat_scale=100.0,
            ready_deadline_s=0.0,
            ack_stale_s=10_000.0,
            ready_grace_s=10_000.0,
        )
    assert "never READY" not in str(caught.value)
