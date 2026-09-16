"""Band A — kagekit spike fail + thin HOST Page layout."""

from __future__ import annotations

from pathlib import Path

from agent_discord.discord.host_page import (
    host_page_enabled,
    host_v2_payload,
    kagekit_spike_adopted,
    split_host_v2_components,
)
from agent_discord.discord.layout import TYPE_ACTION_ROW, TYPE_CONTAINER, action_row, button
from agent_discord.orchestration.cards import host_card


def test_kagekit_not_adopted():
    assert kagekit_spike_adopted() is False


def test_host_page_flag_default_on(monkeypatch):
    monkeypatch.delenv("DISCORD_OS_HOST_PAGE", raising=False)
    assert host_page_enabled() is True
    monkeypatch.setenv("DISCORD_OS_HOST_PAGE", "0")
    assert host_page_enabled() is False


def test_actions_outside_container():
    rows = [action_row([button("On", "discord-os:on")])]
    comps = split_host_v2_components(
        title="Stopped",
        description="Tip: Pair → Ask → Done",
        fields=(("acl", "open", True),),
        action_rows=rows,
    )
    assert comps[0]["type"] == TYPE_CONTAINER
    assert comps[1]["type"] == TYPE_ACTION_ROW
    assert comps[1]["components"][0]["custom_id"] == "discord-os:on"
    joined = "\n".join(
        c.get("content") or ""
        for child in comps[0]["components"]
        for c in ([child] if child.get("type") == 10 else [])
    )
    assert "<t:" in joined
    assert "board + brain lakes" in joined


def test_host_card_v2_uses_page_layout(monkeypatch):
    monkeypatch.setenv("DISCORD_OS_HOST_PAGE", "1")
    card = host_card(armed=False, paired=False, empty_jobs=True, last_job="")
    payload = card.v2_payload(
        rows=[action_row([button("Pair", "discord-os:pair")])]
    )
    comps = payload["components"]
    assert comps[0]["type"] == TYPE_CONTAINER
    assert any(c.get("type") == TYPE_ACTION_ROW for c in comps[1:])
    assert "Pair → Ask → Done" in (card.description or "")


def test_spike_doc_records_fail():
    text = (Path(__file__).resolve().parents[1] / "docs/co-work/band-a-kagekit-spike.md").read_text()
    assert "Do not adopt" in text or "FAIL" in text
    assert "graham" not in text.lower() or "never graham" in text.lower()
    assert "host_page" in text
