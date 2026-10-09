"""'Send to Discord OS' message context menu (application command type 3)."""

from __future__ import annotations

from pathlib import Path

from agent_discord.discord.interactions import (
    COMMAND_TYPE_MESSAGE,
    INTERACTION_APPLICATION_COMMAND,
    MESSAGE_ASK_COMMAND,
    MESSAGE_COMMAND_NAME,
    OPT_IN_COMMANDS,
    handle_interaction_payload,
)
from agent_discord.persistence.sqlite import SQLiteStore


def _message_payload(
    *,
    content: str = "look at this stack trace",
    attachments: list[dict] | None = None,
    author_id: str = "human-1",
    channel_id: str = "ch-home",
):
    return {
        "type": INTERACTION_APPLICATION_COMMAND,
        "id": "ix-msg",
        "token": "tok-msg",
        "channel_id": channel_id,
        "member": {"user": {"id": author_id}},
        "data": {
            "name": MESSAGE_COMMAND_NAME,
            "type": COMMAND_TYPE_MESSAGE,
            "target_id": "msg-9",
            "resolved": {
                "messages": {
                    "msg-9": {
                        "id": "msg-9",
                        "channel_id": "ch-source",
                        "content": content,
                        "author": {"id": "author-3", "global_name": "Dana"},
                        "attachments": attachments or [],
                    }
                }
            },
        },
    }


def test_message_command_is_registered_as_type_three():
    assert MESSAGE_ASK_COMMAND in OPT_IN_COMMANDS
    assert MESSAGE_ASK_COMMAND["type"] == COMMAND_TYPE_MESSAGE
    assert MESSAGE_ASK_COMMAND["name"] == MESSAGE_COMMAND_NAME
    assert "options" not in MESSAGE_ASK_COMMAND


def test_message_command_builds_the_ask_from_resolved_message(tmp_path: Path):
    seen: list[tuple[str, str, str]] = []
    reply = handle_interaction_payload(
        _message_payload(
            attachments=[
                {"filename": "trace.txt", "url": "https://cdn.example/trace.txt"},
                {"filename": "shot.png", "proxy_url": "https://cdn.example/shot.png"},
            ]
        ),
        workspace=tmp_path,
        roots=[tmp_path],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    channel, text, requester = seen[0]
    assert channel == "ch-home"
    assert requester == "human-1"
    assert text.splitlines()[0] == "from Dana in <#ch-source>"
    assert "look at this stack trace" in text
    assert "- trace.txt https://cdn.example/trace.txt" in text
    assert "- shot.png https://cdn.example/shot.png" in text
    assert reply["data"]["flags"] == 64
    assert reply["data"]["content"].startswith("On it.")


def test_message_command_accepts_attachment_only_message(tmp_path: Path):
    seen: list[tuple[str, str, str]] = []
    handle_interaction_payload(
        _message_payload(
            content="",
            attachments=[{"filename": "log.txt", "url": "https://cdn.example/log.txt"}],
        ),
        workspace=tmp_path,
        roots=[tmp_path],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert "log.txt" in seen[0][1]


def test_message_command_refuses_empty_and_unresolved(tmp_path: Path):
    empty = handle_interaction_payload(
        _message_payload(content="", attachments=[]),
        workspace=tmp_path,
        roots=[tmp_path],
        on_ask=lambda *a: None,
    )
    assert "no content" in empty["data"]["content"].lower()

    payload = _message_payload()
    payload["data"]["resolved"] = {}
    missing = handle_interaction_payload(
        payload,
        workspace=tmp_path,
        roots=[tmp_path],
        on_ask=lambda *a: None,
    )
    assert "could not read" in missing["data"]["content"].lower()


def test_message_command_is_operator_only(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.add_operator("owner-1", role="owner")
    store.close()

    seen: list[tuple[str, str, str]] = []
    denied = handle_interaction_payload(
        _message_payload(author_id="stranger-9"),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert seen == []
    assert "denied" in denied["data"]["content"].lower()

    handle_interaction_payload(
        _message_payload(author_id="owner-1"),
        workspace=ws,
        roots=[ws],
        on_ask=lambda channel, text, requester: seen.append((channel, text, requester)),
    )
    assert seen and seen[0][2] == "owner-1"
