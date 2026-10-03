"""User-install: commands that reach outside the operator's server.

Answered through the interaction webhook, never channel REST, and fail
closed for anyone but a paired operator.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_discord.discord.interactions import (
    COMMAND_TYPE_MESSAGE,
    GUILD_INSTALL,
    INSTALL_CONTEXTS,
    INTEGRATION_TYPES,
    INTERACTION_APPLICATION_COMMAND,
    MESSAGE_COMMAND_NAME,
    OPT_IN_COMMANDS,
    USER_INSTALL,
    handle_interaction_payload,
    is_user_install_context,
    register_opt_in_commands,
    route_gateway_interaction,
)
from agent_discord.persistence.sqlite import SQLiteStore


def _store_with_home(ws: Path, *, operator: str = "owner-1") -> None:
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.upsert_binding(
        workspace_id="default",
        channel_id="ch-home",
        guild_id="guild-home",
        metadata={"repo": "discord-os"},
    )
    if operator:
        store.add_operator(operator, role="owner")
    store.close()


def _outside_ask(prompt: str = "cook this", *, author_id: str = "owner-1"):
    return {
        "type": INTERACTION_APPLICATION_COMMAND,
        "id": "ix-ui",
        "token": "tok-ui",
        # A guild the bot is not in: only the user install authorized this.
        "guild_id": "guild-stranger",
        "channel_id": "ch-stranger",
        "context": 0,
        "authorizing_integration_owners": {str(USER_INSTALL): author_id},
        "user": {"id": author_id},
        "data": {"name": "ask", "options": [{"name": "prompt", "value": prompt}]},
    }


def _outside_message(*, author_id: str = "owner-1"):
    return {
        "type": INTERACTION_APPLICATION_COMMAND,
        "id": "ix-ui-msg",
        "token": "tok-ui-msg",
        "guild_id": "guild-stranger",
        "channel_id": "ch-stranger",
        "authorizing_integration_owners": {str(USER_INSTALL): author_id},
        "user": {"id": author_id},
        "data": {
            "name": MESSAGE_COMMAND_NAME,
            "type": COMMAND_TYPE_MESSAGE,
            "target_id": "msg-9",
            "resolved": {
                "messages": {
                    "msg-9": {
                        "id": "msg-9",
                        "channel_id": "ch-stranger",
                        "content": "this broke",
                        "author": {"id": "author-3", "username": "dana"},
                        "attachments": [],
                    }
                }
            },
        },
    }


def test_registration_declares_integration_types_and_contexts():
    posted: list[dict] = []

    def opener(request, timeout=0):
        posted.append(json.loads(request.data.decode("utf-8")))

        class Resp:
            def read(self):
                return json.dumps({"name": posted[-1]["name"]}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    register_opt_in_commands(token="tok", application_id="app", opener=opener)
    assert posted
    for command in posted:
        assert command["integration_types"] == INTEGRATION_TYPES == [0, 1]
        assert command["contexts"] == INSTALL_CONTEXTS == [0, 1, 2]
    assert [c for c in posted if c["type"] == COMMAND_TYPE_MESSAGE]
    for command in OPT_IN_COMMANDS:
        assert command["integration_types"] == [GUILD_INSTALL, USER_INSTALL]


def test_user_install_context_detection():
    assert is_user_install_context(_outside_ask()) is True
    # Guild install present: our own server.
    assert (
        is_user_install_context(
            {"guild_id": "g1", "authorizing_integration_owners": {str(GUILD_INSTALL): "g1"}}
        )
        is False
    )
    # Group DM / someone else's DM.
    assert is_user_install_context({"context": 2}) is True
    assert is_user_install_context({"channel_id": "ch-1"}) is False


def test_outside_ask_uses_the_bound_home_channel_and_links_the_thread(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _store_with_home(ws)
    seen: list[tuple[str, str, str]] = []
    reply = handle_interaction_payload(
        _outside_ask(),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert seen == [("ch-home", "cook this", "owner-1")]
    content = reply["data"]["content"]
    assert reply["data"]["flags"] == 64
    assert "https://discord.com/channels/guild-home/ch-home" in content


def test_outside_ask_fails_closed_for_a_non_operator(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _store_with_home(ws)
    seen: list[tuple[str, str, str]] = []
    reply = handle_interaction_payload(
        _outside_ask(author_id="stranger-9"),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert seen == []
    assert "denied" in reply["data"]["content"].lower()


def test_outside_ask_fails_closed_on_an_unpaired_desk(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _store_with_home(ws, operator="")
    seen: list[tuple[str, str, str]] = []
    reply = handle_interaction_payload(
        _outside_ask(),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    # Empty allowlist is open on the desk, but never from outside the server.
    assert seen == []
    assert "denied" in reply["data"]["content"].lower()


def test_outside_power_slash_fails_closed_on_an_unpaired_desk(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _store_with_home(ws, operator="")
    payload = _outside_ask()
    payload["data"] = {"name": "on"}
    reply = handle_interaction_payload(payload, workspace=ws, roots=[ws])
    assert "denied" in reply["data"]["content"].lower()
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    # Nothing was armed and no owner was seeded from outside the server.
    assert store.get_host_control("ch-stranger") is None
    assert store.list_operators() == []
    store.close()


def test_outside_message_command_sends_to_home_and_fails_closed(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _store_with_home(ws)
    seen: list[tuple[str, str, str]] = []
    reply = handle_interaction_payload(
        _outside_message(),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    channel, text, requester = seen[0]
    assert channel == "ch-home"
    assert requester == "owner-1"
    assert text.startswith("from dana in <#ch-stranger>")
    assert "https://discord.com/channels/guild-home/ch-home" in reply["data"]["content"]

    denied = handle_interaction_payload(
        _outside_message(author_id="stranger-9"),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert len(seen) == 1
    assert "denied" in denied["data"]["content"].lower()


def test_outside_ask_without_a_bound_home_is_honest(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.add_operator("owner-1", role="owner")
    store.close()
    reply = handle_interaction_payload(
        _outside_ask(), workspace=ws, roots=[ws], on_ask=lambda *a: None
    )
    assert "no bound channel" in reply["data"]["content"].lower()


def test_outside_interaction_answers_on_the_webhook_not_channel_rest(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _store_with_home(ws)
    urls: list[str] = []

    def opener(request, timeout=0):
        urls.append(request.full_url)

        class Resp:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    label = route_gateway_interaction(
        _outside_ask(),
        workspace=ws,
        roots=[ws],
        interactions="gateway",
        opener=opener,
        on_ask=lambda *a: None,
    )
    assert label == "slash:ask"
    assert urls == ["https://discord.com/api/v10/interactions/ix-ui/tok-ui/callback"]
    assert not [url for url in urls if "/channels/" in url]
