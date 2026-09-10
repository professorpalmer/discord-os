"""Agentic UsageReceipt must carry CLI cost into Halt spend."""

from __future__ import annotations

from agent_discord.contracts import ModelPin
from agent_discord.orchestration.service import spend_usd_from_usage
from agent_discord.puppetmaster.backend import usage_from_cli_meta
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN


def test_usage_from_cli_meta_cost_feeds_spend() -> None:
    pin: ModelPin = AGENTIC_MODEL_PIN
    usage = usage_from_cli_meta(
        pin,
        "puppetmaster",
        {
            "job_id": "job_test",
            "summary": "ok",
            "cost_usd": 0.042,
            "input_tokens": 10,
            "output_tokens": 5,
        },
    )
    assert usage.model == pin.canonical
    assert usage.adapter_name == pin.adapter_name
    assert usage.metadata.get("cost_usd") == 0.042
    assert spend_usd_from_usage(usage) == 0.042


def test_usage_from_cli_meta_nested_usage_block() -> None:
    pin = AGENTIC_MODEL_PIN
    usage = usage_from_cli_meta(
        pin,
        "puppetmaster",
        {"usage": {"cost_usd": 1.25, "input_tokens": 100, "output_tokens": 20}},
    )
    assert spend_usd_from_usage(usage) == 1.25
