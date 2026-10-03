"""Message chunking, provider selection, gateway exclusivity."""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent_discord.config import ConfigError, load_config
from agent_discord.contracts import DiscordMessage, ToolDescriptor
from agent_discord.discord.chunking import chunk_message
from agent_discord.discord.errors import (
    GatewayOwnershipError,
    MessageDedupError,
    ProviderSelectionError,
)
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.gateway import InMemoryGatewayOwnerRegistry
from agent_discord.discord.providers import select_provider
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.discord.providers.rest import RestDiscordProvider


class RecordingClient:
    def __init__(self):
        self.calls = []
        self.tools = [
            ToolDescriptor(name="send_message"),
            ToolDescriptor(name="read_messages"),
            ToolDescriptor(name="create_thread"),
        ]

    def list_tools(self):
        return list(self.tools)

    def call_tool(self, name, arguments):
        from agent_discord.contracts import ToolInvocationResult

        self.calls.append((name, dict(arguments)))
        return ToolInvocationResult(
            name=name, ok=True, content={"id": "m1"}, raw={"id": "m1", "messageId": "m1"}
        )


def test_chunk_message_respects_limit():
    text = "alpha beta gamma " * 50
    chunks = chunk_message(text, limit=40)
    assert len(chunks) > 1
    assert all(len(c) <= 40 for c in chunks)
    assert "alpha" in chunks[0]
    assert "gamma" in "".join(chunks)


def test_chunk_empty():
    assert chunk_message("") == [""]


def test_facade_repeats_card_prefix_on_every_chunk():
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="abc", owner_id="o1")
    body = "progress line\n" * 40
    posted = facade.send_message("ch", f"**Card** PROGRESS\n{body}", chunk_limit=40)
    assert len(posted) > 1
    assert posted[0].content.startswith("**Card** PROGRESS")
    assert all(m.content.startswith("**Card**") for m in posted)


def test_facade_chunks_and_dedupes():
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="abc", owner_id="o1")
    long = "word " * 100
    posted = facade.send_message("ch", long, chunk_limit=30)
    assert len(posted) > 1
    assert len(fake.sent) == len(posted)

    fake.inbox.append(
        DiscordMessage(channel_id="ch", content="hi", message_id="dup-1")
    )
    first = facade.read_messages("ch")
    assert len(first) == 1
    second = facade.read_messages("ch")
    assert second == []

    with pytest.raises(MessageDedupError):
        facade.observe_message_id("dup-1")


def test_gateway_owner_exclusivity():
    reg = InMemoryGatewayOwnerRegistry()
    reg.claim("tok", "owner-a")
    with pytest.raises(GatewayOwnershipError):
        reg.claim("tok", "owner-b")
    assert reg.current_owner("tok") == "owner-a"
    reg.release("tok", "owner-a")
    reg.claim("tok", "owner-b")
    assert reg.current_owner("tok") == "owner-b"


def test_provider_selection_rejects_removed_adapters(tmp_path):
    with pytest.raises(ConfigError, match="saseq"):
        load_config(
            env={
                "AGENT_DISCORD_WORKSPACE": str(tmp_path),
                "DISCORD_MCP_PROVIDER": "saseq",
                "DISCORD_BOT_TOKEN": "x",
            },
            dotenv_path=tmp_path / "none",
        )
    cfg = load_config(
        env={
            "AGENT_DISCORD_WORKSPACE": str(tmp_path),
            "DISCORD_BOT_TOKEN": "x",
        },
        dotenv_path=tmp_path / "none",
    )
    assert isinstance(select_provider(cfg), RestDiscordProvider)
    with pytest.raises(ProviderSelectionError, match="braindao"):
        select_provider(replace(cfg, discord_mcp_provider="braindao"))
