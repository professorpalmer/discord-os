"""Discord provider adapters. REST is the only live provider; fake backs tests."""

from __future__ import annotations

from typing import Any, Optional

from agent_discord.config import AppConfig
from agent_discord.discord.errors import ProviderSelectionError
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.discord.providers.rest import RestDiscordProvider


def select_provider(
    config: AppConfig,
    *,
    client: Any | None = None,
    bot_token: Optional[str] = None,
):
    """Build a provider adapter from config. Inject `client` in tests."""
    token = config.discord_bot_token if bot_token is None else bot_token
    name = config.discord_mcp_provider
    if name == "rest":
        return RestDiscordProvider(bot_token=token)
    raise ProviderSelectionError(f"unknown provider {name!r}")


__all__ = [
    "FakeDiscordMCPProvider",
    "RestDiscordProvider",
    "select_provider",
]
