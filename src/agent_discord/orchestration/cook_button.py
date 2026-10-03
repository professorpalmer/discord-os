"""One durable Cook button, shared by the CI wake and the morning summary.

The prompt never rides in the custom id — Discord caps that at 100 characters
and the text would then be whatever GitHub last wrote. The card stores the
prompt in SQLite preferences and the button carries only a token, so a tap
survives a restart and an expired token cooks nothing.

A tap is admitted through ``on_ask`` into JobPool like a typed ask. It is
never pre-approved: the write gate holds it exactly as it holds any other.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional

COOK_ID_PREFIX = "discord-os:cook:"
COOK_PREFERENCE_KEY = "cook_ask"
TOKEN_LEN = 12


@dataclass(frozen=True)
class CookAction:
    """Parsed Cook button intent. Carries no prompt of its own."""

    workspace_id: str
    token: str


def cook_token(seed: str) -> str:
    """Stable short token for a prompt or a head SHA."""

    raw = (seed or "").strip()
    if not raw:
        return ""
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:TOKEN_LEN]


def cook_custom_id(workspace_id: str, token: str) -> str:
    space = (workspace_id or "default").strip()[:32] or "default"
    return f"{COOK_ID_PREFIX}{space}:{(token or '').strip()[:TOKEN_LEN]}"


def parse_cook_custom_id(custom_id: str) -> Optional[CookAction]:
    raw = (custom_id or "").strip()
    if not raw.startswith(COOK_ID_PREFIX):
        return None
    space, _, token = raw[len(COOK_ID_PREFIX) :].partition(":")
    if not space or not token:
        return None
    return CookAction(workspace_id=space, token=token)


def remember_cook_prompt(store: Any, workspace_id: str, token: str, prompt: str) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer) or not token or not prompt:
        return
    try:
        writer(workspace_id or "default", f"{COOK_PREFERENCE_KEY}:{token}", prompt)
    except Exception:
        return


def stored_cook_prompt(store: Any, action: CookAction) -> str:
    reader = getattr(store, "get_preference", None)
    if not callable(reader):
        return ""
    try:
        raw = reader(action.workspace_id, f"{COOK_PREFERENCE_KEY}:{action.token}")
    except Exception:
        return ""
    return str(raw or "").strip()


__all__ = [
    "COOK_ID_PREFIX",
    "COOK_PREFERENCE_KEY",
    "CookAction",
    "cook_custom_id",
    "cook_token",
    "parse_cook_custom_id",
    "remember_cook_prompt",
    "stored_cook_prompt",
]
