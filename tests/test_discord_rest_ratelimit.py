"""Discord REST rate limits, retries, and error bodies (audit D3, B8, D1).

Hermetic: fake opener, fake clock, fake sleeper. No live token, no wall clock.
"""

from __future__ import annotations

import errno
import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from agent_discord.discord import rest
from agent_discord.discord.errors import ToolInvocationError
from agent_discord.discord.rest import (
    RestRateLimiter,
    call_discord_json,
    delete_channel_message,
    list_channel_messages,
    request_definitely_not_sent,
    route_bucket_key,
    send_channel_message,
)


class _FakeResponse:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self._payload = payload
        self.headers = dict(headers or {})

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeClock:
    """Monotonic stand-in whose only motion comes from the injected sleeper."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(float(seconds), 6))
        self.t += float(seconds)


def _http_error(url: str, code: int, body: bytes, headers: dict[str, str]):
    return HTTPError(url, code, "error", headers, BytesIO(body))


def _message_body(message_id: str = "m-ok") -> bytes:
    return json.dumps(
        {"id": message_id, "channel_id": "ch", "content": "hi"}
    ).encode("utf-8")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    fake = _FakeClock()
    monkeypatch.setattr(
        rest, "_LIMITER", RestRateLimiter(sleeper=fake.sleep, clock=fake.now)
    )
    monkeypatch.setattr(rest, "_retry_sleep", lambda _seconds: None)
    return fake


def test_route_bucket_key_keeps_major_param_drops_minor() -> None:
    key = route_bucket_key(
        "patch", "https://discord.com/api/v10/channels/123456789012345678/messages/987654321098765432"
    )
    assert key == "PATCH /api/v10/channels/123456789012345678/messages/{id}"
    # Query strings are not part of bucket identity.
    assert route_bucket_key(
        "GET", "https://discord.com/api/v10/channels/123456789012345678/messages?limit=5"
    ) == "GET /api/v10/channels/123456789012345678/messages"


def test_429_per_route_retry_after_is_honored(clock: _FakeClock) -> None:
    calls: list[str] = []

    def opener(request: Any, timeout: int = 60):
        calls.append(request.method)
        if len(calls) == 1:
            raise _http_error(
                request.full_url,
                429,
                json.dumps({"message": "You are being rate limited.", "retry_after": 1.25, "global": False}).encode("utf-8"),
                {"X-RateLimit-Scope": "user", "Retry-After": "2"},
            )
        return _FakeResponse(_message_body())

    posted = send_channel_message(
        token="tok", channel_id="123456789012345678", content="hi", opener=opener
    )
    assert posted.message_id == "m-ok"
    assert len(calls) == 2
    # Body retry_after wins over the coarse integer header.
    assert clock.slept == [1.25]


def test_429_global_blocks_a_different_route(clock: _FakeClock) -> None:
    calls: list[str] = []

    def opener(request: Any, timeout: int = 60):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise _http_error(
                request.full_url,
                429,
                json.dumps({"retry_after": 3.0, "global": True}).encode("utf-8"),
                {"X-RateLimit-Global": "true"},
            )
        return _FakeResponse(_message_body())

    send_channel_message(
        token="tok", channel_id="123456789012345678", content="hi", opener=opener
    )
    assert clock.slept == [3.0]
    clock.slept.clear()
    clock.t = 1001.0  # still inside the global window (opened at 1000, ends 1003)

    # A completely different route must still wait out the global cooldown.
    delete_channel_message(
        token="tok",
        channel_id="222222222222222222",
        message_id="333333333333333333",
        opener=opener,
    )
    assert clock.slept == [2.0]


def test_exhausted_bucket_waits_before_the_next_send(clock: _FakeClock) -> None:
    calls: list[str] = []

    def opener(request: Any, timeout: int = 60):
        calls.append(request.full_url)
        return _FakeResponse(
            _message_body(),
            headers={
                "x-ratelimit-bucket": "abc123",
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset-after": "0.75",
            },
        )

    send_channel_message(
        token="tok", channel_id="123456789012345678", content="one", opener=opener
    )
    assert clock.slept == []
    send_channel_message(
        token="tok", channel_id="123456789012345678", content="two", opener=opener
    )
    # Pre-emptive wait: the bucket had zero remaining and 0.75s to reset.
    assert clock.slept == [0.75]
    assert len(calls) == 2


def test_500_is_retried_on_get_and_patch(clock: _FakeClock) -> None:
    calls = {"n": 0}

    def get_opener(request: Any, timeout: int = 60):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(request.full_url, 500, b'{"message":"boom"}', {})
        return _FakeResponse(b"[]")

    listed = list_channel_messages(
        token="tok", channel_id="123456789012345678", opener=get_opener
    )
    assert listed == []
    assert calls["n"] == 2

    calls["n"] = 0

    def patch_opener(request: Any, timeout: int = 60):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(request.full_url, 500, b'{"message":"boom"}', {})
        return _FakeResponse(_message_body("m-patched"))

    edited = call_discord_json(
        "tok",
        "PATCH",
        "/channels/123456789012345678/messages/987654321098765432",
        payload={"content": "x"},
        opener=patch_opener,
    )
    assert edited["id"] == "m-patched"
    assert calls["n"] == 2


def test_500_is_not_retried_on_post(clock: _FakeClock) -> None:
    calls = {"n": 0}

    def opener(request: Any, timeout: int = 60):
        calls["n"] += 1
        raise _http_error(request.full_url, 500, b'{"message":"boom","code":0}', {})

    with pytest.raises(ToolInvocationError, match="HTTP 500"):
        send_channel_message(
            token="tok", channel_id="123456789012345678", content="hi", opener=opener
        )
    assert calls["n"] == 1


def test_post_is_not_retried_after_a_timeout(clock: _FakeClock) -> None:
    calls = {"n": 0}

    def opener(request: Any, timeout: int = 60):
        calls["n"] += 1
        raise TimeoutError("timed out")

    with pytest.raises(ToolInvocationError, match="not retried"):
        send_channel_message(
            token="tok", channel_id="123456789012345678", content="hi", opener=opener
        )
    assert calls["n"] == 1


def test_post_is_retried_when_the_connection_was_refused(clock: _FakeClock) -> None:
    calls = {"n": 0}

    def opener(request: Any, timeout: int = 60):
        calls["n"] += 1
        if calls["n"] == 1:
            raise URLError(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
        return _FakeResponse(_message_body())

    posted = send_channel_message(
        token="tok", channel_id="123456789012345678", content="hi", opener=opener
    )
    assert posted.message_id == "m-ok"
    assert calls["n"] == 2


def test_request_definitely_not_sent_classification() -> None:
    assert request_definitely_not_sent(URLError(ConnectionRefusedError(errno.ECONNREFUSED, "x")))
    assert request_definitely_not_sent(OSError(errno.EHOSTUNREACH, "x"))
    assert not request_definitely_not_sent(TimeoutError("timed out"))
    assert not request_definitely_not_sent(OSError(errno.ECONNRESET, "reset"))


def test_non_transient_socket_error_surfaces_as_tool_invocation_error(
    clock: _FakeClock,
) -> None:
    """Listen's per-message loop only knows ToolInvocationError (audit D3)."""

    def opener(request: Any, timeout: int = 60):
        raise OSError(errno.EACCES, "permission denied")

    with pytest.raises(ToolInvocationError, match="transport failed"):
        send_channel_message(
            token="tok", channel_id="123456789012345678", content="hi", opener=opener
        )


def test_error_body_is_surfaced_and_token_is_redacted(clock: _FakeClock) -> None:
    body = json.dumps(
        {
            "message": "Invalid Form Body",
            "code": 50035,
            "errors": {"components": {"0": {"_errors": [{"code": "COMPONENT_LAYOUT_WIDTH_EXCEEDED"}]}}},
        }
    ).encode("utf-8")

    def opener(request: Any, timeout: int = 60):
        raise _http_error(request.full_url, 400, body, {})

    with pytest.raises(ToolInvocationError) as caught:
        send_channel_message(
            token="super-secret-bot-token",
            channel_id="123456789012345678",
            content="hi",
            opener=opener,
        )
    text = str(caught.value)
    assert "HTTP 400" in text
    assert "Invalid Form Body" in text
    assert "COMPONENT_LAYOUT_WIDTH_EXCEEDED" in text
    assert "super-secret-bot-token" not in text


def test_429_gives_up_after_bounded_retries(clock: _FakeClock) -> None:
    calls = {"n": 0}

    def opener(request: Any, timeout: int = 60):
        calls["n"] += 1
        raise _http_error(
            request.full_url,
            429,
            json.dumps({"retry_after": 0.5}).encode("utf-8"),
            {},
        )

    with pytest.raises(ToolInvocationError, match="HTTP 429"):
        list_channel_messages(
            token="tok", channel_id="123456789012345678", opener=opener
        )
    assert calls["n"] == rest.RATE_LIMIT_MAX_RETRIES + 1


def test_429_with_an_absurd_retry_after_does_not_sleep(clock: _FakeClock) -> None:
    def opener(request: Any, timeout: int = 60):
        raise _http_error(
            request.full_url,
            429,
            json.dumps({"retry_after": 9999.0}).encode("utf-8"),
            {},
        )

    with pytest.raises(ToolInvocationError, match="retry_after"):
        list_channel_messages(
            token="tok", channel_id="123456789012345678", opener=opener
        )
    assert clock.slept == []
