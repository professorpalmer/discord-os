"""/ask — slash front door for the HOST Ask modal."""

from __future__ import annotations

from pathlib import Path

from agent_discord.discord.interactions import (
    ASK_COMMAND,
    INTERACTION_APPLICATION_COMMAND,
    INTERACTION_APPLICATION_COMMAND_AUTOCOMPLETE,
    OPT_IN_COMMANDS,
    handle_interaction_payload,
)
from agent_discord.host.realms import channel_for_realm
from agent_discord.persistence.sqlite import SQLiteStore


def _ask_payload(prompt: str, *, realm: str = "", channel_id: str = "ch-1", author_id: str = "human-1"):
    options = [{"name": "prompt", "value": prompt}]
    if realm:
        options.append({"name": "realm", "value": realm})
    return {
        "type": INTERACTION_APPLICATION_COMMAND,
        "id": "ix-ask",
        "token": "tok-ask",
        "channel_id": channel_id,
        "member": {"user": {"id": author_id}},
        "data": {"name": "ask", "options": options},
    }


def test_ask_command_registered_with_autocomplete_realm():
    assert ASK_COMMAND in OPT_IN_COMMANDS
    options = {opt["name"]: opt for opt in ASK_COMMAND["options"]}
    assert options["prompt"]["required"] is True
    assert options["realm"]["autocomplete"] is True
    assert options["realm"].get("required", False) is False


def test_ask_enqueues_with_requester_and_channel(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    seen: list[tuple[str, str, str]] = []

    reply = handle_interaction_payload(
        _ask_payload("ship the thing"),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert seen == [("ch-1", "ship the thing", "human-1")]
    assert reply["data"]["flags"] == 64
    assert reply["data"]["content"].startswith("On it.")
    assert "<#ch-1>" in reply["data"]["content"]


def test_ask_receipt_carries_a_job_code_when_known(tmp_path: Path):
    reply = handle_interaction_payload(
        _ask_payload("cook"),
        workspace=tmp_path,
        roots=[tmp_path],
        on_ask=lambda channel, text, requester: "DOS-10001",
    )
    assert "DOS-10001" in reply["data"]["content"]


def test_ask_realm_option_picks_the_bound_channel(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    repo = tmp_path / "puppetmaster"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setenv("DISCORD_OS_REPOS", f"puppetmaster:{repo}")
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.merge_binding_metadata(
        "default", "ch-pup", {"repo": "puppetmaster", "cwd": str(repo)}
    )
    assert channel_for_realm(store, "puppetmaster") == "ch-pup"
    store.close()

    seen: list[tuple[str, str, str]] = []
    reply = handle_interaction_payload(
        _ask_payload("audit the router", realm="puppetmaster"),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert seen[0][0] == "ch-pup"
    assert "<#ch-pup>" in reply["data"]["content"]


def test_ask_unbound_realm_refuses(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    seen: list[tuple[str, str, str]] = []
    reply = handle_interaction_payload(
        _ask_payload("go", realm="nowhere"),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert seen == []
    assert "no channel bound" in reply["data"]["content"].lower()


def test_ask_denied_for_non_operator(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.add_operator("owner-1", role="owner")
    store.close()

    seen: list[tuple[str, str, str]] = []
    denied = handle_interaction_payload(
        _ask_payload("sneak", author_id="stranger-9"),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert seen == []
    assert "denied" in denied["data"]["content"].lower()

    allowed = handle_interaction_payload(
        _ask_payload("fine", author_id="owner-1"),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert seen == [("ch-1", "fine", "owner-1")]
    assert allowed["data"]["content"].startswith("On it.")


def test_ask_without_a_host_queue_is_honest(tmp_path: Path):
    reply = handle_interaction_payload(
        _ask_payload("cook"),
        workspace=tmp_path,
        roots=[tmp_path],
    )
    assert "listen host" in reply["data"]["content"].lower()


def test_ask_empty_prompt_refuses(tmp_path: Path):
    reply = handle_interaction_payload(
        _ask_payload("   "),
        workspace=tmp_path,
        roots=[tmp_path],
        on_ask=lambda *a: None,
    )
    assert "needs a prompt" in reply["data"]["content"].lower()


def test_ask_realm_autocomplete_uses_the_bind_source(tmp_path: Path, monkeypatch):
    repo = tmp_path / "marionette"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setenv("DISCORD_OS_REPOS", f"marionette:{repo}")
    reply = handle_interaction_payload(
        {
            "type": INTERACTION_APPLICATION_COMMAND_AUTOCOMPLETE,
            "channel_id": "ch-1",
            "data": {
                "name": "ask",
                "options": [
                    {"name": "prompt", "value": "x"},
                    {"name": "realm", "value": "mario", "focused": True},
                ],
            },
        },
        workspace=tmp_path,
        roots=[tmp_path],
    )
    values = [choice["value"] for choice in reply["data"]["choices"]]
    assert "marionette" in values
