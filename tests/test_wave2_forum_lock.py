"""Forum deepen: never mutate available_tags."""

from __future__ import annotations

import pytest

from agent_discord.discord.errors import ToolInvocationError
from agent_discord.discord.rest import modify_channel
from agent_discord.host.forum_realm import (
    cache_status_tags_from_forum_payload,
    refresh_status_tags_from_discord,
)
from agent_discord.persistence.sqlite import SQLiteStore


def test_modify_channel_refuses_available_tags():
    with pytest.raises(ToolInvocationError, match="available_tags"):
        modify_channel(
            token="x",
            channel_id="1",
            payload={"available_tags": [{"name": "done"}]},
        )


def test_cache_status_tags_soft_empty(tmp_path):
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.initialize()
    updates = cache_status_tags_from_forum_payload(
        store,
        workspace_id="default",
        channel_id="forum1",
        payload={"type": 15, "available_tags": []},
    )
    assert updates["tags_as_tickets"] is False
    assert updates["status_tag_ids"] == {}
    store.close()


def test_refresh_status_tags_from_fetch(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.initialize()
    calls = []

    def fake_fetch(*, token, channel_id, opener=None):
        calls.append(channel_id)
        return {
            "id": channel_id,
            "type": 15,
            "available_tags": [
                {"id": "t1", "name": "done"},
                {"id": "t2", "name": "running"},
            ],
        }

    import agent_discord.discord.rest as rest

    monkeypatch.setattr(rest, "fetch_channel", fake_fetch)
    out = refresh_status_tags_from_discord(
        store, channel_id="forum1", token="tok"
    )
    assert out["created_available_tags"] is False
    assert out["tags_as_tickets"] is True
    assert calls == ["forum1"]
    store.close()
