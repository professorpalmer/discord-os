"""P1 co-work: handoff parse, attribution fields, desk-pack, schedule list."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import RunReceipt, TaskStatus
from agent_discord.host.add import add_desk_pack
from agent_discord.orchestration.cards import receipt_card
from agent_discord.orchestration.service import parse_handoff_command
from agent_discord.persistence.sqlite import SQLiteStore


def test_parse_handoff_command():
    assert parse_handoff_command("handoff <@123456789012345678>: do x") == (
        "123456789012345678",
        "do x",
    )
    peer, prompt = parse_handoff_command("peer 123456789012345678 fix it")
    assert peer == "123456789012345678"
    assert prompt == "fix it"
    assert parse_handoff_command("not handoff") is None


def test_receipt_card_operator_lane_fields():
    receipt = RunReceipt(
        task_id="t",
        run_id="r",
        status=TaskStatus.COMPLETED,
        summary="ok",
    )
    card = receipt_card(receipt, operator="111", lane="handoff")
    names = {n for n, _v, _i in card.fields}
    assert "Operator" in names
    assert "Lane" in names


def test_add_desk_pack_realm_memory(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(tmp_path / "ws"))
    ws = tmp_path / "ws"
    ws.mkdir()
    env = ws / ".env"
    env.write_text("DISCORD_BOT_TOKEN=x\n")
    store = SQLiteStore(ws / "db.sqlite3")
    store.initialize()
    # Without a real repo catalog, realm may be live=False — still returns steps
    payload = add_desk_pack(store, channel_id="ch-desk", realm="puppetmaster", env_file=env)
    assert payload["kind"] == "desk-pack"
    kinds = [s["kind"] for s in payload["steps"]]
    assert kinds[:2] == ["realm", "memory"]
    store.close()
