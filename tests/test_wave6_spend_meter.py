"""Wave 6 P0a — HOST spend meter + Halt honesty."""

from __future__ import annotations

from pathlib import Path

from agent_discord.discord.layout import progress_bar
from agent_discord.host.status_digest import format_status_digest
from agent_discord.orchestration.cards import _host_status_fields
from agent_discord.orchestration.service import format_spend_meter


def test_progress_bar_ascii():
    assert progress_bar(0, width=10).startswith("[")
    assert "100%" in progress_bar(100, width=10)


def test_meter_unknown_never_invents_zero():
    s = format_spend_meter(None, known=False, cap_usd=10.0, halted=False)
    assert "unknown" in s
    assert "$0" not in s
    assert "?" in s or "unknown" in s


def test_meter_cap_known_fills():
    s = format_spend_meter(2.5, known=True, cap_usd=10.0, halted=False)
    assert "$2.50" in s
    assert "$10.00" in s
    assert "[" in s and "]" in s
    assert "25%" in s


def test_meter_cap_none_path():
    s = format_spend_meter(1.0, known=True, cap_usd=None, halted=False)
    assert "cap none" in s
    assert "known" in s
    assert "$0" not in s or "$1" in s  # spent is $1, not invented zero


def test_meter_halt_badge():
    s = format_spend_meter(0.5, known=True, cap_usd=5.0, halted=True)
    assert "halted" in s


def test_host_fields_unknown_and_halt():
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
    assert "halted" in spend_vals[0]


def test_status_digest_uses_meter():
    body = format_status_digest(
        {
            "version": "0.5.77",
            "host": {"armed": False, "running": True},
            "spend": {
                "spend_usd": 1.25,
                "cap_usd": 10.0,
                "spend_known": True,
                "halted": True,
            },
            "jobs": [],
            "hosts": [],
        }
    )
    assert "spend" in body
    assert "halted" in body
    assert "[" in body  # meter


def test_wave6_spend_docs():
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs/co-work/wave6-spend-meter.md").read_text().lower()
    assert "unknown" in text
    assert "$0" in text or "≠" in text or "!=" in text
    assert "halt" in text
    assert "graham" not in text
