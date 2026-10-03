"""Facade capability checks instead of except TypeError (audit D9).

A TypeError raised while serializing a Components V2 payload or parsing the
response used to look like a signature mismatch, so the facade retried without
the components or re-posted a message Discord had already accepted.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from agent_discord.contracts import DiscordMessage
from agent_discord.discord.facade import DiscordFacade, accepts_keyword
from agent_discord.discord.layout import FLAG_COMPONENTS_V2


def _msg(message_id: str = "m-1") -> DiscordMessage:
    return DiscordMessage(channel_id="ch", content="", message_id=message_id)


class _RichProvider:
    """Full modern signature, but it blows up mid-serialization."""

    name = "rich"

    def __init__(self, *, explode: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.explode = explode

    def send_message(
        self,
        channel_id: str,
        content: str,
        *,
        thread_id: Optional[str] = None,
        components: Optional[list] = None,
        embeds: Optional[list] = None,
        flags: int = 0,
    ) -> DiscordMessage:
        self.calls.append({"content": content, "components": components, "flags": flags})
        if self.explode:
            raise TypeError("Object of type set is not JSON serializable")
        return _msg()

    def edit_message(
        self,
        channel_id: str,
        message_id: str,
        content: str,
        *,
        components: Optional[list] = None,
        embeds: Optional[list] = None,
        flags: int = 0,
    ) -> DiscordMessage:
        self.calls.append({"edit": message_id, "components": components, "flags": flags})
        if self.explode:
            raise TypeError("'NoneType' object is not subscriptable")
        return _msg(message_id)

    def send_attachment(
        self,
        channel_id: str,
        filename: str,
        data: bytes,
        *,
        content: str = "",
        thread_id: Optional[str] = None,
        embeds: Optional[list] = None,
        components: Optional[list] = None,
        flags: int = 0,
    ) -> DiscordMessage:
        self.calls.append({"file": filename, "components": components, "flags": flags})
        if self.explode:
            raise TypeError("cannot serialize component")
        return _msg("m-file")


class _LegacyProvider:
    """Old provider: no embeds, no flags, no Components V2."""

    name = "legacy"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_message(
        self,
        channel_id: str,
        content: str,
        *,
        thread_id: Optional[str] = None,
        components: Optional[list] = None,
    ) -> DiscordMessage:
        self.calls.append({"content": content, "components": components})
        return _msg()

    def edit_message(
        self, channel_id: str, message_id: str, content: str
    ) -> DiscordMessage:
        self.calls.append({"edit": message_id, "content": content})
        return _msg(message_id)

    def send_attachment(
        self,
        channel_id: str,
        filename: str,
        data: bytes,
        *,
        content: str = "",
        thread_id: Optional[str] = None,
    ) -> DiscordMessage:
        self.calls.append({"file": filename, "content": content})
        return _msg("m-file")


class _KwargsProvider:
    name = "kwargs"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_message(self, channel_id: str, content: str, **kwargs: Any) -> DiscordMessage:
        self.calls.append(dict(kwargs))
        return _msg()


def test_accepts_keyword_reads_the_signature() -> None:
    rich = _RichProvider()
    assert accepts_keyword(rich.send_message, "flags") is True
    assert accepts_keyword(rich.send_message, "embeds") is True
    legacy = _LegacyProvider()
    assert accepts_keyword(legacy.send_message, "flags") is False
    assert accepts_keyword(legacy.send_message, "components") is True
    assert accepts_keyword(legacy.edit_message, "components") is False
    # **kwargs swallows anything.
    assert accepts_keyword(_KwargsProvider().send_message, "flags") is True
    # Positional-only never takes the keyword.
    assert accepts_keyword(len, "obj") is False


def test_serialization_type_error_propagates_from_send() -> None:
    provider = _RichProvider(explode=True)
    facade = DiscordFacade(provider)
    with pytest.raises(TypeError, match="JSON serializable"):
        facade.send_message(
            "ch", "", components=[{"type": 17}], flags=FLAG_COMPONENTS_V2
        )
    # One attempt only: no silent resend that drops the Components V2 payload.
    assert len(provider.calls) == 1
    assert provider.calls[0]["flags"] == FLAG_COMPONENTS_V2


def test_response_type_error_propagates_from_edit() -> None:
    provider = _RichProvider(explode=True)
    facade = DiscordFacade(provider)
    with pytest.raises(TypeError, match="not subscriptable"):
        facade.edit_message(
            "ch", "m-1", "", components=[{"type": 17}], flags=FLAG_COMPONENTS_V2
        )
    assert len(provider.calls) == 1


def test_type_error_propagates_from_send_attachment() -> None:
    provider = _RichProvider(explode=True)
    facade = DiscordFacade(provider)
    with pytest.raises(TypeError, match="serialize component"):
        facade.send_attachment(
            "ch", "a.png", b"x", components=[{"type": 17}], flags=FLAG_COMPONENTS_V2
        )
    assert len(provider.calls) == 1


def test_legacy_provider_gets_a_text_fallback_in_one_call() -> None:
    provider = _LegacyProvider()
    facade = DiscordFacade(provider)
    posted = facade.send_message(
        "ch",
        "",
        embeds=[{"title": "Job 1", "description": "running"}],
        flags=0,
    )
    assert [msg.message_id for msg in posted] == ["m-1"]
    assert len(provider.calls) == 1
    assert provider.calls[0]["content"] == "Job 1\nrunning"


def test_legacy_edit_drops_unsupported_keywords() -> None:
    provider = _LegacyProvider()
    facade = DiscordFacade(provider)
    facade.edit_message("ch", "m-7", "text", components=[{"type": 1}], flags=0)
    assert provider.calls == [{"edit": "m-7", "content": "text"}]


def test_legacy_attachment_drops_unsupported_keywords() -> None:
    provider = _LegacyProvider()
    facade = DiscordFacade(provider)
    facade.send_attachment(
        "ch", "a.png", b"x", content="hi", components=[{"type": 1}], flags=7
    )
    assert provider.calls == [{"file": "a.png", "content": "hi"}]


def test_rich_provider_keeps_components_and_flags() -> None:
    provider = _RichProvider()
    facade = DiscordFacade(provider)
    facade.send_message(
        "ch", "", components=[{"type": 17}], flags=FLAG_COMPONENTS_V2
    )
    assert provider.calls[0]["components"] == [{"type": 17}]
    assert provider.calls[0]["flags"] == FLAG_COMPONENTS_V2
