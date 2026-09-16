"""Optional jishaku for Cary tip debugging only. Default OFF. Not a product feature.

Host I/O is REST + a stdlib Gateway so On/Off buttons work. That is not
``discord.ext.commands.Bot``. Jishaku's cog cannot attach without a second
gateway (HARD lock: single gateway). This module gates the optional extra
import and documents that park.

Install: ``pip install discord-os[debug]``.
Enable: ``DISCORD_OS_JISHAKU=1`` **and** invoker is owner / allowlisted
operator. Shared ``REQUIRE_OPERATORS`` demos stay off unless both gates pass.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from agent_discord.orchestration.service import author_is_operator, operators_configured

ENV_JISHAKU = "DISCORD_OS_JISHAKU"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_CMD_RE = re.compile(r"^(?:jsk|jishaku)(?:\s|$)", re.IGNORECASE)

STATUS_OFF = "off"
STATUS_BLOCKED = "blocked"
STATUS_DENIED = "denied"
STATUS_MISSING = "missing"
STATUS_IMPORTABLE = "importable"
STATUS_LOADED = "loaded"

LoadFn = Callable[[], Any]


@dataclass(frozen=True)
class JishakuLoadResult:
    status: str
    reason: str = ""
    loaded: bool = False


def jishaku_flag_on(env: Optional[Mapping[str, str]] = None) -> bool:
    """Explicit opt-in only. Unset / empty / ``0`` / off → False."""

    source = env if env is not None else os.environ
    raw = str(source.get(ENV_JISHAKU) or "").strip().lower()
    return raw in _TRUTHY


def jishaku_available() -> bool:
    try:
        import jishaku  # noqa: F401

        return True
    except Exception:
        return False


def jishaku_operators_ready(store: Any) -> bool:
    return operators_configured(store)


def jishaku_invoker_ok(
    store: Any,
    user_id: Optional[str],
    *,
    role_ids: Optional[Sequence[str]] = None,
) -> bool:
    return author_is_operator(store, user_id, role_ids=role_ids)


def jishaku_may_load(env: Optional[Mapping[str, str]] = None, store: Any = None) -> bool:
    """Process gate: flag on **and** an owner / operator already exists."""

    return jishaku_flag_on(env) and jishaku_operators_ready(store)


def jishaku_may_invoke(
    env: Optional[Mapping[str, str]] = None,
    store: Any = None,
    user_id: Optional[str] = None,
    *,
    role_ids: Optional[Sequence[str]] = None,
) -> bool:
    """Invoke gate: flag on **and** this user is owner / allowlisted operator."""

    return jishaku_flag_on(env) and jishaku_invoker_ok(store, user_id, role_ids=role_ids)


def jishaku_enabled(
    env: Optional[Mapping[str, str]] = None,
    store: Any = None,
    user_id: Optional[str] = None,
    *,
    role_ids: Optional[Sequence[str]] = None,
) -> bool:
    if user_id is not None:
        return jishaku_may_invoke(env, store, user_id, role_ids=role_ids)
    return jishaku_may_load(env, store)


def is_jishaku_command(text: str) -> bool:
    return bool(_CMD_RE.match((text or "").strip()))


def maybe_load_jishaku(
    *,
    env: Optional[Mapping[str, str]] = None,
    store: Any = None,
    user_id: Optional[str] = None,
    role_ids: Optional[Sequence[str]] = None,
    loader: Optional[LoadFn] = None,
) -> JishakuLoadResult:
    """Gated optional load. Never raises into the host loop.

    A real ``loader`` (or a successful ``import jishaku``) marks the extra
    importable. The cog itself stays parked — no ``commands.Bot``, no second
    gateway. CI should pass ``loader`` and must not open a Discord session.
    """

    try:
        if not jishaku_flag_on(env):
            return JishakuLoadResult(STATUS_OFF, reason="flag")
        if not jishaku_operators_ready(store):
            return JishakuLoadResult(STATUS_BLOCKED, reason="owner")
        if user_id is not None and not jishaku_invoker_ok(
            store, user_id, role_ids=role_ids
        ):
            return JishakuLoadResult(STATUS_DENIED, reason="owner")
        if loader is not None:
            loader()
            return JishakuLoadResult(STATUS_LOADED, reason="loader", loaded=True)
        if not jishaku_available():
            return JishakuLoadResult(STATUS_MISSING, reason="extra")
        return JishakuLoadResult(STATUS_IMPORTABLE, reason="parked-cog", loaded=True)
    except Exception as exc:
        print(f"jishaku skipped: {exc}", flush=True)
        return JishakuLoadResult("error", reason=str(exc))


def format_jishaku_line(result: JishakuLoadResult) -> str:
    """Short spoken / log line. Tip-debug only — not product marketing."""

    if result.status == STATUS_OFF:
        return "jishaku off (DISCORD_OS_JISHAKU unset)."
    if result.status == STATUS_BLOCKED:
        return "Denied. jishaku needs an owner / allowlisted operator."
    if result.status == STATUS_DENIED:
        return "Denied. jishaku is owner/operator only."
    if result.status == STATUS_MISSING:
        return (
            "jishaku: tip-debug only. Extra missing. "
            "Cog parked (REST host; no commands.Bot / second gateway)."
        )
    if result.status in {STATUS_IMPORTABLE, STATUS_LOADED}:
        return (
            "jishaku: tip-debug only. Extra importable. "
            "Cog parked (REST host; no commands.Bot / second gateway)."
        )
    return f"jishaku skipped ({result.status})."


def absorb_jishaku_command(
    message: Any,
    *,
    discord: Any,
    store: Any,
    channel_id: str,
    thread_id: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    role_ids: Optional[Sequence[str]] = None,
    loader: Optional[LoadFn] = None,
) -> JishakuLoadResult:
    """Listen path when the flag is on and the text is ``jsk`` / ``jishaku``."""

    result = maybe_load_jishaku(
        env=env,
        store=store,
        user_id=getattr(message, "author_id", None),
        role_ids=role_ids,
        loader=loader,
    )
    _speak(discord, channel_id, thread_id, format_jishaku_line(result))
    return result


def _speak(
    discord: Any, channel_id: str, thread_id: Optional[str], body: str
) -> None:
    try:
        send = getattr(discord, "send_message", None)
        if callable(send):
            send(channel_id, body, thread_id=thread_id)
    except Exception:
        pass
