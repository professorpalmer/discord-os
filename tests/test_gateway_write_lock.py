"""One socket, two writers. Frames must not interleave (Discord closes 4002)."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from agent_discord.discord.realtime import GatewayClosed, run_discord_gateway
from agent_discord.discord.ws import WebSocketClient, WebSocketError, decode_frame

HELLO = json.dumps({"op": 10, "d": {"heartbeat_interval": 50}})
READY = json.dumps({"op": 0, "t": "READY", "s": 1, "d": {"session_id": "s"}})
FAKE_URL = "wss://example.test/?v=10&encoding=json"


class _InterleaveDetector:
    """Counts overlapping sendall calls and keeps every byte string sent."""

    def __init__(self) -> None:
        self.inside = 0
        self.overlaps = 0
        self.frames: list[bytes] = []
        self._guard = threading.Lock()

    def sendall(self, data: bytes) -> None:
        with self._guard:
            self.inside += 1
            if self.inside > 1:
                self.overlaps += 1
        time.sleep(0.005)
        with self._guard:
            self.inside -= 1
            self.frames.append(bytes(data))

    def close(self) -> None:
        return None


def test_websocket_sends_are_serialized() -> None:
    detector = _InterleaveDetector()
    client = WebSocketClient(detector)  # type: ignore[arg-type]
    threads = [
        threading.Thread(target=client.send_text, args=(f"payload-{i}",))
        for i in range(6)
    ]
    threads.append(threading.Thread(target=client.send_pong, args=(b"ping",)))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert detector.overlaps == 0
    assert len(detector.frames) == 7
    # Each sendall carried exactly one whole frame.
    for frame in detector.frames:
        buffer = bytearray(frame)
        assert decode_frame(buffer) is not None
        assert not buffer


def test_gateway_send_wrapper_serializes_concurrent_writers() -> None:
    """The gateway's own send wrapper locks too, so fake sockets are safe.

    The real second writer is the heartbeat thread; the presence sender handed
    to ``on_connected`` is the same ``send`` closure, so racing it exercises
    the same lock without waiting a whole heartbeat interval.
    """

    class _SlowSocket:
        def __init__(self) -> None:
            self.inside = 0
            self.overlaps = 0
            self.sent: list[dict] = []
            self._guard = threading.Lock()
            self._n = 0

        def send_text(self, text: str) -> None:
            with self._guard:
                self.inside += 1
                if self.inside > 1:
                    self.overlaps += 1
            time.sleep(0.004)
            with self._guard:
                self.inside -= 1
                self.sent.append(json.loads(text))

        def recv_text(self, timeout: float = 1.0):
            self._n += 1
            if self._n == 1:
                return HELLO
            if self._n == 2:
                return READY
            raise WebSocketError("closed")

        def close(self) -> None:
            return None

    sock = _SlowSocket()

    def on_connected(sender: Any) -> None:
        writers = [
            threading.Thread(target=sender, args=("idle", f"Discord OS {i}"))
            for i in range(6)
        ]
        for thread in writers:
            thread.start()
        for thread in writers:
            thread.join()

    with pytest.raises(GatewayClosed):
        run_discord_gateway(
            "tok",
            lambda event, payload: None,
            connect=lambda url: sock,
            gateway_url=FAKE_URL,
            heartbeat_scale=100.0,
            on_connected=on_connected,
        )
    assert sock.overlaps == 0
    assert sum(1 for item in sock.sent if item.get("op") == 3) == 6
