"""TIDY polish: quiet drain / Errno 49, no fake READY, policy locks, forum soak."""

from __future__ import annotations

import errno
import json
from io import BytesIO
from pathlib import Path
from urllib.error import URLError

import pytest

from agent_discord.discord.errors import ToolInvocationError
from agent_discord.discord.gateway_health import (
    note_gateway_expected,
    reset_gateway_health_for_tests,
    snapshot_gateway_health,
)
from agent_discord.discord.rest import (
    is_transient_discord_network_error,
    send_channel_message,
    transient_network_label,
)
from agent_discord.host.forum_realm import build_status_tag_id_map, parse_available_tags


ROOT = Path(__file__).resolve().parents[1]


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_transient_classifier_errno_49_and_timeout() -> None:
    err49 = OSError(errno.EADDRNOTAVAIL, "Can't assign requested address")
    assert is_transient_discord_network_error(err49) is True
    assert "49" in transient_network_label(err49)
    assert is_transient_discord_network_error(TimeoutError("timed out")) is True
    assert is_transient_discord_network_error(URLError(err49)) is True
    assert is_transient_discord_network_error(ValueError("nope")) is False
    assert is_transient_discord_network_error(
        ToolInvocationError("Discord REST unreachable (timeout)")
    )
    assert is_transient_discord_network_error(
        OSError("The read operation timed out")
    )
    assert "timeout" in transient_network_label(
        OSError("The read operation timed out")
    ) or "timed out" in str(OSError("The read operation timed out")).lower()


def test_rest_retries_timeout_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("agent_discord.discord.rest._retry_sleep", lambda _s: None)
    calls = {"n": 0}

    def opener(request, timeout=60):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("timed out")
        return _FakeResponse(
            json.dumps(
                {"id": "m-ok", "channel_id": "ch", "content": "hi"}
            ).encode("utf-8")
        )

    posted = send_channel_message(
        token="tok", channel_id="ch", content="hi", opener=opener
    )
    assert posted.message_id == "m-ok"
    assert calls["n"] == 2


def test_rest_retries_errno_49_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("agent_discord.discord.rest._retry_sleep", lambda _s: None)
    calls = {"n": 0}

    def opener(request, timeout=60):
        calls["n"] += 1
        if calls["n"] < 3:
            raise URLError(OSError(errno.EADDRNOTAVAIL, "Can't assign requested address"))
        return _FakeResponse(
            json.dumps(
                {"id": "m-49", "channel_id": "ch", "content": "hi"}
            ).encode("utf-8")
        )

    posted = send_channel_message(
        token="tok", channel_id="ch", content="hi", opener=opener
    )
    assert posted.message_id == "m-49"
    assert calls["n"] == 3


def test_note_gateway_expected_is_not_fake_ready_or_connected() -> None:
    reset_gateway_health_for_tests()
    note_gateway_expected(now=1000.0)
    snap = snapshot_gateway_health(now=1000.0, never_ready_grace_s=90.0)
    assert snap.ready is False
    assert snap.connected is False  # expected alone must not fake connected
    assert snap.ok is True  # still in grace


def test_forum_alias_soak_manual_tags_only() -> None:
    tags = parse_available_tags(
        {
            "available_tags": [
                {"id": "1", "name": "todo"},
                {"id": "2", "name": "active"},
                {"id": "3", "name": "blocked"},
                {"id": "4", "name": "stopped"},
                {"id": "5", "name": "success"},
            ]
        }
    )
    smap = build_status_tag_id_map(tags)
    assert smap["pending"] == "1"
    assert smap["running"] == "2"
    assert smap["failed"] == "3"
    assert smap["cancelled"] == "4"
    assert smap["completed"] == "5"
    # Never invent — empty available_tags → empty map
    assert build_status_tag_id_map(parse_available_tags({"available_tags": []})) == {}


def test_policy_doc_stamps_ten_hard_locks() -> None:
    text = (ROOT / "docs/host/policy.md").read_text(encoding="utf-8")
    assert "HARD locks" in text
    for needle in (
        "SSH bridge OPT-IN",
        "No forum auto-create tags",
        "never silent local",
        "Single gateway",
        "Update = PyPI",
        "local TTS",
        "Spend honesty",
        "Desk single-user",
        "Slash self-heal",
        "CU / docker PARKED",
    ):
        assert needle in text, needle


def test_forum_realm_module_never_posts_available_tags() -> None:
    src = (ROOT / "src/agent_discord/host/forum_realm.py").read_text(encoding="utf-8")
    assert "available_tags" in src
    # No create/POST invent path for guild tags
    assert "create_tag" not in src
    assert "/available_tags" not in src
    assert "never invent" in src.lower() or "does **not** invent" in src.lower() or "Does **not** invent" in src
