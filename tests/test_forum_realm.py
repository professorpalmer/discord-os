"""Forum-as-realm experiment — bind fail-closed, JobPool reuse, not a second system."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from agent_discord.host.forum_realm import (
    FORUM_NEED_MISSING_PERMS,
    FORUM_NEED_NOT_FORUM,
    ForumRealmError,
    GUILD_FORUM,
    assert_forum_channel,
    binding_is_forum_realm,
    collect_forum_thread_dests,
    discover_forum_post_threads,
    is_forum_binding,
    mark_forum_binding,
    parent_from_forum_thread_binding,
    remember_forum_thread_parent,
    validate_and_mark_forum_bind,
)
from agent_discord.persistence.sqlite import SQLiteStore


def test_assert_forum_channel_fail_closed() -> None:
    info = assert_forum_channel({"id": "f1", "type": GUILD_FORUM, "name": "tickets"})
    assert info.channel_id == "f1"
    with pytest.raises(ForumRealmError) as exc:
        assert_forum_channel({"id": "t1", "type": 0})
    assert "Need:" in exc.value.spoken
    assert "forum" in exc.value.spoken.lower()


def test_mark_and_detect_forum_binding(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "f.sqlite3")
    store.initialize()
    mark_forum_binding(store, workspace_id="ws", channel_id="forum-1")
    assert binding_is_forum_realm(store, "forum-1", workspace_id="ws")
    row = store.get_binding("ws", "forum-1")
    assert is_forum_binding(row)
    store.close()


def test_validate_require_forum_not_forum(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "v.sqlite3")
    store.initialize()

    def opener(request, timeout=0):
        class Resp:
            def read(self):
                return json.dumps({"id": "ch", "type": 0, "name": "general"}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    with pytest.raises(ForumRealmError) as exc:
        validate_and_mark_forum_bind(
            store,
            workspace_id="ws",
            channel_id="ch",
            token="tok",
            require_forum=True,
            opener=opener,
        )
    assert FORUM_NEED_NOT_FORUM in exc.value.spoken or "not a Discord forum" in exc.value.spoken
    assert not binding_is_forum_realm(store, "ch", workspace_id="ws")
    store.close()


def test_validate_forum_ok_and_perm_deny(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "p.sqlite3")
    store.initialize()
    calls: list[str] = []

    def opener(request, timeout=0):
        path = request.full_url
        calls.append(path)

        class Resp:
            def read(self):
                if "/threads/active" in path:
                    return json.dumps({"threads": [{"id": "th1", "parent_id": "forum"}]}).encode()
                return json.dumps(
                    {"id": "forum", "type": GUILD_FORUM, "name": "jobs", "guild_id": "g"}
                ).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    meta = validate_and_mark_forum_bind(
        store,
        workspace_id="ws",
        channel_id="forum",
        token="tok",
        require_forum=True,
        opener=opener,
    )
    assert meta["forum"] is True
    assert binding_is_forum_realm(store, "forum", workspace_id="ws")

    def deny_opener(request, timeout=0):
        path = request.full_url
        if "/threads/active" in path:
            raise HTTPError(path, 403, "Forbidden", hdrs=None, fp=None)

        class Resp:
            def read(self):
                return json.dumps({"id": "forum2", "type": GUILD_FORUM}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    with pytest.raises(ForumRealmError) as exc:
        validate_and_mark_forum_bind(
            store,
            workspace_id="ws",
            channel_id="forum2",
            token="tok",
            require_forum=True,
            opener=deny_opener,
        )
    assert "Need:" in exc.value.spoken
    assert "perm" in exc.value.spoken.lower() or FORUM_NEED_MISSING_PERMS in exc.value.spoken
    store.close()


def test_discover_threads_and_parent_remember(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "d.sqlite3")
    store.initialize()
    mark_forum_binding(store, workspace_id="ws", channel_id="forum")

    def opener(request, timeout=0):
        class Resp:
            def read(self):
                return json.dumps(
                    {
                        "threads": [
                            {"id": "post-a", "parent_id": "forum"},
                            {"id": "post-b", "parent_id": "other"},
                            {"id": "post-c", "parent_id": "forum"},
                        ]
                    }
                ).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    ids = discover_forum_post_threads(
        token="tok", forum_channel_id="forum", opener=opener
    )
    assert ids == ("post-a", "post-c")

    dests = collect_forum_thread_dests(
        store,
        workspace_id="ws",
        listen_ids=("forum", "text-ch"),
        token="tok",
        opener=opener,
    )
    assert "post-a" in dests and "post-c" in dests
    assert parent_from_forum_thread_binding(store, "post-a", workspace_id="ws") == "forum"
    assert store.parent_channel_for_thread("post-a") == "forum"
    store.close()


def test_remember_parent_without_task(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "r.sqlite3")
    store.initialize()
    remember_forum_thread_parent(
        store, workspace_id="default", thread_id="th-new", parent_channel_id="forum-x"
    )
    assert store.parent_channel_for_thread("th-new") == "forum-x"
    store.close()
