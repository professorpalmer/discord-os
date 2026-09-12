"""Honest OpenRouter / PM-adapter spend: omitted cost_usd → unknown, not $0."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import UsageReceipt
from agent_discord.orchestration.cards import _host_status_fields
from agent_discord.orchestration.receipts import render_receipt
from agent_discord.orchestration.service import (
    format_spend,
    mark_spend_cost_known,
    provider_cost_usd,
    spend_cost_known,
    spend_usd_from_usage,
)
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.backend import usage_from_cli_meta
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN
from agent_discord.contracts import RunReceipt, TaskStatus


def test_provider_cost_omitted_is_none() -> None:
    usage = UsageReceipt(
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        input_tokens=10,
        output_tokens=5,
        metadata={"backend": "cli"},
    )
    assert provider_cost_usd(usage) is None
    assert format_spend(None, known=False) == "unknown"


def test_provider_cost_present_kept() -> None:
    usage = usage_from_cli_meta(
        AGENTIC_MODEL_PIN,
        "puppetmaster",
        {"cost_usd": 0.042, "input_tokens": 10, "output_tokens": 5},
    )
    assert provider_cost_usd(usage) == 0.042
    assert spend_usd_from_usage(usage) == 0.042
    assert format_spend(0.042, known=True).startswith("$")


def test_halt_fields_show_unknown_when_cost_unknown() -> None:
    rows = _host_status_fields(
        paired=True,
        operator_count=1,
        role_count=0,
        write_gate=False,
        spend_usd=0.0,
        cap_usd=5.0,
        halted=True,
        realm="discord-os",
        bank=False,
        spend_known=False,
    )
    spend_vals = [r[1] for r in rows if str(r[0]).lower() == "spend"]
    assert spend_vals
    assert "unknown" in spend_vals[0]
    assert "$0" not in spend_vals[0]


def test_receipt_cost_line_unknown(tmp_path: Path) -> None:
    usage = UsageReceipt(
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        metadata={"backend": "cli"},
    )
    receipt = RunReceipt(
        task_id="t1",
        run_id="r1",
        status=TaskStatus.COMPLETED,
        summary="ok",
        usage=usage,
    )
    body = render_receipt(receipt)
    assert "Cost: unknown" in body


def test_mark_spend_cost_known(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.sqlite3")
    store.initialize()
    assert spend_cost_known(store) is False
    mark_spend_cost_known(store, True)
    assert spend_cost_known(store) is True
    store.close()
