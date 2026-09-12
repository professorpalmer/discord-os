"""Pinned model constants — exact allowlist, no silent fallback."""

from __future__ import annotations

from agent_discord.contracts import ModelPin

CANONICAL_MODEL = "openrouter/auto"
ADAPTER_NAME = "openrouter/auto"

DEFAULT_MODEL_PIN = ModelPin(
    canonical=CANONICAL_MODEL,
    adapter_name=ADAPTER_NAME,
    allowlist=(CANONICAL_MODEL,),
)

# Product compute is agentic/OpenRouter only. Aliases kept for call sites.
AGENTIC_CANONICAL_MODEL = CANONICAL_MODEL
AGENTIC_ADAPTER_NAME = ADAPTER_NAME
AGENTIC_MODEL_PIN = DEFAULT_MODEL_PIN
