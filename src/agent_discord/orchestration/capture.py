"""Capture-first intake — a thought is not a job.

Production receipt behind this: 10 of 43 jobs were dismissed, and many of the
asks were thoughts ("PM routing should prefer X", "Freese FAQ still waits"),
not work. Every channel sentence became a paid cook.

With capture-first armed on a channel, a short declarative top-level message is
written to host memory, reacted to once, and left alone. No card, no job, no
spend. The capture comes back through ordinary memory recall, so a later ask on
that channel carries it as context.

OFF by default. The live host keeps "a sentence is a task" until the operator
turns this on: ``DISCORD_OS_CAPTURE_FIRST=1`` globally, or
``discord-os add capture --channel-id ID`` for one channel.

Escape hatch in both directions: ``do:`` / ``cook:`` always cooks, and job
threads are never captured — a reply in a job thread steers or cooks exactly as
it did before.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from agent_discord.host.realms import binding_metadata
from agent_discord.redaction import redact_text_markers

CAPTURE_ENV = "DISCORD_OS_CAPTURE_FIRST"
CAPTURE_CHANNELS_ENV = "DISCORD_OS_CAPTURE_CHANNELS"
CAPTURE_BINDING_KEY = "capture_first"

CAPTURE_SOURCE = "capture"
# Bookmark. A reaction is the whole acknowledgement: no card, no thread.
CAPTURE_REACTION = "\N{BOOKMARK}"
CAPTURE_MAX_CHARS = 140
CAPTURE_CONTENT_MAX = 500

# One place. The classifier and the docs page both read this list.
IMPERATIVE_VERBS = (
    "add",
    "apply",
    "build",
    "bump",
    "cancel",
    "check",
    "clean",
    "commit",
    "connect",
    "cook",
    "create",
    "debug",
    "delete",
    "deploy",
    "diagnose",
    "do",
    "document",
    "draft",
    "explain",
    "find",
    "fix",
    "generate",
    "implement",
    "install",
    "investigate",
    "land",
    "list",
    "make",
    "merge",
    "migrate",
    "move",
    "open",
    "patch",
    "publish",
    "pull",
    "push",
    "refactor",
    "release",
    "remove",
    "rename",
    "repair",
    "replace",
    "research",
    "review",
    "revert",
    "rewrite",
    "run",
    "ship",
    "show",
    "split",
    "summarize",
    "sync",
    "tag",
    "test",
    "update",
    "upgrade",
    "verify",
    "write",
)

COOK_PREFIXES = ("do:", "cook:")

_IMPERATIVE_RE = re.compile(r"^(?:" + "|".join(IMPERATIVE_VERBS) + r")\b", re.IGNORECASE)
# A request wrapper around an imperative is still work: "can you fix the card".
_LEAD_RE = re.compile(
    r"""^(?:
        <@!?\d+>\s*
        | <@&\d+>\s*
        | please\s+ | pls\s+ | hey\s+ | yo\s+ | ok\s+ | okay\s+
        | can\s+you\s+ | could\s+you\s+ | would\s+you\s+ | will\s+you\s+
        | go\s+(?:ahead\s+and\s+)? | let's\s+ | lets\s+
        | (?:i\s+)?need\s+you\s+to\s+ | i\s+want\s+you\s+to\s+
    )+""",
    re.IGNORECASE | re.VERBOSE,
)
_PREFIX_COMMAND_CHARS = ("/", "!")


@dataclass(frozen=True)
class IntakeDecision:
    """What intake should do with one message, and the text to use."""

    capture: bool
    text: str
    reason: str


def strip_cook_prefix(text: str) -> tuple[bool, str]:
    """``do:`` / ``cook:`` forces a cook. Returns (forced, text without prefix)."""

    raw = (text or "").strip()
    lowered = raw.lower()
    for prefix in COOK_PREFIXES:
        if lowered.startswith(prefix):
            return True, raw[len(prefix) :].strip()
    return False, raw


def looks_like_command(text: str) -> bool:
    """Prefix commands and the host verbs are never captures."""

    raw = (text or "").strip()
    if not raw:
        return False
    if raw[0] in _PREFIX_COMMAND_CHARS:
        return True
    from agent_discord.host.memory import MEMORY_PREFIXES
    from agent_discord.host.power import is_power_command
    from agent_discord.host.realms import is_bind_command
    from agent_discord.host.verbs import is_open_command
    from agent_discord.keys.connect import is_connect_command
    from agent_discord.orchestration.service import (
        parse_claim_command,
        parse_handoff_command,
        parse_schedule_command,
    )

    if is_connect_command(raw) or is_bind_command(raw) or is_power_command(raw):
        return True
    if is_open_command(raw):
        return True
    if parse_schedule_command(raw) is not None:
        return True
    if parse_claim_command(raw) is not None:
        return True
    if parse_handoff_command(raw) is not None:
        return True
    first = raw.split()[0].lower()
    if first in MEMORY_PREFIXES or first in {"jishaku", "jsk"}:
        return True
    return False


def classify_intake(
    text: str,
    *,
    capture_first: bool,
    in_job_thread: bool = False,
) -> IntakeDecision:
    """Capture or cook. Pure — the channel opt-in is decided by the caller."""

    forced, body = strip_cook_prefix(text)
    if forced:
        return IntakeDecision(capture=False, text=body, reason="forced")
    if not capture_first:
        return IntakeDecision(capture=False, text=body, reason="off")
    if in_job_thread:
        return IntakeDecision(capture=False, text=body, reason="job-thread")
    if not body:
        return IntakeDecision(capture=False, text=body, reason="empty")
    if looks_like_command(body):
        return IntakeDecision(capture=False, text=body, reason="command")
    if len(body) >= CAPTURE_MAX_CHARS:
        return IntakeDecision(capture=False, text=body, reason="long")
    if _IMPERATIVE_RE.match(_LEAD_RE.sub("", body).lstrip()):
        return IntakeDecision(capture=False, text=body, reason="imperative")

    from agent_discord.host.repo_status import is_repo_status_ask

    if is_repo_status_ask(body):
        return IntakeDecision(capture=False, text=body, reason="repo-status")
    return IntakeDecision(capture=True, text=body, reason="capture")


def capture_first_enabled(
    store: Any = None,
    channel_id: str = "",
    *,
    workspace_id: str = "default",
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """Global env flag, the named-channel env list, or the channel binding."""

    source = dict(os.environ if env is None else env)
    if _truthy(source.get(CAPTURE_ENV)):
        return True
    cid = str(channel_id or "").strip()
    if cid and cid in _split_ids(source.get(CAPTURE_CHANNELS_ENV) or ""):
        return True
    if store is None or not cid:
        return False
    reader = getattr(store, "get_binding", None)
    if callable(reader):
        try:
            meta = binding_metadata(reader(workspace_id, cid))
        except Exception:
            meta = {}
        if meta.get(CAPTURE_BINDING_KEY):
            return True
    return False


def enable_capture_channel(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
) -> bool:
    writer = getattr(store, "merge_binding_metadata", None)
    cid = str(channel_id or "").strip()
    if not callable(writer) or not cid:
        return False
    writer(workspace_id or "default", cid, {CAPTURE_BINDING_KEY: True})
    return True


def capture_channel_ids(
    store: Any = None,
    *,
    workspace_id: str = "default",
    env: Optional[Mapping[str, str]] = None,
) -> tuple[str, ...]:
    source = dict(os.environ if env is None else env)
    seen: list[str] = []
    known: set[str] = set()
    for cid in _split_ids(source.get(CAPTURE_CHANNELS_ENV) or ""):
        if cid not in known:
            seen.append(cid)
            known.add(cid)
    lister = getattr(store, "list_bindings", None)
    if callable(lister):
        try:
            rows = list(lister(workspace_id) or ())
        except Exception:
            rows = []
        for row in rows:
            cid = str(row.get("channel_id") or "").strip()
            if cid and cid not in known and binding_metadata(row).get(CAPTURE_BINDING_KEY):
                seen.append(cid)
                known.add(cid)
    return tuple(seen)


def message_link(guild_id: str, channel_id: str, message_id: str) -> str:
    """Discord jump link. ``@me`` when the guild is unknown (DM shape)."""

    cid = str(channel_id or "").strip()
    mid = str(message_id or "").strip()
    if not cid or not mid:
        return ""
    guild = str(guild_id or "").strip() or "@me"
    return f"https://discord.com/channels/{guild}/{cid}/{mid}"


def record_capture(
    store: Any,
    *,
    workspace_id: str,
    channel_id: str,
    text: str,
    author_id: str = "",
    message_id: str = "",
    guild_id: str = "",
) -> str:
    """Write one capture into host memory. Redacted, cited, recallable."""

    remember = getattr(store, "remember", None)
    body = redact_text_markers((text or "").strip())[:CAPTURE_CONTENT_MAX]
    if not callable(remember) or not body:
        return ""
    citation = message_link(guild_id, channel_id, message_id)
    try:
        return str(
            remember(
                workspace_id=workspace_id or "default",
                channel_id=str(channel_id or ""),
                content=body,
                source=CAPTURE_SOURCE,
                provenance={
                    "citation": citation,
                    "author": str(author_id or ""),
                    "channel_id": str(channel_id or ""),
                    "message_id": str(message_id or ""),
                },
            )
            or ""
        )
    except Exception:
        return ""


def acknowledge_capture(discord: Any, channel_id: str, message_id: str) -> bool:
    """One reaction. Best-effort: a missing reaction never loses the capture."""

    react = getattr(discord, "add_reaction", None)
    if not callable(react) or not channel_id or not message_id:
        return False
    try:
        react(channel_id, message_id, CAPTURE_REACTION)
    except Exception:
        return False
    return True


def _truthy(raw: Any) -> bool:
    value = str(raw or "").strip().lower()
    return value in {"1", "on", "true", "yes"}


def _split_ids(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(raw or "").split(",") if part.strip())


__all__ = [
    "CAPTURE_BINDING_KEY",
    "CAPTURE_CHANNELS_ENV",
    "CAPTURE_CONTENT_MAX",
    "CAPTURE_ENV",
    "CAPTURE_MAX_CHARS",
    "CAPTURE_REACTION",
    "CAPTURE_SOURCE",
    "COOK_PREFIXES",
    "IMPERATIVE_VERBS",
    "IntakeDecision",
    "acknowledge_capture",
    "capture_channel_ids",
    "capture_first_enabled",
    "classify_intake",
    "enable_capture_channel",
    "looks_like_command",
    "message_link",
    "record_capture",
    "strip_cook_prefix",
]
