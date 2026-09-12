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

def test_spend_usd_parses_dollar_string() -> None:
    from agent_discord.contracts import UsageReceipt

    usage = UsageReceipt(
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        metadata={"cost_usd": "$0.0420"},
    )
    assert spend_usd_from_usage(usage) == 0.042


def test_host_status_fields_include_recorded_spend(tmp_path) -> None:
    from pathlib import Path

    from agent_discord.orchestration.cards import _host_status_fields
    from agent_discord.orchestration.service import format_usd
    from agent_discord.persistence.sqlite import SQLiteStore

    store = SQLiteStore(Path(tmp_path) / "t.sqlite3")
    store.initialize()
    store.record_spend("default", "run-1", 0.12)
    spend = store.session_spend_usd("default")
    assert abs(spend - 0.12) < 1e-9
    rows = _host_status_fields(
        paired=True,
        operator_count=1,
        role_count=0,
        write_gate=False,
        spend_usd=spend,
        cap_usd=5.0,
        halted=False,
        realm="discord-os",
        bank=False,
    )
    spend_vals = [r[1] for r in rows if str(r[0]).lower() == "spend"]
    assert spend_vals, rows
    assert format_usd(0.12) in spend_vals[0]
    store.close()
