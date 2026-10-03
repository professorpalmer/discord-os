"""Components V2 ceilings: 40 components, 4000 text chars (audit D1).

An oversized card used to be sent as-is, get a 400, and have the Discord error
body discarded, so the live card silently stopped updating.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest

from agent_discord.discord.errors import ToolInvocationError
from agent_discord.discord.layout import (
    COMPONENTS_V2_MAX_COMPONENTS,
    COMPONENTS_V2_MAX_TEXT_CHARS,
    FLAG_COMPONENTS_V2,
    TYPE_ACTION_ROW,
    TYPE_BUTTON,
    TYPE_SEPARATOR,
    TYPE_TEXT,
    action_row,
    button,
    container,
    count_components,
    fit_components_v2,
    separator,
    text_display,
    total_text_chars,
)
from agent_discord.discord.rest import edit_channel_message, send_channel_message


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.headers: dict[str, str] = {}

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _controls() -> dict[str, Any]:
    return action_row(
        [
            button("Halt", "job:halt:1"),
            button("Steer", "job:steer:1"),
            button("Logs", "job:logs:1"),
        ]
    )


def _oversized_card(rows: int = 60, chars: int = 300) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = [text_display("**Card** job 1")]
    for index in range(rows):
        children.append(text_display(f"step {index} " + "x" * chars))
        children.append(separator())
    children.append(_controls())
    return [container(children, color=0x5865F2)]


def _buttons(components: Any) -> list[str]:
    found: list[str] = []
    for item in components or ():
        if not isinstance(item, dict):
            continue
        if int(item.get("type") or 0) == TYPE_BUTTON:
            found.append(str(item.get("custom_id") or ""))
        found.extend(_buttons(item.get("components")))
    return found


def test_oversized_card_is_sent_as_is_without_the_fit() -> None:
    """Guard the fixture: the raw card really does break both ceilings."""

    raw = _oversized_card()
    assert count_components(raw) > COMPONENTS_V2_MAX_COMPONENTS
    assert total_text_chars(raw) > COMPONENTS_V2_MAX_TEXT_CHARS


def test_fit_keeps_buttons_and_fits_both_ceilings() -> None:
    fitted = fit_components_v2(_oversized_card())
    assert count_components(fitted) <= COMPONENTS_V2_MAX_COMPONENTS
    assert total_text_chars(fitted) <= COMPONENTS_V2_MAX_TEXT_CHARS
    assert _buttons(fitted) == ["job:halt:1", "job:steer:1", "job:logs:1"]
    # The container survives; only its tail rows went.
    assert len(fitted) == 1
    assert fitted[0]["type"] == 17


def test_fit_truncates_long_text_rather_than_dropping_the_only_row() -> None:
    card = [container([text_display("y" * 9000), _controls()], color=1)]
    fitted = fit_components_v2(card)
    assert total_text_chars(fitted) <= COMPONENTS_V2_MAX_TEXT_CHARS
    texts = [
        child["content"]
        for child in fitted[0]["components"]
        if child.get("type") == TYPE_TEXT
    ]
    assert len(texts) == 1
    assert texts[0].endswith("[trimmed]")
    assert _buttons(fitted) == ["job:halt:1", "job:steer:1", "job:logs:1"]


def test_fit_never_drops_an_action_row_to_meet_the_count() -> None:
    children: list[dict[str, Any]] = [separator() for _ in range(80)]
    children.append(_controls())
    fitted = fit_components_v2([container(children, color=1)])
    assert count_components(fitted) <= COMPONENTS_V2_MAX_COMPONENTS
    kinds = [child["type"] for child in fitted[0]["components"]]
    assert TYPE_ACTION_ROW in kinds
    assert kinds.count(TYPE_SEPARATOR) < 80


def test_fit_does_not_mutate_the_caller_payload() -> None:
    card = _oversized_card()
    before = json.dumps(card, sort_keys=True)
    fit_components_v2(card)
    assert json.dumps(card, sort_keys=True) == before


def test_send_channel_message_trims_the_card_before_posting() -> None:
    captured: dict[str, Any] = {}

    def opener(request: Any, timeout: int = 60):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(
            json.dumps({"id": "m-1", "channel_id": "ch", "content": ""}).encode("utf-8")
        )

    send_channel_message(
        token="tok",
        channel_id="123456789012345678",
        content="",
        components=_oversized_card(),
        flags=FLAG_COMPONENTS_V2,
        opener=opener,
    )
    sent = captured["payload"]["components"]
    assert count_components(sent) <= COMPONENTS_V2_MAX_COMPONENTS
    assert total_text_chars(sent) <= COMPONENTS_V2_MAX_TEXT_CHARS
    assert _buttons(sent) == ["job:halt:1", "job:steer:1", "job:logs:1"]


def test_edit_channel_message_trims_the_card_before_patching() -> None:
    captured: dict[str, Any] = {}

    def opener(request: Any, timeout: int = 60):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(
            json.dumps({"id": "m-1", "channel_id": "ch", "content": ""}).encode("utf-8")
        )

    edit_channel_message(
        token="tok",
        channel_id="123456789012345678",
        message_id="987654321098765432",
        content="",
        components=_oversized_card(),
        flags=FLAG_COMPONENTS_V2,
        opener=opener,
    )
    sent = captured["payload"]["components"]
    assert count_components(sent) <= COMPONENTS_V2_MAX_COMPONENTS
    assert total_text_chars(sent) <= COMPONENTS_V2_MAX_TEXT_CHARS
    assert _buttons(sent) == ["job:halt:1", "job:steer:1", "job:logs:1"]


def test_card_edit_400_surfaces_the_discord_field_paths(monkeypatch) -> None:
    monkeypatch.setattr("agent_discord.discord.rest._retry_sleep", lambda _s: None)
    body = json.dumps(
        {
            "message": "Invalid Form Body",
            "code": 50035,
            "errors": {
                "components": {
                    "0": {
                        "components": {
                            "_errors": [
                                {
                                    "code": "COMPONENT_COUNT_EXCEEDED",
                                    "message": "Must be 40 or fewer in length.",
                                }
                            ]
                        }
                    }
                }
            },
        }
    ).encode("utf-8")

    def opener(request: Any, timeout: int = 60):
        raise HTTPError(request.full_url, 400, "Bad Request", {}, BytesIO(body))

    with pytest.raises(ToolInvocationError) as caught:
        edit_channel_message(
            token="a-live-bot-token",
            channel_id="123456789012345678",
            message_id="987654321098765432",
            content="",
            components=[container([text_display("x"), _controls()], color=1)],
            flags=FLAG_COMPONENTS_V2,
            opener=opener,
        )
    text = str(caught.value)
    assert "HTTP 400" in text
    assert "COMPONENT_COUNT_EXCEEDED" in text
    assert '"components"' in text or "components" in text
    assert "a-live-bot-token" not in text
