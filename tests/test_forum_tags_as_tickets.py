"""Forum tags-as-tickets — status ↔ applied_tags, fail closed, no invented guild tags."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from agent_discord.contracts import TaskStatus
from agent_discord.host.forum_realm import (
    FORUM_NEED_TAGS_MISSING,
    FORUM_NEED_TAGS_PERMS,
    ForumRealmError,
    GUILD_FORUM,
    TAGS_AS_TICKETS_FLAG,
    apply_thread_status_tags,
    build_status_tag_id_map,
    cache_status_tags_from_forum_payload,
    collect_forum_thread_dests,
    mark_forum_binding,
    maybe_sync_forum_ticket_tags,
    merge_applied_tags_for_status,
    parse_applied_tag_ids,
    parse_available_tags,
    resolve_status_from_applied_tags,
    status_value,
    tags_as_tickets_enabled,
    validate_and_mark_forum_bind,
)
from agent_discord.persistence.sqlite import SQLiteStore


def test_parse_and_map_status_tags() -> None:
    available = parse_available_tags(
        {
            "available_tags": [
                {"id": "t-q", "name": "Queued"},
                {"id": "t-r", "name": "In Progress"},
                {"id": "t-d", "name": "Done"},
                {"id": "t-f", "name": "Failed"},
                {"id": "t-c", "name": "Cancelled"},
                {"id": "t-x", "name": "priority"},
            ]
        }
    )
    assert [t.name for t in available] == [
        "Queued",
        "In Progress",
        "Done",
        "Failed",
        "Cancelled",
        "priority",
    ]
    smap = build_status_tag_id_map(available)
    assert smap["pending"] == "t-q"
    assert smap["running"] == "t-r"
    assert smap["completed"] == "t-d"
    assert smap["failed"] == "t-f"
    assert smap["cancelled"] == "t-c"
    assert status_value(TaskStatus.PROGRESS) == "running"
    assert (
        resolve_status_from_applied_tags(("t-x", "t-r"), smap) == "running"
    )


def test_merge_preserves_non_status_tags() -> None:
    smap = {
        "pending": "t-q",
        "running": "t-r",
        "completed": "t-d",
        "failed": "t-f",
        "cancelled": "t-c",
    }
    merged = merge_applied_tags_for_status(
        ("t-q", "t-prio", "t-area"),
        status=TaskStatus.COMPLETED,
        status_tag_ids=smap,
    )
    assert merged[0] == "t-d"
    assert "t-prio" in merged and "t-area" in merged
    assert "t-q" not in merged


def test_validate_bind_caches_tags_as_tickets(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "tags.sqlite3")
    store.initialize()

    def opener(request, timeout=0):
        path = request.full_url

        class Resp:
            def read(self):
                if "/threads/active" in path:
                    return json.dumps({"threads": []}).encode()
                return json.dumps(
                    {
                        "id": "forum",
                        "type": GUILD_FORUM,
                        "name": "tickets",
                        "guild_id": "g",
                        "available_tags": [
                            {"id": "1", "name": "queued"},
                            {"id": "2", "name": "running"},
                            {"id": "3", "name": "done"},
                        ],
                    }
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
    assert meta[TAGS_AS_TICKETS_FLAG] is True
    assert meta["status_tag_ids"]["pending"] == "1"
    assert meta["status_tag_ids"]["completed"] == "3"
    row = store.get_binding("ws", "forum")
    assert tags_as_tickets_enabled(row)
    store.close()


def test_collect_remembers_applied_tags(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "c.sqlite3")
    store.initialize()
    mark_forum_binding(store, workspace_id="ws", channel_id="forum")
    cache_status_tags_from_forum_payload(
        store,
        workspace_id="ws",
        channel_id="forum",
        payload={
            "available_tags": [
                {"id": "tq", "name": "queued"},
                {"id": "tr", "name": "running"},
            ]
        },
    )

    def opener(request, timeout=0):
        class Resp:
            def read(self):
                return json.dumps(
                    {
                        "threads": [
                            {
                                "id": "post-1",
                                "parent_id": "forum",
                                "applied_tags": ["tq", "extra"],
                            }
                        ]
                    }
                ).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    dests = collect_forum_thread_dests(
        store,
        workspace_id="ws",
        listen_ids=("forum",),
        token="tok",
        opener=opener,
    )
    assert dests == ("post-1",)
    from agent_discord.host.realms import binding_metadata

    meta = binding_metadata(store.get_binding("ws", "post-1"))
    assert meta["applied_tags"] == ["tq", "extra"]
    store.close()


def test_apply_thread_status_tags_ok_and_acl(tmp_path: Path) -> None:
    calls: list[tuple[str, bytes | None]] = []

    def opener(request, timeout=0):
        body = request.data
        calls.append((request.full_url, body))

        class Resp:
            def read(self):
                return json.dumps(
                    {"id": "post-1", "applied_tags": ["tr"]}
                ).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    smap = {"pending": "tq", "running": "tr", "completed": "td"}
    result = apply_thread_status_tags(
        token="tok",
        thread_id="post-1",
        status=TaskStatus.RUNNING,
        status_tag_ids=smap,
        current_applied=("tq",),
        opener=opener,
    )
    assert result["ok"] is True
    assert result["applied_tags"] == ["tr"]
    assert calls and "post-1" in calls[0][0]
    payload = json.loads(calls[0][1].decode())
    assert payload["applied_tags"] == ["tr"]

    def deny(request, timeout=0):
        raise HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)

    with pytest.raises(ForumRealmError) as exc:
        apply_thread_status_tags(
            token="tok",
            thread_id="post-1",
            status="completed",
            status_tag_ids=smap,
            opener=deny,
        )
    assert FORUM_NEED_TAGS_PERMS in exc.value.spoken or "Need:" in exc.value.spoken

    with pytest.raises(ForumRealmError):
        apply_thread_status_tags(
            token="tok",
            thread_id="post-1",
            status="failed",
            status_tag_ids=smap,
            require_tag=True,
            opener=opener,
        )


def test_maybe_sync_soft_skip_and_sync(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.sqlite3")
    store.initialize()
    # Not a forum → skip
    assert maybe_sync_forum_ticket_tags(
        store,
        token="tok",
        workspace_id="ws",
        channel_id="text",
        thread_id="th",
        status="running",
    )["skipped"] == "not forum realm"

    mark_forum_binding(store, workspace_id="ws", channel_id="forum")
    # Forum without status tags → soft skip
    assert maybe_sync_forum_ticket_tags(
        store,
        token="tok",
        workspace_id="ws",
        channel_id="forum",
        thread_id="post",
        status="running",
    )["skipped"] == "tags-as-tickets off"

    cache_status_tags_from_forum_payload(
        store,
        workspace_id="ws",
        channel_id="forum",
        payload={
            "available_tags": [
                {"id": "tq", "name": "queued"},
                {"id": "tr", "name": "running"},
                {"id": "td", "name": "done"},
            ]
        },
    )

    def opener(request, timeout=0):
        class Resp:
            def read(self):
                body = json.loads(request.data.decode())
                return json.dumps(
                    {"id": "post", "applied_tags": body["applied_tags"]}
                ).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    out = maybe_sync_forum_ticket_tags(
        store,
        token="tok",
        workspace_id="ws",
        channel_id="forum",
        thread_id="post",
        status=TaskStatus.COMPLETED,
        opener=opener,
    )
    assert out.get("ok") is True
    assert out["applied_tags"] == ["td"]

    needs: list[str] = []
    with pytest.raises(ForumRealmError):
        maybe_sync_forum_ticket_tags(
            store,
            token="tok",
            workspace_id="ws",
            channel_id="forum",
            thread_id="post",
            status="failed",
            require_tag=True,
            opener=opener,
            on_need=needs.append,
        )
    assert needs and FORUM_NEED_TAGS_MISSING.split("—")[0].strip() in needs[0]
    store.close()


def test_parse_applied_tag_ids_cap() -> None:
    ids = parse_applied_tag_ids(
        {"applied_tags": ["a", "b", "c", "d", "e", "f", ""]}
    )
    assert ids == ("a", "b", "c", "d", "e")
