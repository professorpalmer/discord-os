"""Forwarded messages: the payload lives in message_snapshots, not content."""

from __future__ import annotations

from agent_discord.discord.rest import (
    FORWARD_PROVENANCE,
    MESSAGE_REFERENCE_FORWARD,
    message_from_rest_payload,
)


def _forward(content: str = "", *, snapshot: dict | None = None, ref_type: int | None = MESSAGE_REFERENCE_FORWARD):
    reference: dict = {"message_id": "msg-source", "channel_id": "ch-source"}
    if ref_type is not None:
        reference["type"] = ref_type
    return {
        "id": "msg-1",
        "channel_id": "ch-home",
        "content": content,
        "author": {"id": "human-1", "username": "cary"},
        "attachments": [],
        "message_reference": reference,
        "message_snapshots": [
            {
                "message": snapshot
                if snapshot is not None
                else {
                    "content": "the original ask",
                    "attachments": [],
                    "embeds": [],
                }
            }
        ],
    }


def test_forward_snapshot_content_lands_in_the_intake():
    msg = message_from_rest_payload(_forward(), channel_id="ch-home")
    assert msg.content.startswith(FORWARD_PROVENANCE)
    assert "the original ask" in msg.content
    assert msg.metadata["forwarded"] is True


def test_forward_keeps_the_senders_own_comment_first():
    msg = message_from_rest_payload(_forward("look at this"), channel_id="ch-home")
    lines = [line for line in msg.content.splitlines() if line.strip()]
    assert lines[0] == "look at this"
    assert lines[1] == FORWARD_PROVENANCE
    assert lines[2] == "the original ask"


def test_forward_merges_snapshot_attachments_and_embeds():
    msg = message_from_rest_payload(
        _forward(
            snapshot={
                "content": "crash log attached",
                "attachments": [
                    {"id": "att-1", "filename": "trace.txt", "size": 12},
                    {"id": "att-2", "filename": "shot.png", "size": 34},
                ],
                "embeds": [{"title": "gist"}],
            }
        ),
        channel_id="ch-home",
    )
    assert [a.filename for a in msg.attachments] == ["trace.txt", "shot.png"]
    assert [a.attachment_id for a in msg.attachments] == ["att-1", "att-2"]
    assert msg.metadata["embeds"] == [{"title": "gist"}]


def test_forward_does_not_duplicate_an_attachment_already_on_the_outer_message():
    raw = _forward(
        snapshot={
            "content": "same file",
            "attachments": [{"id": "att-1", "filename": "trace.txt", "size": 12}],
        }
    )
    raw["attachments"] = [{"id": "att-1", "filename": "trace.txt", "size": 12}]
    msg = message_from_rest_payload(raw, channel_id="ch-home")
    assert [a.attachment_id for a in msg.attachments] == ["att-1"]


def test_a_reply_is_not_a_forward():
    # message_reference.type 0 is DEFAULT (a reply) — no snapshot merge.
    raw = _forward("a reply", ref_type=0)
    msg = message_from_rest_payload(raw, channel_id="ch-home")
    assert msg.content == "a reply"
    assert "forwarded" not in msg.metadata


def test_plain_message_is_untouched():
    msg = message_from_rest_payload(
        {
            "id": "msg-2",
            "channel_id": "ch-home",
            "content": "hello",
            "author": {"id": "human-1"},
            "attachments": [],
        },
        channel_id="ch-home",
    )
    assert msg.content == "hello"
    assert "forwarded" not in msg.metadata
