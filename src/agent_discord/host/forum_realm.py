"""Forum-as-realm experiment (Discord-half EXTRAS).

Scoped: bind a Discord **forum** channel (type 15) as a normal realm checkout
and route **new forum posts** into the existing JobPool with
``thread_id = post thread``. Not a second job system. Not forum-tags as
ticket types. Fail closed with spoken Need when the channel is not a forum
or the bot cannot list threads (missing perms).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from agent_discord.host.realms import binding_metadata

# Discord channel type: GUILD_FORUM
GUILD_FORUM = 15

FORUM_META_KIND = "forum"
FORUM_META_FLAG = "forum"

# Spoken Need — phone-visible, fail closed (no silent text-channel fallback).
FORUM_NEED_NOT_FORUM = (
    "Need: forum-as-realm — channel is not a Discord forum (type 15). "
    "Bind a forum channel, or omit --forum for a text realm."
)
FORUM_NEED_MISSING_PERMS = (
    "Need: forum-as-realm — missing View Channel / Read Message History / "
    "Send Messages in Threads (cannot list active threads)."
)
FORUM_NEED_FETCH = (
    "Need: forum-as-realm — could not fetch channel (token/ACL). Fail closed."
)


class ForumRealmError(ValueError):
    """Forum bind / intake refused. ``spoken`` is the phone Need line."""

    def __init__(self, spoken: str):
        super().__init__(spoken)
        self.spoken = spoken


@dataclass(frozen=True)
class ForumChannelInfo:
    channel_id: str
    channel_type: int
    name: str = ""
    guild_id: str = ""


def spoken_forum_need(reason: str) -> str:
    why = (reason or "refused").strip() or "refused"
    if why.startswith("Need:"):
        return why
    return f"Need: forum-as-realm — {why}"


def is_forum_binding(row_or_meta: Optional[Mapping[str, Any]]) -> bool:
    """True when binding metadata marks this channel as a forum realm."""

    if not row_or_meta:
        return False
    meta = (
        binding_metadata(row_or_meta)
        if "metadata_json" in row_or_meta or "metadata" in row_or_meta
        else dict(row_or_meta)
    )
    if bool(meta.get(FORUM_META_FLAG)):
        return True
    return str(meta.get("kind") or "").strip().lower() == FORUM_META_KIND


def forum_binding_updates() -> dict[str, Any]:
    return {FORUM_META_FLAG: True, "kind": FORUM_META_KIND}


def clear_forum_binding_updates() -> dict[str, Any]:
    """Remove forum markers (text realm)."""

    return {FORUM_META_FLAG: False, "kind": ""}


def channel_is_forum(payload: Mapping[str, Any]) -> bool:
    try:
        return int(payload.get("type") or 0) == GUILD_FORUM
    except (TypeError, ValueError):
        return False


def parse_channel_info(payload: Mapping[str, Any]) -> ForumChannelInfo:
    return ForumChannelInfo(
        channel_id=str(payload.get("id") or "").strip(),
        channel_type=int(payload.get("type") or 0),
        name=str(payload.get("name") or "").strip(),
        guild_id=str(payload.get("guild_id") or "").strip(),
    )


def assert_forum_channel(payload: Mapping[str, Any]) -> ForumChannelInfo:
    """Fail closed unless payload is GUILD_FORUM."""

    info = parse_channel_info(payload)
    if info.channel_type != GUILD_FORUM:
        raise ForumRealmError(FORUM_NEED_NOT_FORUM)
    if not info.channel_id:
        raise ForumRealmError(spoken_forum_need("channel id missing"))
    return info


def mark_forum_binding(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
) -> None:
    writer = getattr(store, "merge_binding_metadata", None)
    if callable(writer):
        writer(workspace_id, channel_id, forum_binding_updates())


def unmark_forum_binding(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
) -> None:
    writer = getattr(store, "merge_binding_metadata", None)
    if callable(writer):
        writer(workspace_id, channel_id, clear_forum_binding_updates())


def binding_is_forum_realm(
    store: Any,
    channel_id: str,
    *,
    workspace_id: str = "default",
) -> bool:
    reader = getattr(store, "get_binding", None)
    if not callable(reader):
        return False
    try:
        return is_forum_binding(reader(workspace_id, channel_id))
    except Exception:
        return False


def remember_forum_thread_parent(
    store: Any,
    *,
    workspace_id: str,
    thread_id: str,
    parent_channel_id: str,
) -> None:
    """Persist thread→forum parent so listen can resolve realm before first task."""

    tid = (thread_id or "").strip()
    parent = (parent_channel_id or "").strip()
    if not tid or not parent:
        return
    writer = getattr(store, "merge_binding_metadata", None)
    if not callable(writer):
        return
    writer(
        workspace_id,
        tid,
        {
            "parent_channel_id": parent,
            "forum_post": True,
            "kind": "forum_post",
        },
    )


def parent_from_forum_thread_binding(
    store: Any,
    thread_id: str,
    *,
    workspace_id: str = "default",
) -> str:
    tid = (thread_id or "").strip()
    if not tid:
        return ""
    # Prefer explicit workspace, then any binding row for this thread id.
    reader = getattr(store, "get_binding", None)
    if callable(reader):
        try:
            meta = binding_metadata(reader(workspace_id, tid))
            parent = str(meta.get("parent_channel_id") or "").strip()
            if parent:
                return parent
        except Exception:
            pass
    lister = getattr(store, "list_bindings", None)
    if callable(lister):
        for wid in (workspace_id, ""):
            try:
                for row in lister(wid) or ():
                    if str(row.get("channel_id") or "").strip() != tid:
                        continue
                    meta = binding_metadata(row)
                    parent = str(meta.get("parent_channel_id") or "").strip()
                    if parent:
                        return parent
            except Exception:
                continue
    conn = getattr(store, "_connection", None)
    if callable(conn):
        try:
            row = conn().execute(
                """
                SELECT metadata_json FROM workspace_bindings
                WHERE channel_id=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (tid,),
            ).fetchone()
            if row:
                raw = row["metadata_json"] if "metadata_json" in row.keys() else row[0]
                meta = binding_metadata({"metadata_json": raw})
                return str(meta.get("parent_channel_id") or "").strip()
        except Exception:
            pass
    return ""


def list_forum_realm_channel_ids(
    store: Any,
    *,
    workspace_id: str = "default",
    listen_ids: Sequence[str] = (),
) -> tuple[str, ...]:
    """Forum-marked bindings that appear in the current listen set."""

    out: list[str] = []
    seen: set[str] = set()
    for raw in listen_ids or ():
        cid = str(raw or "").strip()
        if not cid or cid in seen:
            continue
        if binding_is_forum_realm(store, cid, workspace_id=workspace_id):
            out.append(cid)
            seen.add(cid)
    return tuple(out)


def discover_forum_post_threads(
    *,
    token: str,
    forum_channel_id: str,
    opener: Any = None,
) -> tuple[str, ...]:
    """Active public threads under a forum. Raises ForumRealmError on ACL miss."""

    from agent_discord.discord.errors import ToolInvocationError
    from agent_discord.discord.rest import list_active_threads
    from urllib.error import HTTPError

    forum = (forum_channel_id or "").strip()
    if not forum:
        return ()
    try:
        threads = list_active_threads(
            token=token, channel_id=forum, opener=opener
        )
    except HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code in {401, 403}:
            raise ForumRealmError(FORUM_NEED_MISSING_PERMS) from exc
        raise ForumRealmError(
            spoken_forum_need(f"list threads failed HTTP {code or '?'}")
        ) from exc
    except ToolInvocationError as exc:
        msg = str(exc).lower()
        if "403" in msg or "401" in msg or "missing" in msg or "perm" in msg:
            raise ForumRealmError(FORUM_NEED_MISSING_PERMS) from exc
        raise ForumRealmError(spoken_forum_need(str(exc))) from exc
    except ForumRealmError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ForumRealmError(spoken_forum_need(str(exc))) from exc

    ids: list[str] = []
    seen: set[str] = set()
    for item in threads:
        tid = str(item.get("id") or "").strip()
        if not tid or tid in seen:
            continue
        # Prefer threads whose parent is this forum when parent_id present.
        parent = str(item.get("parent_id") or "").strip()
        if parent and parent != forum:
            continue
        ids.append(tid)
        seen.add(tid)
    return tuple(ids)


def validate_and_mark_forum_bind(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    token: str,
    require_forum: bool = False,
    opener: Any = None,
) -> dict[str, Any]:
    """Fetch channel; mark forum realm when type 15 (+ thread list OK).

    ``require_forum=True`` (CLI ``--forum``): fail closed if not a forum.
    ``require_forum=False``: auto-mark when Discord says forum; leave text
    realms unmarked. Missing perms on a forum → ForumRealmError (Need).
    """

    from agent_discord.discord.errors import ToolInvocationError
    from agent_discord.discord.rest import fetch_channel, list_active_threads
    from urllib.error import HTTPError

    cid = (channel_id or "").strip()
    if not cid:
        raise ForumRealmError(spoken_forum_need("channel id missing"))
    if not (token or "").strip():
        if require_forum:
            raise ForumRealmError(FORUM_NEED_FETCH)
        return {"forum": False, "skipped": "no token"}

    try:
        raw = fetch_channel(token=token, channel_id=cid, opener=opener)
    except HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if require_forum or code in {401, 403}:
            raise ForumRealmError(
                FORUM_NEED_MISSING_PERMS if code in {401, 403} else FORUM_NEED_FETCH
            ) from exc
        return {"forum": False, "skipped": f"fetch HTTP {code}"}
    except ToolInvocationError as exc:
        if require_forum:
            raise ForumRealmError(FORUM_NEED_FETCH) from exc
        return {"forum": False, "skipped": str(exc)}
    except Exception as exc:  # noqa: BLE001
        if require_forum:
            raise ForumRealmError(FORUM_NEED_FETCH) from exc
        return {"forum": False, "skipped": str(exc)}

    if not isinstance(raw, dict):
        if require_forum:
            raise ForumRealmError(FORUM_NEED_FETCH)
        return {"forum": False, "skipped": "bad payload"}

    info = parse_channel_info(raw)
    if info.channel_type != GUILD_FORUM:
        if require_forum:
            raise ForumRealmError(FORUM_NEED_NOT_FORUM)
        # Text/voice/etc. — ensure forum flag cleared if previously set.
        if binding_is_forum_realm(store, cid, workspace_id=workspace_id):
            unmark_forum_binding(store, workspace_id=workspace_id, channel_id=cid)
        return {"forum": False, "type": info.channel_type}

    # Forum: prove we can list threads (perm probe).
    try:
        list_active_threads(token=token, channel_id=cid, opener=opener)
    except HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code in {401, 403}:
            raise ForumRealmError(FORUM_NEED_MISSING_PERMS) from exc
        raise ForumRealmError(
            spoken_forum_need(f"list threads failed HTTP {code or '?'}")
        ) from exc
    except ToolInvocationError as exc:
        raise ForumRealmError(FORUM_NEED_MISSING_PERMS) from exc

    mark_forum_binding(store, workspace_id=workspace_id, channel_id=cid)
    return {
        "forum": True,
        "type": GUILD_FORUM,
        "name": info.name,
        "guild_id": info.guild_id,
    }


def collect_forum_thread_dests(
    store: Any,
    *,
    workspace_id: str,
    listen_ids: Sequence[str],
    token: str,
    opener: Any = None,
    on_need: Any = None,
) -> tuple[str, ...]:
    """Discover active forum posts for forum-bound listen ids; remember parents.

    ACL failures invoke ``on_need(forum_id, spoken)`` when provided and skip
    that forum (fail closed for intake — no silent invent).
    """

    out: list[str] = []
    seen: set[str] = set()
    for forum_id in list_forum_realm_channel_ids(
        store, workspace_id=workspace_id, listen_ids=listen_ids
    ):
        try:
            threads = discover_forum_post_threads(
                token=token, forum_channel_id=forum_id, opener=opener
            )
        except ForumRealmError as exc:
            if callable(on_need):
                try:
                    on_need(forum_id, exc.spoken)
                except Exception:
                    pass
            continue
        for tid in threads:
            if tid in seen:
                continue
            remember_forum_thread_parent(
                store,
                workspace_id=workspace_id,
                thread_id=tid,
                parent_channel_id=forum_id,
            )
            out.append(tid)
            seen.add(tid)
    return tuple(out)


__all__ = [
    "FORUM_META_FLAG",
    "FORUM_META_KIND",
    "FORUM_NEED_FETCH",
    "FORUM_NEED_MISSING_PERMS",
    "FORUM_NEED_NOT_FORUM",
    "ForumChannelInfo",
    "ForumRealmError",
    "GUILD_FORUM",
    "assert_forum_channel",
    "binding_is_forum_realm",
    "channel_is_forum",
    "clear_forum_binding_updates",
    "collect_forum_thread_dests",
    "discover_forum_post_threads",
    "forum_binding_updates",
    "is_forum_binding",
    "list_forum_realm_channel_ids",
    "mark_forum_binding",
    "parent_from_forum_thread_binding",
    "parse_channel_info",
    "remember_forum_thread_parent",
    "spoken_forum_need",
    "unmark_forum_binding",
    "validate_and_mark_forum_bind",
]
