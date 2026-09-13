"""Forum-as-realm + tags-as-tickets experiment (Discord-half EXTRAS).

Scoped: bind a Discord **forum** channel (type 15) as a normal realm checkout
and route **new forum posts** into the existing JobPool with
``thread_id = post thread``. Not a second job system.

Tags-as-tickets (deepen): when the forum already has ``available_tags`` whose
names match conventional JobPool statuses (queued / running / done / failed /
cancelled), map those tags onto ticket status and ``PATCH`` the post thread's
``applied_tags`` on status change. Does **not** invent guild tags or a fantasy
ticket UI. Soft-skip when no status tags exist; fail closed (spoken Need) on
ACL miss when sync is attempted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Union

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
FORUM_NEED_TAGS_PERMS = (
    "Need: tags-as-tickets — missing Manage Threads / tag apply "
    "(cannot PATCH applied_tags). Fail closed."
)
FORUM_NEED_TAGS_MISSING = (
    "Need: tags-as-tickets — forum has no available_tags matching "
    "queued/running/done/failed/cancelled. Add those tags on the forum, "
    "or omit tags-as-tickets."
)

# Binding metadata: tags-as-tickets deepen (still JobPool — not a second system).
TAGS_AS_TICKETS_FLAG = "tags_as_tickets"
STATUS_TAG_IDS_KEY = "status_tag_ids"
APPLIED_TAGS_KEY = "applied_tags"

# Discord hard limit on thread applied_tags.
MAX_APPLIED_TAGS = 5

# Conventional status tag names (normalized) → TaskStatus.value
# Match against forum available_tags.name; we never invent guild tags.
_STATUS_NAME_ALIASES: dict[str, str] = {
    "pending": "pending",
    "queued": "pending",
    "queue": "pending",
    "open": "pending",
    "new": "pending",
    "running": "running",
    "working": "running",
    "inprogress": "running",
    "in-progress": "running",
    "progress": "running",
    "live": "running",
    "completed": "completed",
    "complete": "completed",
    "done": "completed",
    "success": "completed",
    "failed": "failed",
    "fail": "failed",
    "error": "failed",
    "need": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


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


@dataclass(frozen=True)
class ForumTag:
    tag_id: str
    name: str
    moderated: bool = False


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
    applied_tags: Sequence[str] = (),
) -> None:
    """Persist thread→forum parent so listen can resolve realm before first task."""

    tid = (thread_id or "").strip()
    parent = (parent_channel_id or "").strip()
    if not tid or not parent:
        return
    writer = getattr(store, "merge_binding_metadata", None)
    if not callable(writer):
        return
    meta: dict[str, Any] = {
        "parent_channel_id": parent,
        "forum_post": True,
        "kind": "forum_post",
    }
    tags = [str(t).strip() for t in (applied_tags or ()) if str(t or "").strip()]
    if tags:
        meta[APPLIED_TAGS_KEY] = tags[:MAX_APPLIED_TAGS]
    writer(workspace_id, tid, meta)


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


def discover_forum_post_rows(
    *,
    token: str,
    forum_channel_id: str,
    opener: Any = None,
) -> tuple[dict[str, Any], ...]:
    """Active forum posts as thread payloads (id, parent_id, applied_tags)."""

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

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in threads:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("id") or "").strip()
        if not tid or tid in seen:
            continue
        parent = str(item.get("parent_id") or "").strip()
        if parent and parent != forum:
            continue
        rows.append(item)
        seen.add(tid)
    return tuple(rows)


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
    tag_meta = cache_status_tags_from_forum_payload(
        store,
        workspace_id=workspace_id,
        channel_id=cid,
        payload=raw,
    )
    return {
        "forum": True,
        "type": GUILD_FORUM,
        "name": info.name,
        "guild_id": info.guild_id,
        TAGS_AS_TICKETS_FLAG: bool(tag_meta.get(TAGS_AS_TICKETS_FLAG)),
        STATUS_TAG_IDS_KEY: dict(tag_meta.get(STATUS_TAG_IDS_KEY) or {}),
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
            rows = discover_forum_post_rows(
                token=token, forum_channel_id=forum_id, opener=opener
            )
        except ForumRealmError as exc:
            if callable(on_need):
                try:
                    on_need(forum_id, exc.spoken)
                except Exception:
                    pass
            continue
        for row in rows:
            tid = str(row.get("id") or "").strip()
            if not tid or tid in seen:
                continue
            remember_forum_thread_parent(
                store,
                workspace_id=workspace_id,
                thread_id=tid,
                parent_channel_id=forum_id,
                applied_tags=parse_applied_tag_ids(row),
            )
            out.append(tid)
            seen.add(tid)
    return tuple(out)



def normalize_tag_name(name: str) -> str:
    """Lowercase; collapse spaces/underscores to hyphens for alias lookup."""

    raw = str(name or "").strip().lower()
    if not raw:
        return ""
    out: list[str] = []
    prev_sep = False
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
            prev_sep = False
        elif ch in {" ", "_", "-", "/"}:
            if not prev_sep and out:
                out.append("-")
                prev_sep = True
        # else drop punctuation
    return "".join(out).strip("-")


def parse_available_tags(payload: Mapping[str, Any]) -> tuple[ForumTag, ...]:
    raw = payload.get("available_tags") if isinstance(payload, Mapping) else None
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[ForumTag] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        tag_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not tag_id or not name or tag_id in seen:
            continue
        out.append(
            ForumTag(
                tag_id=tag_id,
                name=name,
                moderated=bool(item.get("moderated")),
            )
        )
        seen.add(tag_id)
    return tuple(out)


def parse_applied_tag_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw = payload.get("applied_tags") if isinstance(payload, Mapping) else None
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = str(item or "").strip()
        if not tag or tag in seen:
            continue
        out.append(tag)
        seen.add(tag)
        if len(out) >= MAX_APPLIED_TAGS:
            break
    return tuple(out)


def status_value(status: Union[str, Any]) -> str:
    """Normalize TaskStatus | str → pending|running|completed|failed|cancelled."""

    if status is None:
        return ""
    raw = getattr(status, "value", None)
    text = str(raw if raw is not None else status).strip().lower()
    if text == "progress":
        return "running"
    if text in {"pending", "running", "completed", "failed", "cancelled"}:
        return text
    alias = _STATUS_NAME_ALIASES.get(normalize_tag_name(text))
    return alias or ""


def build_status_tag_id_map(
    available: Sequence[ForumTag],
) -> dict[str, str]:
    """Map TaskStatus.value → Discord tag id from available_tags names.

    First matching alias wins per status. Does not invent tags.
    """

    by_status: dict[str, str] = {}
    for tag in available or ():
        key = normalize_tag_name(tag.name)
        # try both hyphenated and compacted forms
        status = _STATUS_NAME_ALIASES.get(key)
        if status is None:
            status = _STATUS_NAME_ALIASES.get(key.replace("-", ""))
        if not status or status in by_status:
            continue
        by_status[status] = tag.tag_id
    return by_status


def resolve_status_from_applied_tags(
    applied_ids: Sequence[str],
    status_tag_ids: Mapping[str, str],
) -> str:
    """Best-effort status from applied tag ids (last matching status tag wins)."""

    if not applied_ids or not status_tag_ids:
        return ""
    inverse = {str(v): str(k) for k, v in status_tag_ids.items() if v}
    found = ""
    for tag_id in applied_ids:
        status = inverse.get(str(tag_id).strip())
        if status:
            found = status
    return found


def merge_applied_tags_for_status(
    current: Sequence[str],
    *,
    status: Union[str, Any],
    status_tag_ids: Mapping[str, str],
) -> tuple[str, ...]:
    """Replace any status tags with the one for ``status``; keep non-status tags.

    Caps at Discord's 5. If the target status has no mapped tag, returns current
    unchanged (soft — caller decides fail-closed).
    """

    wanted = status_value(status)
    target = str(status_tag_ids.get(wanted) or "").strip() if wanted else ""
    if not target:
        return tuple(str(x).strip() for x in (current or ()) if str(x or "").strip())[
            :MAX_APPLIED_TAGS
        ]

    status_id_set = {str(v).strip() for v in status_tag_ids.values() if str(v or "").strip()}
    kept: list[str] = []
    seen: set[str] = set()
    for raw in current or ():
        tag = str(raw or "").strip()
        if not tag or tag in seen or tag in status_id_set:
            continue
        kept.append(tag)
        seen.add(tag)

    out = [target, *[t for t in kept if t != target]]
    # Dedup preserve order, cap 5
    final: list[str] = []
    seen2: set[str] = set()
    for tag in out:
        if tag in seen2:
            continue
        final.append(tag)
        seen2.add(tag)
        if len(final) >= MAX_APPLIED_TAGS:
            break
    return tuple(final)


def tags_as_tickets_enabled(row_or_meta: Optional[Mapping[str, Any]]) -> bool:
    if not row_or_meta:
        return False
    meta = (
        binding_metadata(row_or_meta)
        if "metadata_json" in row_or_meta or "metadata" in row_or_meta
        else dict(row_or_meta)
    )
    if TAGS_AS_TICKETS_FLAG in meta:
        return bool(meta.get(TAGS_AS_TICKETS_FLAG))
    ids = meta.get(STATUS_TAG_IDS_KEY)
    return isinstance(ids, dict) and bool(ids)


def status_tag_ids_from_binding(
    store: Any,
    channel_id: str,
    *,
    workspace_id: str = "default",
) -> dict[str, str]:
    reader = getattr(store, "get_binding", None)
    if not callable(reader):
        return {}
    try:
        row = reader(workspace_id, channel_id)
    except Exception:
        return {}
    meta = binding_metadata(row) if row else {}
    raw = meta.get(STATUS_TAG_IDS_KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        status = status_value(key)
        tag = str(val or "").strip()
        if status and tag:
            out[status] = tag
    return out


def cache_status_tags_from_forum_payload(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Cache status↔tag id map from forum ``available_tags``. Soft when empty."""

    available = parse_available_tags(payload)
    status_map = build_status_tag_id_map(available)
    enabled = bool(status_map)
    updates = {
        TAGS_AS_TICKETS_FLAG: enabled,
        STATUS_TAG_IDS_KEY: status_map,
    }
    writer = getattr(store, "merge_binding_metadata", None)
    if callable(writer):
        writer(workspace_id, channel_id, updates)
    return updates


def extract_discord_token(discord: Any) -> str:
    if discord is None:
        return ""
    for attr in ("bot_token", "token", "_token"):
        raw = getattr(discord, attr, None)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    provider = getattr(discord, "provider", None)
    if provider is not None:
        for attr in ("bot_token", "token", "_token"):
            raw = getattr(provider, attr, None)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return ""


def apply_thread_status_tags(
    *,
    token: str,
    thread_id: str,
    status: Union[str, Any],
    status_tag_ids: Mapping[str, str],
    current_applied: Sequence[str] = (),
    opener: Any = None,
    require_tag: bool = False,
) -> dict[str, Any]:
    """PATCH thread applied_tags for ticket status. Fail closed on ACL / missing map."""

    from agent_discord.discord.errors import ToolInvocationError
    from agent_discord.discord.rest import set_thread_applied_tags
    from urllib.error import HTTPError

    tid = (thread_id or "").strip()
    if not tid:
        raise ForumRealmError(spoken_forum_need("thread id missing for tag sync"))
    wanted = status_value(status)
    if not wanted:
        return {"skipped": "unknown status", "applied_tags": list(current_applied or ())}
    if wanted not in status_tag_ids or not str(status_tag_ids.get(wanted) or "").strip():
        if require_tag:
            raise ForumRealmError(FORUM_NEED_TAGS_MISSING)
        return {"skipped": "no tag for status", "status": wanted}

    desired = merge_applied_tags_for_status(
        current_applied, status=wanted, status_tag_ids=status_tag_ids
    )
    try:
        raw = set_thread_applied_tags(
            token=token,
            thread_id=tid,
            tag_ids=desired,
            opener=opener,
        )
    except HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code in {401, 403}:
            raise ForumRealmError(FORUM_NEED_TAGS_PERMS) from exc
        raise ForumRealmError(
            spoken_forum_need(f"applied_tags PATCH failed HTTP {code or '?'}")
        ) from exc
    except ToolInvocationError as exc:
        msg = str(exc).lower()
        if "403" in msg or "401" in msg or "perm" in msg:
            raise ForumRealmError(FORUM_NEED_TAGS_PERMS) from exc
        raise ForumRealmError(spoken_forum_need(str(exc))) from exc
    except ForumRealmError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ForumRealmError(spoken_forum_need(str(exc))) from exc

    applied = parse_applied_tag_ids(raw) if isinstance(raw, dict) else desired
    return {
        "ok": True,
        "status": wanted,
        "applied_tags": list(applied or desired),
        "thread_id": tid,
    }


def maybe_sync_forum_ticket_tags(
    store: Any,
    *,
    discord: Any = None,
    token: str = "",
    workspace_id: str = "default",
    channel_id: str,
    thread_id: str,
    status: Union[str, Any],
    opener: Any = None,
    on_need: Any = None,
    require_tag: bool = False,
) -> dict[str, Any]:
    """Best-effort status→applied_tags sync for forum-as-realm posts.

    Soft-skips when the channel is not a forum realm or tags-as-tickets is off
    / has no status map. Speaks Need via ``on_need`` on ACL / require miss.
    """

    cid = (channel_id or "").strip()
    tid = (thread_id or "").strip()
    if not cid or not tid:
        return {"skipped": "missing ids"}
    if not binding_is_forum_realm(store, cid, workspace_id=workspace_id):
        # Forum post may have channel_id already as parent; also accept when
        # thread binding points at a forum parent that is a forum realm.
        parent = parent_from_forum_thread_binding(
            store, tid, workspace_id=workspace_id
        )
        if parent and binding_is_forum_realm(
            store, parent, workspace_id=workspace_id
        ):
            cid = parent
        else:
            return {"skipped": "not forum realm"}

    row = None
    reader = getattr(store, "get_binding", None)
    if callable(reader):
        try:
            row = reader(workspace_id, cid)
        except Exception:
            row = None
    status_map = status_tag_ids_from_binding(store, cid, workspace_id=workspace_id)
    if not tags_as_tickets_enabled(row) and not require_tag:
        return {"skipped": "tags-as-tickets off"}
    if not status_map:
        if require_tag:
            err = ForumRealmError(FORUM_NEED_TAGS_MISSING)
            if callable(on_need):
                try:
                    on_need(err.spoken)
                except Exception:
                    pass
            raise err
        return {"skipped": "no status tag map"}

    tok = (token or "").strip() or extract_discord_token(discord)
    if not tok:
        return {"skipped": "no token"}

    # Prefer remembered applied_tags on the post binding.
    current: tuple[str, ...] = ()
    reader = getattr(store, "get_binding", None)
    if callable(reader):
        try:
            meta = binding_metadata(reader(workspace_id, tid) or {})
            current = tuple(
                str(x).strip()
                for x in (meta.get(APPLIED_TAGS_KEY) or ())
                if str(x or "").strip()
            )
        except Exception:
            current = ()

    try:
        result = apply_thread_status_tags(
            token=tok,
            thread_id=tid,
            status=status,
            status_tag_ids=status_map,
            current_applied=current,
            opener=opener,
            require_tag=require_tag,
        )
    except ForumRealmError as exc:
        if callable(on_need):
            try:
                on_need(exc.spoken)
            except Exception:
                pass
        if require_tag:
            raise
        return {"error": exc.spoken}

    applied = result.get("applied_tags") or []
    if applied and callable(getattr(store, "merge_binding_metadata", None)):
        try:
            store.merge_binding_metadata(
                workspace_id,
                tid,
                {APPLIED_TAGS_KEY: list(applied)[:MAX_APPLIED_TAGS]},
            )
        except Exception:
            pass
    return result


__all__ = [
    "APPLIED_TAGS_KEY",
    "FORUM_META_FLAG",
    "FORUM_META_KIND",
    "FORUM_NEED_FETCH",
    "FORUM_NEED_MISSING_PERMS",
    "FORUM_NEED_NOT_FORUM",
    "FORUM_NEED_TAGS_MISSING",
    "FORUM_NEED_TAGS_PERMS",
    "ForumChannelInfo",
    "ForumRealmError",
    "ForumTag",
    "GUILD_FORUM",
    "MAX_APPLIED_TAGS",
    "STATUS_TAG_IDS_KEY",
    "TAGS_AS_TICKETS_FLAG",
    "apply_thread_status_tags",
    "assert_forum_channel",
    "binding_is_forum_realm",
    "build_status_tag_id_map",
    "cache_status_tags_from_forum_payload",
    "channel_is_forum",
    "clear_forum_binding_updates",
    "collect_forum_thread_dests",
    "discover_forum_post_rows",
    "discover_forum_post_threads",
    "extract_discord_token",
    "forum_binding_updates",
    "is_forum_binding",
    "list_forum_realm_channel_ids",
    "mark_forum_binding",
    "maybe_sync_forum_ticket_tags",
    "merge_applied_tags_for_status",
    "normalize_tag_name",
    "parent_from_forum_thread_binding",
    "parse_applied_tag_ids",
    "parse_available_tags",
    "parse_channel_info",
    "remember_forum_thread_parent",
    "resolve_status_from_applied_tags",
    "spoken_forum_need",
    "status_tag_ids_from_binding",
    "status_value",
    "tags_as_tickets_enabled",
    "unmark_forum_binding",
    "validate_and_mark_forum_bind",
]
