"""Discord HTTP REST — default live transport (no MCP, no Gateway).

Object put/get, channel poll, and send/edit/delete use the official API.
CDN URLs are ephemeral handles only — never stored as durable keys.
Token is sent as Authorization and never returned.
"""

from __future__ import annotations

import errno
import json
import socket
import time
import uuid
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from agent_discord.contracts import DiscordAttachment, DiscordMessage
from agent_discord.discord.errors import ToolInvocationError
from agent_discord.discord.layout import FLAG_COMPONENTS_V2, fit_components_v2

DISCORD_API_BASE = "https://discord.com/api/v10"
USER_AGENT = "discord-os (https://github.com/professorpalmer/discord-os)"
_ATTACHMENT_HOSTS = frozenset(
    {"cdn.discordapp.com", "media.discordapp.net", "cdn.discord.com"}
)
VOICE_FETCH_MAX_BYTES = 25 * 1024 * 1024


UrlOpener = Callable[..., Any]
_TRANSIENT_HTTP = frozenset({502, 503, 504})
# 500 means the origin ran the request, so only replay it when a replay is a
# no-op. 502/503/504 come from the edge before Discord applied anything.
_IDEMPOTENT_RETRY_HTTP = frozenset({500})
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"})
_TRANSIENT_RETRY_SLEEPS = (0.25, 0.75)
RATE_LIMIT_MAX_RETRIES = 3
# A longer cooldown than this is not something a channel tick should sit on.
RATE_LIMIT_MAX_WAIT_SECONDS = 60.0
RATE_LIMIT_FALLBACK_WAIT_SECONDS = 1.0
ERROR_BODY_MAX_CHARS = 400
# Buckets are keyed by major parameter; everything else is a minor id.
_MAJOR_PARAM_PARENTS = frozenset({"channels", "guilds", "webhooks"})
_SNOWFLAKE_MIN_DIGITS = 15
# macOS EADDRNOTAVAIL=49 ("Can't assign requested address") and cousins —
# listen drain should retry honestly, not paint fake READY.
_TRANSIENT_ERRNOS = frozenset(
    {
        errno.EADDRNOTAVAIL,  # 49 on Darwin
        errno.ETIMEDOUT,
        errno.ECONNRESET,
        errno.ECONNREFUSED,
        errno.EHOSTUNREACH,
        errno.ENETUNREACH,
        errno.EPIPE,
        getattr(errno, "ECONNABORTED", 53),
    }
)


def _retry_sleep(seconds: float) -> None:
    time.sleep(float(seconds))


def is_transient_discord_network_error(exc: BaseException) -> bool:
    """True for TimeoutError / Errno 49 / URLError wraps — honest REST retry.

    Does **not** mean Gateway READY. Listen may quiet-log these without
    escalating Need / fake liveness.
    """

    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if reason is not None and reason is not exc:
            if is_transient_discord_network_error(reason):
                return True
        # Unclassified URLError (DNS / route flap) — still retry once/twice.
        return True
    if isinstance(exc, OSError):
        code = getattr(exc, "errno", None)
        if code in _TRANSIENT_ERRNOS:
            return True
        if code == getattr(errno, "ETIME", -1):
            return True
    msg = str(exc or "").lower()
    if "http 401" in msg or "http 403" in msg:
        return False
    # Live Mac saw ssl/urllib "The read operation timed out" outside TimeoutError.
    if (
        "discord rest unreachable" in msg
        or "timed out" in msg
        or "timeout" in msg
        or "eaddrnotavail" in msg
        or "can't assign requested address" in msg
    ):
        if "http 4" in msg and "http 408" not in msg and "http 429" not in msg:
            return False
        return True
    return False


def transient_network_label(exc: BaseException) -> str:
    """Short quiet-log label (no secrets)."""

    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        code = getattr(exc, "errno", None)
        if code == errno.EADDRNOTAVAIL:
            return "errno 49 EADDRNOTAVAIL"
        if code is not None:
            return f"errno {code}"
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, BaseException):
            return transient_network_label(reason)
        return "URLError"
    text_s = str(exc or "").strip()
    if "unreachable" in text_s.lower():
        return "unreachable"
    return (text_s[:60] or "network").strip()


# macOS/Linux codes that mean the socket never carried the request, so even a
# POST may be replayed without posting a duplicate card.
_NOT_SENT_ERRNOS = frozenset(
    {
        errno.ECONNREFUSED,
        errno.EHOSTUNREACH,
        errno.ENETUNREACH,
        errno.EADDRNOTAVAIL,
    }
)


def request_definitely_not_sent(exc: BaseException) -> bool:
    """True only when the request provably never left this host."""

    if isinstance(exc, socket.gaierror):
        return True
    if isinstance(exc, TimeoutError):
        return False
    if getattr(exc, "errno", None) in _NOT_SENT_ERRNOS:
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException) and reason is not exc:
        return request_definitely_not_sent(reason)
    return False


def _headers_of(source: Any) -> Any:
    headers = getattr(source, "headers", None)
    if headers is not None:
        return headers
    info = getattr(source, "info", None)
    if callable(info):
        try:
            return info() or {}
        except Exception:
            return {}
    return {}


def _header(headers: Any, name: str) -> str:
    """Read one header case-insensitively from a Message, dict, or stub."""

    getter = getattr(headers, "get", None)
    if callable(getter):
        try:
            value = getter(name)
        except Exception:
            value = None
        if value is not None:
            return str(value).strip()
    items = getattr(headers, "items", None)
    if callable(items):
        wanted = name.casefold()
        try:
            pairs = list(items())
        except Exception:
            pairs = ()
        for key, value in pairs:
            if str(key).casefold() == wanted:
                return str(value).strip()
    return ""


def _as_float(text: str) -> Optional[float]:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _as_int(text: str) -> Optional[int]:
    value = _as_float(text)
    return None if value is None else int(value)


def route_bucket_key(method: str, url: str) -> str:
    """Discord's bucket identity: method plus path with minor ids collapsed."""

    path = urlparse(url).path or url
    parts = path.split("/")
    out: list[str] = []
    for index, part in enumerate(parts):
        if part.isdigit() and len(part) >= _SNOWFLAKE_MIN_DIGITS:
            parent = parts[index - 1] if index else ""
            out.append(part if parent in _MAJOR_PARAM_PARENTS else "{id}")
        else:
            out.append(part)
    return f"{method.upper()} {'/'.join(out)}"


class RestRateLimiter:
    """Per-route bucket book-keeping plus 429 cooldowns.

    Clock and sleeper are injectable so tests never wait on wall time. State is
    process-local: Discord buckets are per-token, and one host owns one token.
    """

    def __init__(
        self,
        *,
        sleeper: Optional[Callable[[float], None]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._sleeper = sleeper
        self._clock = clock
        self._bucket_of_route: dict[str, str] = {}
        self._bucket_reset_at: dict[str, float] = {}
        self._bucket_remaining: dict[str, int] = {}
        self._global_until = 0.0
        self.waits: list[float] = []

    def now(self) -> float:
        return float(self._clock() if self._clock is not None else time.monotonic())

    def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self.waits.append(float(seconds))
        if self._sleeper is not None:
            self._sleeper(float(seconds))
        else:
            _retry_sleep(seconds)

    def reset(self) -> None:
        self._bucket_of_route.clear()
        self._bucket_reset_at.clear()
        self._bucket_remaining.clear()
        self._global_until = 0.0
        self.waits.clear()

    def acquire(self, route_key: str) -> None:
        """Wait out a global cooldown and an exhausted bucket before sending."""

        remaining_global = self._global_until - self.now()
        if remaining_global > 0:
            self._sleep(remaining_global)
        bucket = self._bucket_of_route.get(route_key)
        if not bucket:
            return
        if self._bucket_remaining.get(bucket, 1) > 0:
            return
        wait = self._bucket_reset_at.get(bucket, 0.0) - self.now()
        if wait > 0:
            self._sleep(wait)
        # One request through; the response headers restore the real count.
        self._bucket_remaining[bucket] = 1

    def observe(self, route_key: str, headers: Any) -> None:
        bucket = _header(headers, "X-RateLimit-Bucket")
        if not bucket:
            return
        self._bucket_of_route[route_key] = bucket
        remaining = _as_int(_header(headers, "X-RateLimit-Remaining"))
        if remaining is not None:
            self._bucket_remaining[bucket] = remaining
        reset_after = _as_float(_header(headers, "X-RateLimit-Reset-After"))
        if reset_after is not None:
            self._bucket_reset_at[bucket] = self.now() + reset_after

    def note_rate_limited(
        self, route_key: str, retry_after: float, *, is_global: bool
    ) -> None:
        wait = max(0.0, float(retry_after))
        now = self.now()
        if is_global:
            self._global_until = max(self._global_until, now + wait)
        else:
            bucket = self._bucket_of_route.setdefault(route_key, route_key)
            self._bucket_remaining[bucket] = 0
            self._bucket_reset_at[bucket] = now + wait
        self._sleep(wait)


_LIMITER = RestRateLimiter()


def _retry_after_from_429(detail: str, headers: Any) -> tuple[float, bool]:
    """Seconds to wait and whether the limit is global, body first."""

    wait: Optional[float] = None
    is_global = False
    try:
        parsed = json.loads(detail) if detail else None
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        if parsed.get("retry_after") is not None:
            wait = _as_float(str(parsed.get("retry_after")))
        is_global = bool(parsed.get("global"))
    if wait is None:
        wait = _as_float(_header(headers, "Retry-After"))
    if not is_global:
        if _header(headers, "X-RateLimit-Global").lower() in {"true", "1"}:
            is_global = True
        if _header(headers, "X-RateLimit-Scope").lower() == "global":
            is_global = True
    if wait is None:
        wait = RATE_LIMIT_FALLBACK_WAIT_SECONDS
    return max(0.0, wait), is_global


def _read_error_body(exc: HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:
        return ""
    if not raw:
        return ""
    try:
        text = bytes(raw).decode("utf-8", errors="replace")
    except Exception:
        return ""
    return " ".join(text.split())[:ERROR_BODY_MAX_CHARS]


def _redact_token(text: str, token: str) -> str:
    secret = (token or "").strip()
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


def _http_error_text(code: int, detail: str, token: str) -> str:
    body = _redact_token(detail, token)
    if not body:
        return f"Discord REST HTTP {code}"
    return f"Discord REST HTTP {code} {body}"


def call_discord_json(
    token: str,
    method: str,
    path: str,
    *,
    payload: Optional[dict[str, Any]] = None,
    opener: Optional[UrlOpener] = None,
) -> Any:
    """JSON Discord REST helper. Token is sent as Authorization only."""

    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _discord_request(
        token,
        method,
        path,
        body=body,
        content_type="application/json",
        opener=opener,
    )


def fetch_channel(
    *,
    token: str,
    channel_id: str,
    opener: Optional[UrlOpener] = None,
) -> dict[str, Any]:
    """GET /channels/{channel.id}. Public channel fields only — never the token."""

    cid = (channel_id or "").strip()
    if not cid:
        raise ToolInvocationError("Discord channel id required")
    raw = call_discord_json(token, "GET", f"/channels/{cid}", opener=opener)
    if not isinstance(raw, dict):
        raise ToolInvocationError("Discord channel fetch was not an object")
    return raw


def list_active_threads(
    *,
    token: str,
    channel_id: str,
    opener: Optional[UrlOpener] = None,
) -> tuple[dict[str, Any], ...]:
    """GET /channels/{channel.id}/threads/active (forum / text parent).

    Returns thread channel objects. Empty tuple when none. Callers map 403 →
    spoken Need for forum-as-realm.
    """

    cid = (channel_id or "").strip()
    if not cid:
        raise ToolInvocationError("Discord channel id required")
    raw = call_discord_json(
        token, "GET", f"/channels/{cid}/threads/active", opener=opener
    )
    if not isinstance(raw, dict):
        raise ToolInvocationError("Discord active threads was not an object")
    threads = raw.get("threads") or ()
    out: list[dict[str, Any]] = []
    for item in threads:
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            out.append(item)
    return tuple(out)


def modify_channel(
    *,
    token: str,
    channel_id: str,
    payload: Mapping[str, Any],
    opener: Optional[UrlOpener] = None,
) -> dict[str, Any]:
    """PATCH /channels/{channel.id}.

    Forum/media threads use this for ``applied_tags`` (max 5 snowflakes).
    Callers map 401/403 → spoken Need for tags-as-tickets.
    """

    cid = (channel_id or "").strip()
    if not cid:
        raise ToolInvocationError("Discord channel id required")
    body = dict(payload or {})
    # HARD lock: never auto-create / rewrite forum available_tags.
    if "available_tags" in body:
        raise ToolInvocationError(
            "refused: Discord OS never mutates available_tags "
            "(add tags manually on the forum)"
        )
    raw = call_discord_json(
        token, "PATCH", f"/channels/{cid}", payload=body, opener=opener
    )
    if not isinstance(raw, dict):
        raise ToolInvocationError("Discord channel modify was not an object")
    return raw


def set_thread_applied_tags(
    *,
    token: str,
    thread_id: str,
    tag_ids: Sequence[str],
    opener: Optional[UrlOpener] = None,
) -> dict[str, Any]:
    """Replace ``applied_tags`` on a forum/media thread (Discord max 5)."""

    tid = (thread_id or "").strip()
    if not tid:
        raise ToolInvocationError("Discord thread id required")
    ids: list[str] = []
    seen: set[str] = set()
    for raw in tag_ids or ():
        tag = str(raw or "").strip()
        if not tag or tag in seen:
            continue
        ids.append(tag)
        seen.add(tag)
        if len(ids) >= 5:
            break
    return modify_channel(
        token=token,
        channel_id=tid,
        payload={"applied_tags": ids},
        opener=opener,
    )


def fetch_bot_identity(
    *,
    token: str,
    opener: Optional[UrlOpener] = None,
) -> dict[str, str]:
    """GET /users/@me. Returns public bot fields only — never the token."""

    raw = call_discord_json(token, "GET", "/users/@me", opener=opener)
    if not isinstance(raw, dict):
        raise ToolInvocationError("Discord REST identity was not an object")
    return {
        "id": str(raw.get("id") or ""),
        "username": str(raw.get("username") or ""),
        "avatar": str(raw.get("avatar") or ""),
    }


def fetch_message_attachment_bytes(
    token: str,
    *,
    channel_id: str,
    message_id: str,
    attachment_id: str,
    opener: Optional[UrlOpener] = None,
    max_bytes: int = VOICE_FETCH_MAX_BYTES,
) -> bytes:
    """Re-read the message, fetch bytes, drop the signed URL. Nothing persisted."""

    raw = call_discord_json(
        token,
        "GET",
        f"/channels/{channel_id}/messages/{message_id}",
        opener=opener,
    )
    if not isinstance(raw, dict):
        raise ToolInvocationError("Discord message fetch was not an object")
    url = ""
    for att in raw.get("attachments") or ():
        if not isinstance(att, dict):
            continue
        if str(att.get("id") or "") != str(attachment_id):
            continue
        url = str(att.get("url") or att.get("proxy_url") or "").strip()
        break
    if not url:
        raise ToolInvocationError("voice attachment URL missing from message")
    return fetch_attachment_bytes(token, url, opener=opener, max_bytes=max_bytes)


def fetch_attachment_bytes(
    token: str,
    url: str,
    *,
    opener: Optional[UrlOpener] = None,
    max_bytes: int = VOICE_FETCH_MAX_BYTES,
) -> bytes:
    """GET a Discord attachment URL with the bot token. Never persist the URL."""

    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"} or host not in _ATTACHMENT_HOSTS:
        raise ToolInvocationError("attachment URL is not a Discord CDN host")
    if "/attachments/" not in parsed.path:
        raise ToolInvocationError("attachment URL is not a Discord attachment")
    raw = _discord_request_bytes(
        token,
        "GET",
        url,
        opener=opener,
        absolute=True,
    )
    if len(raw) > int(max_bytes):
        raise ToolInvocationError("attachment exceeds fetch budget")
    return raw


def bot_avatar_url(identity: Mapping[str, Any]) -> str:
    user_id = str(identity.get("id") or "").strip()
    avatar = str(identity.get("avatar") or "").strip()
    if user_id and avatar:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=128"
    if user_id.isdigit():
        return f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 6}.png"
    return ""


def start_message_thread(
    *,
    token: str,
    channel_id: str,
    message_id: str,
    name: str,
    opener: Optional[UrlOpener] = None,
) -> str:
    title = (name or "job").replace("\n", " ").strip() or "job"
    raw = call_discord_json(
        token,
        "POST",
        f"/channels/{channel_id}/messages/{message_id}/threads",
        payload={"name": title[:100], "auto_archive_duration": 1440},
        opener=opener,
    )
    if not isinstance(raw, dict):
        raise ToolInvocationError("Discord thread create was not an object")
    thread_id = str(raw.get("id") or "").strip()
    if not thread_id:
        raise ToolInvocationError("Discord thread create missing id")
    return thread_id



def add_message_reaction(
    token: str,
    channel_id: str,
    message_id: str,
    emoji: str,
    *,
    opener: Optional[UrlOpener] = None,
) -> None:
    """PUT a reaction on a message. Empty body. Emoji is URL-encoded."""

    encoded = quote(emoji, safe="")
    call_discord_json(
        token,
        "PUT",
        f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
        opener=opener,
    )


def list_message_reactions(
    *,
    token: str,
    channel_id: str,
    message_id: str,
    emoji: str,
    limit: int = 100,
    opener: Optional[UrlOpener] = None,
) -> tuple[dict[str, Any], ...]:
    """GET the users who reacted with one emoji. Emoji is URL-encoded.

    Reading reactions over REST is how settled cards get an operator outcome:
    the Gateway is only there for On/Off (lock 4), so there is no reaction
    event to listen for.
    """

    cid = (channel_id or "").strip()
    mid = (message_id or "").strip()
    if not cid or not mid:
        raise ToolInvocationError("Discord channel and message id required")
    encoded = quote(emoji, safe="")
    capped = max(1, min(int(limit), 100))
    raw = call_discord_json(
        token,
        "GET",
        f"/channels/{cid}/messages/{mid}/reactions/{encoded}?limit={capped}",
        opener=opener,
    )
    if not isinstance(raw, list):
        raise ToolInvocationError("Discord reaction list was not an array")
    return tuple(item for item in raw if isinstance(item, dict))


def patch_bot_avatar(
    *,
    token: str,
    png_bytes: bytes,
    opener: Optional[UrlOpener] = None,
) -> None:
    import base64

    encoded = base64.b64encode(png_bytes).decode("ascii")
    call_discord_json(
        token,
        "PATCH",
        "/users/@me",
        payload={"avatar": f"data:image/png;base64,{encoded}"},
        opener=opener,
    )


def list_channel_messages(
    *,
    token: str,
    channel_id: str,
    limit: int = 20,
    thread_id: Optional[str] = None,
    after: Optional[str] = None,
    opener: Optional[UrlOpener] = None,
) -> list[DiscordMessage]:
    """Newest-first page. ``after`` anchors the window at a message id."""

    dest = thread_id or channel_id
    capped = max(1, min(int(limit), 100))
    query = f"limit={capped}"
    anchor = str(after or "").strip()
    if anchor:
        query = f"{query}&after={anchor}"
    raw = call_discord_json(
        token,
        "GET",
        f"/channels/{dest}/messages?{query}",
        opener=opener,
    )
    if not isinstance(raw, list):
        raise ToolInvocationError("Discord REST message list was not an array")
    return [
        message_from_rest_payload(item, channel_id=channel_id, thread_id=thread_id)
        for item in raw
        if isinstance(item, dict)
    ]


def send_channel_message(
    *,
    token: str,
    channel_id: str,
    content: str,
    thread_id: Optional[str] = None,
    components: Optional[list[dict[str, Any]]] = None,
    embeds: Optional[list[dict[str, Any]]] = None,
    poll: Optional[Mapping[str, Any]] = None,
    flags: int = 0,
    opener: Optional[UrlOpener] = None,
) -> DiscordMessage:
    dest = thread_id or channel_id
    payload: dict[str, Any] = {}
    if flags:
        payload["flags"] = int(flags)
    if flags & FLAG_COMPONENTS_V2:
        if components:
            payload["components"] = fit_components_v2(components)
    else:
        payload["content"] = content or ""
        if embeds:
            payload["embeds"] = list(embeds)
        if components:
            payload["components"] = list(components)
    if poll is not None:
        # Discord native polls (non-blocking preference asks). Not for live gates.
        payload["poll"] = dict(poll)
    raw = call_discord_json(
        token,
        "POST",
        f"/channels/{dest}/messages",
        payload=payload,
        opener=opener,
    )
    return message_from_rest_payload(
        raw,
        channel_id=channel_id,
        thread_id=thread_id,
        fallback_content=content,
    )


def edit_channel_message(
    *,
    token: str,
    channel_id: str,
    message_id: str,
    content: str,
    components: Optional[list[dict[str, Any]]] = None,
    embeds: Optional[list[dict[str, Any]]] = None,
    flags: int = 0,
    opener: Optional[UrlOpener] = None,
) -> DiscordMessage:
    payload: dict[str, Any] = {}
    if flags:
        payload["flags"] = int(flags)
    if flags & FLAG_COMPONENTS_V2:
        if components is not None:
            payload["components"] = fit_components_v2(components)
    else:
        payload["content"] = content or ""
        if embeds is not None:
            payload["embeds"] = list(embeds)
        if components is not None:
            payload["components"] = list(components)
    raw = call_discord_json(
        token,
        "PATCH",
        f"/channels/{channel_id}/messages/{message_id}",
        payload=payload,
        opener=opener,
    )
    return message_from_rest_payload(
        raw, channel_id=channel_id, fallback_content=content
    )


def edit_original_interaction(
    *,
    application_id: str,
    interaction_token: str,
    payload: dict[str, Any],
    opener: Optional[UrlOpener] = None,
) -> None:
    """Update the message after a deferred ACK. Uses the interaction token."""

    if not application_id.strip() or not interaction_token.strip():
        raise ToolInvocationError("Discord interaction edit missing application/token")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}/messages/@original",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="PATCH",
    )
    do_open = opener or urlopen
    try:
        with do_open(request, timeout=10) as resp:
            resp.read()
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
        except Exception:
            detail = ""
        raise ToolInvocationError(
            f"Discord interaction edit HTTP {exc.code} {detail}".strip()
        ) from None
    except URLError as exc:
        raise ToolInvocationError("Discord interaction edit unreachable") from exc


def create_followup_message(
    *,
    application_id: str,
    interaction_token: str,
    payload: dict[str, Any],
    opener: Optional[UrlOpener] = None,
) -> None:
    """Post a follow-up after a deferred ACK. Uses the interaction token."""

    if not application_id.strip() or not interaction_token.strip():
        raise ToolInvocationError("Discord follow-up missing application/token")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{DISCORD_API_BASE}/webhooks/{application_id}/{interaction_token}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    do_open = opener or urlopen
    try:
        with do_open(request, timeout=10) as resp:
            resp.read()
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
        except Exception:
            detail = ""
        raise ToolInvocationError(
            f"Discord follow-up HTTP {exc.code} {detail}".strip()
        ) from None
    except URLError as exc:
        raise ToolInvocationError("Discord follow-up unreachable") from exc


def callback_interaction(
    *,
    interaction_id: str,
    interaction_token: str,
    payload: dict[str, Any],
    opener: Optional[UrlOpener] = None,
) -> None:
    """ACK a button click. Uses the interaction token, not the bot token."""

    if not interaction_id.strip() or not interaction_token.strip():
        raise ToolInvocationError("Discord interaction callback missing id/token")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{DISCORD_API_BASE}/interactions/{interaction_id}/{interaction_token}/callback",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    do_open = opener or urlopen
    try:
        with do_open(request, timeout=10) as resp:
            resp.read()
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
        except Exception:
            detail = ""
        raise ToolInvocationError(
            f"Discord interaction callback HTTP {exc.code} {detail}".strip()
        ) from None
    except URLError as exc:
        raise ToolInvocationError("Discord interaction callback unreachable") from exc


def delete_channel_message(
    *,
    token: str,
    channel_id: str,
    message_id: str,
    opener: Optional[UrlOpener] = None,
) -> None:
    call_discord_json(
        token,
        "DELETE",
        f"/channels/{channel_id}/messages/{message_id}",
        opener=opener,
    )


def send_channel_attachment(
    *,
    token: str,
    channel_id: str,
    filename: str,
    data: bytes,
    content: str = "",
    thread_id: Optional[str] = None,
    embeds: Optional[list[dict[str, Any]]] = None,
    components: Optional[list[dict[str, Any]]] = None,
    flags: int = 0,
    attachment_extra: Optional[Mapping[str, Any]] = None,
    attachment_content_type: str = "",
    opener: Optional[UrlOpener] = None,
) -> DiscordMessage:
    """POST a file to a channel (or thread) via Discord REST multipart.

    ``attachment_extra`` merges into the single ``attachments[0]`` descriptor —
    this is how a voice message carries ``duration_secs`` + ``waveform``.
    ``attachment_content_type`` overrides the file part's MIME type (Discord
    requires ``audio/ogg`` for a voice message, not octet-stream).
    """

    dest = thread_id or channel_id
    safe_name = _safe_filename(filename)
    descriptor: dict[str, Any] = {"id": 0, "filename": safe_name}
    if attachment_extra:
        descriptor.update({str(k): v for k, v in attachment_extra.items()})
    payload: dict[str, Any] = {"attachments": [descriptor]}
    if flags:
        payload["flags"] = int(flags)
    if flags & FLAG_COMPONENTS_V2:
        if components:
            payload["components"] = fit_components_v2(components)
    else:
        payload["content"] = content or ""
        if embeds:
            payload["embeds"] = list(embeds)
        if components:
            payload["components"] = list(components)
    body, content_type = _multipart_message(
        payload, safe_name, data, file_content_type=attachment_content_type
    )
    raw = _discord_request(
        token,
        "POST",
        f"/channels/{dest}/messages",
        body=body,
        content_type=content_type,
        opener=opener,
    )
    return message_from_rest_payload(
        raw,
        channel_id=channel_id,
        thread_id=thread_id,
        fallback_content=content,
    )


def fetch_channel_message(
    *,
    token: str,
    channel_id: str,
    message_id: str,
    opener: Optional[UrlOpener] = None,
) -> DiscordMessage:
    raw = _discord_request(
        token,
        "GET",
        f"/channels/{channel_id}/messages/{message_id}",
        opener=opener,
    )
    return message_from_rest_payload(raw, channel_id=channel_id)


def download_attachment_url(
    *,
    token: str,
    url: str,
    opener: Optional[UrlOpener] = None,
) -> bytes:
    """GET an ephemeral attachment URL. Caller must not persist the URL."""

    if not url.startswith("https://cdn.discordapp.com/") and not url.startswith(
        "https://media.discordapp.net/"
    ):
        raise ToolInvocationError("attachment URL is not a Discord CDN handle")
    return _discord_request_bytes(token, "GET", url, opener=opener, absolute=True)


def download_channel_attachment(
    *,
    token: str,
    channel_id: str,
    message_id: str,
    attachment_id: str,
    opener: Optional[UrlOpener] = None,
) -> bytes:
    """Re-fetch the message for a fresh CDN handle, then download. Do not store the URL."""

    raw = _discord_request(
        token,
        "GET",
        f"/channels/{channel_id}/messages/{message_id}",
        opener=opener,
    )
    if not isinstance(raw, dict):
        raise ToolInvocationError("Discord REST returned a non-object message")
    for att_id, url in _attachment_handles(raw):
        if att_id != str(attachment_id):
            continue
        if not url:
            raise ToolInvocationError("attachment had no ephemeral CDN handle")
        return download_attachment_url(token=token, url=url, opener=opener)
    raise ToolInvocationError(
        f"attachment {attachment_id!r} not on message {message_id!r}"
    )


def message_from_rest_payload(
    raw: Any,
    *,
    channel_id: str,
    thread_id: Optional[str] = None,
    fallback_content: str = "",
) -> DiscordMessage:
    if not isinstance(raw, dict):
        raise ToolInvocationError("Discord REST returned a non-object message")
    attachments: list[DiscordAttachment] = []
    for att in raw.get("attachments") or ():
        parsed = _attachment_from_rest(att)
        if parsed is not None:
            attachments.append(parsed)
    components = raw.get("components") if isinstance(raw.get("components"), list) else []
    seen = {item.attachment_id for item in attachments if item.attachment_id}
    for parsed in _attachments_from_components(components):
        if parsed.attachment_id and parsed.attachment_id in seen:
            continue
        attachments.append(parsed)
        if parsed.attachment_id:
            seen.add(parsed.attachment_id)
    msg_thread = thread_id
    if raw.get("thread") and isinstance(raw["thread"], dict) and raw["thread"].get("id"):
        msg_thread = str(raw["thread"]["id"])
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    embeds = list(raw.get("embeds")) if isinstance(raw.get("embeds"), list) else []
    content = str(raw.get("content") or fallback_content)
    forwarded = _forwarded_snapshots(raw)
    if forwarded:
        content = _merge_forward_content(content, forwarded)
        for snapshot in forwarded:
            for att in snapshot.get("attachments") or ():
                parsed = _attachment_from_rest(att)
                if parsed is None:
                    continue
                if parsed.attachment_id and parsed.attachment_id in seen:
                    continue
                attachments.append(parsed)
                if parsed.attachment_id:
                    seen.add(parsed.attachment_id)
            snap_embeds = snapshot.get("embeds")
            if isinstance(snap_embeds, list):
                embeds.extend(snap_embeds)
    metadata: dict[str, Any] = {
        "provider": "discord-rest",
        "embeds": embeds,
        "components": _scrub_component_urls(components),
        "flags": raw.get("flags") or 0,
        "author_name": str(author.get("global_name") or author.get("username") or ""),
        "author_bot": bool(author.get("bot")),
    }
    if forwarded:
        metadata["forwarded"] = True
    return DiscordMessage(
        channel_id=str(raw.get("channel_id") or channel_id),
        content=content,
        message_id=str(raw.get("id") or ""),
        thread_id=msg_thread,
        author_id=str(author.get("id") or "") or None,
        attachments=tuple(attachments),
        metadata=metadata,
    )


FORWARD_PROVENANCE = "forwarded"
MESSAGE_REFERENCE_FORWARD = 1


def _forwarded_snapshots(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Snapshot message objects behind a forward.

    A forward arrives with an empty outer ``content`` and the real payload in
    ``message_snapshots[].message``; ``message_reference.type`` is 1 (FORWARD).
    Without this the intake is blank.
    """

    snapshots = raw.get("message_snapshots")
    if not isinstance(snapshots, list):
        return []
    reference = (
        raw.get("message_reference")
        if isinstance(raw.get("message_reference"), dict)
        else {}
    )
    ref_type = reference.get("type")
    if ref_type is not None:
        try:
            if int(ref_type) != MESSAGE_REFERENCE_FORWARD:
                return []
        except (TypeError, ValueError):
            return []
    found: list[dict[str, Any]] = []
    for item in snapshots:
        if not isinstance(item, dict):
            continue
        message = item.get("message")
        if isinstance(message, dict):
            found.append(message)
    return found


def _merge_forward_content(content: str, snapshots: Sequence[Mapping[str, Any]]) -> str:
    bodies = [str(snap.get("content") or "").strip() for snap in snapshots]
    bodies = [body for body in bodies if body]
    block = "\n\n".join([FORWARD_PROVENANCE] + bodies)
    head = (content or "").strip()
    return f"{head}\n\n{block}" if head else block


def _attachment_from_rest(att: Any) -> Optional[DiscordAttachment]:
    if not isinstance(att, dict):
        return None
    att_id = str(att.get("id") or att.get("attachment_id") or "")
    name = str(att.get("filename") or att.get("name") or "")
    if not att_id and not name:
        return None
    try:
        size = int(att.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return DiscordAttachment(
        attachment_id=att_id,
        filename=name,
        size=size,
        content_type=str(att.get("content_type") or ""),
    )


def _attachment_id_from_url(url: str) -> str:
    if "/attachments/" not in url:
        return ""
    parts = url.split("/attachments/", 1)[-1].split("/")
    if len(parts) < 2:
        return ""
    return parts[1].split("?", 1)[0]


def _walk_component_dicts(components: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for item in components or ():
        if not isinstance(item, dict):
            continue
        found.append(item)
        nested = item.get("components")
        if isinstance(nested, list):
            found.extend(_walk_component_dicts(nested))
    return found


def _attachments_from_components(components: Any) -> list[DiscordAttachment]:
    found: list[DiscordAttachment] = []
    for item in _walk_component_dicts(components):
        if int(item.get("type") or 0) != 13:
            continue
        media = item.get("file") if isinstance(item.get("file"), dict) else {}
        url = str(media.get("url") or media.get("proxy_url") or "")
        att_id = _attachment_id_from_url(url) or str(media.get("attachment_id") or "")
        name = str(item.get("name") or media.get("name") or media.get("filename") or "")
        parsed = _attachment_from_rest(
            {
                "id": att_id,
                "filename": name,
                "size": item.get("size") or media.get("size") or 0,
                "content_type": media.get("content_type") or "",
            }
        )
        if parsed is not None:
            found.append(parsed)
    return found


def _attachment_handles(raw: Mapping[str, Any]) -> list[tuple[str, str]]:
    handles: list[tuple[str, str]] = []
    for att in raw.get("attachments") or ():
        if not isinstance(att, dict):
            continue
        att_id = str(att.get("id") or "")
        url = str(att.get("url") or att.get("proxy_url") or "")
        if att_id and url:
            handles.append((att_id, url))
    for item in _walk_component_dicts(raw.get("components")):
        if int(item.get("type") or 0) != 13:
            continue
        media = item.get("file") if isinstance(item.get("file"), dict) else {}
        url = str(media.get("url") or media.get("proxy_url") or "")
        att_id = _attachment_id_from_url(url) or str(media.get("attachment_id") or "")
        if att_id and url:
            handles.append((att_id, url))
    return handles


def _scrub_component_urls(components: Any) -> list[Any]:
    cleaned: list[Any] = []
    for item in components or ():
        if not isinstance(item, dict):
            cleaned.append(item)
            continue
        copy = dict(item)
        media = copy.get("file")
        if isinstance(media, dict):
            media = dict(media)
            media.pop("url", None)
            media.pop("proxy_url", None)
            copy["file"] = media
        nested = copy.get("components")
        if isinstance(nested, list):
            copy["components"] = _scrub_component_urls(nested)
        cleaned.append(copy)
    return cleaned


def _safe_filename(filename: str) -> str:
    name = (filename or "object.bin").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch not in "\r\n\x00\"")
    return name or "object.bin"


def _safe_mimetype(value: str) -> str:
    """Keep a MIME type header-safe. Reject anything but token/token chars."""

    raw = (value or "").strip()
    if not raw or "/" not in raw:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789/+-.")
    lowered = raw.lower()
    return lowered if set(lowered) <= allowed else ""


def _multipart_message(
    payload: dict[str, Any],
    filename: str,
    data: bytes,
    *,
    file_content_type: str = "",
) -> tuple[bytes, str]:
    part_type = _safe_mimetype(file_content_type) or "application/octet-stream"
    boundary = f"----agentdiscord{uuid.uuid4().hex}"
    crlf = b"\r\n"
    chunks: list[bytes] = []
    chunks.extend(
        (
            f"--{boundary}".encode("ascii"),
            crlf,
            b'Content-Disposition: form-data; name="payload_json"',
            crlf,
            b"Content-Type: application/json",
            crlf,
            crlf,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            crlf,
            f"--{boundary}".encode("ascii"),
            crlf,
            (
                f'Content-Disposition: form-data; name="files[0]"; '
                f'filename="{filename}"'
            ).encode("utf-8"),
            crlf,
            f"Content-Type: {part_type}".encode("ascii"),
            crlf,
            crlf,
            data,
            crlf,
            f"--{boundary}--".encode("ascii"),
            crlf,
        )
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _discord_request(
    token: str,
    method: str,
    path: str,
    *,
    body: Optional[bytes] = None,
    content_type: str = "application/json",
    opener: Optional[UrlOpener] = None,
) -> Any:
    raw = _discord_request_bytes(
        token,
        method,
        path,
        body=body,
        content_type=content_type,
        opener=opener,
        absolute=False,
    )
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolInvocationError("Discord REST returned non-JSON") from exc
    if isinstance(parsed, dict) and parsed.get("message") and parsed.get("code"):
        raise ToolInvocationError(f"Discord REST error {parsed.get('code')}")
    return parsed


def _discord_request_bytes(
    token: str,
    method: str,
    path: str,
    *,
    body: Optional[bytes] = None,
    content_type: str = "application/json",
    opener: Optional[UrlOpener] = None,
    absolute: bool = False,
) -> bytes:
    if not token.strip():
        raise ToolInvocationError("Discord REST requires a bot token")
    url = path if absolute else f"{DISCORD_API_BASE}{path}"
    headers = {
        "Authorization": f"Bot {token.strip()}",
        "User-Agent": USER_AGENT,
    }
    if body is not None:
        headers["Content-Type"] = content_type
    do_open = opener or urlopen
    limiter = _LIMITER
    route = route_bucket_key(method, url)
    idempotent = method.upper() in _IDEMPOTENT_METHODS
    transient_left = len(_TRANSIENT_RETRY_SLEEPS)
    rate_limit_left = RATE_LIMIT_MAX_RETRIES
    backoff = 0
    while True:
        limiter.acquire(route)
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with do_open(request, timeout=60) as resp:
                limiter.observe(route, _headers_of(resp))
                return resp.read()
        except HTTPError as exc:
            detail = _read_error_body(exc)
            exc_headers = _headers_of(exc)
            limiter.observe(route, exc_headers)
            code = int(getattr(exc, "code", 0) or 0)
            if code == 429:
                # Discord rejected the call without applying it, so replaying is
                # safe for every method including POST.
                wait, is_global = _retry_after_from_429(detail, exc_headers)
                if rate_limit_left <= 0 or wait > RATE_LIMIT_MAX_WAIT_SECONDS:
                    raise ToolInvocationError(
                        _http_error_text(
                            429,
                            f"retry_after {wait:.3f}s {'global' if is_global else route}"
                            f" {detail}".strip(),
                            token,
                        )
                    ) from None
                rate_limit_left -= 1
                limiter.note_rate_limited(route, wait, is_global=is_global)
                continue
            http_error = ToolInvocationError(_http_error_text(code, detail, token))
            retryable = code in _TRANSIENT_HTTP or (
                idempotent and code in _IDEMPOTENT_RETRY_HTTP
            )
            if not retryable or transient_left <= 0:
                raise http_error from None
            transient_left -= 1
            _retry_sleep(_TRANSIENT_RETRY_SLEEPS[backoff])
            backoff = min(backoff + 1, len(_TRANSIENT_RETRY_SLEEPS) - 1)
        except OSError as exc:
            # TimeoutError is OSError but not URLError on 3.11+; Errno 49
            # (EADDRNOTAVAIL) often arrives as URLError(reason=OSError(49)).
            # URLError is an OSError, so one clause covers both.
            label = transient_network_label(exc)
            if not is_transient_discord_network_error(exc):
                raise ToolInvocationError(
                    f"Discord REST transport failed ({label})"
                ) from exc
            if not idempotent and not request_definitely_not_sent(exc):
                # A timed-out POST may already have posted the card. Replaying
                # it would double-post, so stop and let the caller decide.
                raise ToolInvocationError(
                    f"Discord REST unreachable ({label}) — "
                    f"{method.upper()} not retried, request may have been sent"
                ) from None
            if transient_left <= 0:
                raise ToolInvocationError(
                    f"Discord REST unreachable ({label})"
                ) from None
            transient_left -= 1
            _retry_sleep(_TRANSIENT_RETRY_SLEEPS[backoff])
            backoff = min(backoff + 1, len(_TRANSIENT_RETRY_SLEEPS) - 1)
