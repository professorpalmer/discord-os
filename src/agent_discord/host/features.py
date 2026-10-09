"""One switchboard for every opt-in feature.

Each opt-in has its own env flag. That is fine for a first install, but an
operator on a phone cannot edit ``.env``. This module is the one list of the
opt-ins and the one way to turn them on or off. Slash ``/features``, the HOST
panel's More > Features menu, and ``discord-os features`` all call it.

State lives in the SQLite store, which the CLI and the bot share, so a toggle
takes effect on the next listen tick without a restart:

* Host features are a ``feature:<name>`` preference. ``sync_feature_env``
  copies it into ``os.environ`` each tick, so the existing ``*_enabled``
  checks need no change. A stored toggle wins over the ``.env`` value.
* Channel features use the stores their modules already read: the capture
  binding and the PM inbox channel preference.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Optional

from agent_discord.orchestration.service import HOST_PREFS_WORKSPACE

SCOPE_HOST = "host"
SCOPE_CHANNEL = "channel"
_PREF_PREFIX = "feature:"
_TRUTHY = frozenset({"1", "on", "true", "yes"})


@dataclass(frozen=True)
class Feature:
    name: str
    label: str
    summary: str
    scope: str
    env: str


FEATURES: tuple[Feature, ...] = (
    Feature(
        "ci-watch",
        "CI watcher",
        "Red CI on a bound repo posts one card with a Fix CI button",
        SCOPE_HOST,
        "DISCORD_OS_CI_WATCH",
    ),
    Feature(
        "morning",
        "Morning summary",
        "One HOST card a day with overnight results, Needs, and red CI",
        SCOPE_HOST,
        "DISCORD_OS_MORNING",
    ),
    Feature(
        "voice-done",
        "Voice Done",
        "Speak the Done line as a voice message in the job thread",
        SCOPE_HOST,
        "DISCORD_OS_VOICE_DONE",
    ),
    Feature(
        "capture",
        "Capture first",
        "Short thoughts in this channel go to memory instead of a job",
        SCOPE_CHANNEL,
        "DISCORD_OS_CAPTURE_CHANNELS",
    ),
    Feature(
        "pm-inbox",
        "Puppetmaster inbox",
        "Card Puppetmaster jobs started elsewhere in this channel",
        SCOPE_CHANNEL,
        "DISCORD_OS_PM_INBOX_CHANNEL",
    ),
)
FEATURE_NAMES: tuple[str, ...] = tuple(feature.name for feature in FEATURES)


@dataclass(frozen=True)
class FeatureState:
    feature: Feature
    on: bool
    # "toggle" (stored), "env" (from .env, a toggle cannot change it), or "".
    source: str = ""
    note: str = ""

    @property
    def line(self) -> str:
        mark = "on" if self.on else "off"
        tail = f" ({self.note})" if self.note else ""
        return f"{self.feature.label}: {mark}{tail}"


def feature_by_name(name: str) -> Optional[Feature]:
    key = (name or "").strip().lower().replace("_", "-")
    for feature in FEATURES:
        if feature.name == key:
            return feature
    return None


def _pref(store: Any, key: str) -> str:
    reader = getattr(store, "get_preference", None)
    if not callable(reader):
        return ""
    try:
        return str(reader(HOST_PREFS_WORKSPACE, key) or "").strip()
    except Exception:
        return ""


def _set_pref(store: Any, key: str, value: str) -> None:
    writer = getattr(store, "set_preference", None)
    if not callable(writer):
        raise ValueError("this store cannot hold feature toggles")
    writer(HOST_PREFS_WORKSPACE, key, value)


def sync_feature_env(
    store: Any, *, environ: Optional[MutableMapping[str, str]] = None
) -> None:
    """Copy stored host toggles into the process env. Never raises."""

    target = os.environ if environ is None else environ
    for feature in FEATURES:
        if feature.scope != SCOPE_HOST:
            continue
        stored = _pref(store, _PREF_PREFIX + feature.name)
        if stored in {"0", "1"}:
            target[feature.env] = stored


def _env_lists(raw: str, channel_id: str) -> bool:
    return channel_id in {item.strip() for item in (raw or "").split(",")}


def feature_state(
    store: Any,
    feature: Feature,
    *,
    channel_id: str = "",
    workspace_id: str = "default",
    env: Optional[Mapping[str, str]] = None,
) -> FeatureState:
    source_env = os.environ if env is None else env
    if feature.scope == SCOPE_HOST:
        stored = _pref(store, _PREF_PREFIX + feature.name)
        if stored in {"0", "1"}:
            state = FeatureState(feature, stored == "1", "toggle")
        else:
            raw = str(source_env.get(feature.env) or "").strip().lower()
            state = FeatureState(feature, raw in _TRUTHY, "env" if raw else "")
        if feature.name == "voice-done" and state.on:
            from agent_discord.discord.tts import voice_done_tools

            if not voice_done_tools(env={feature.env: "1"}).get("ready"):
                return FeatureState(
                    feature, True, state.source, "needs say or espeak, and ffmpeg"
                )
        return state
    cid = (channel_id or "").strip()
    if feature.name == "capture":
        from agent_discord.orchestration.capture import CAPTURE_ENV, capture_first_enabled

        if str(source_env.get(CAPTURE_ENV) or "").strip().lower() in _TRUTHY:
            return FeatureState(feature, True, "env", f"every channel, {CAPTURE_ENV} in .env")
        if cid and _env_lists(str(source_env.get(feature.env) or ""), cid):
            return FeatureState(feature, True, "env", f"{feature.env} in .env")
        on = bool(cid) and capture_first_enabled(
            store, cid, workspace_id=workspace_id, env={}
        )
        return FeatureState(feature, on, "toggle" if on else "")
    if feature.name == "pm-inbox":
        from agent_discord.orchestration.pm_inbox import PM_INBOX_CHANNEL_PREF

        configured = str(source_env.get(feature.env) or "").strip()
        if configured:
            here = configured == cid
            note = f"{feature.env} in .env" + ("" if here else f", channel {configured}")
            return FeatureState(feature, here, "env", note)
        stored = _pref(store, PM_INBOX_CHANNEL_PREF)
        if not stored:
            return FeatureState(feature, False)
        if stored == cid:
            return FeatureState(feature, True, "toggle")
        return FeatureState(feature, False, "toggle", f"on in channel {stored}")
    return FeatureState(feature, False)


def feature_states(
    store: Any,
    *,
    channel_id: str = "",
    workspace_id: str = "default",
    env: Optional[Mapping[str, str]] = None,
) -> list[FeatureState]:
    return [
        feature_state(
            store, feature, channel_id=channel_id, workspace_id=workspace_id, env=env
        )
        for feature in FEATURES
    ]


def set_feature(
    store: Any,
    name: str,
    on: bool,
    *,
    channel_id: str = "",
    workspace_id: str = "default",
    environ: Optional[MutableMapping[str, str]] = None,
) -> FeatureState:
    """Turn one feature on or off. Raises ``ValueError`` on a bad request.

    A value that only ``.env`` sets cannot be changed here. The returned state
    then names the ``.env`` key, so the operator knows where to look.
    """

    feature = feature_by_name(name)
    if feature is None:
        raise ValueError(f"unknown feature {name!r}; one of: {', '.join(FEATURE_NAMES)}")
    target = os.environ if environ is None else environ
    cid = (channel_id or "").strip()
    if feature.scope == SCOPE_CHANNEL and not cid:
        raise ValueError(f"{feature.name} is per channel; give a channel id")
    if feature.scope == SCOPE_HOST:
        value = "1" if on else "0"
        _set_pref(store, _PREF_PREFIX + feature.name, value)
        target[feature.env] = value
    elif feature.name == "capture":
        from agent_discord.orchestration.capture import CAPTURE_BINDING_KEY

        writer = getattr(store, "merge_binding_metadata", None)
        if not callable(writer):
            raise ValueError("this store cannot hold feature toggles")
        writer(workspace_id or "default", cid, {CAPTURE_BINDING_KEY: bool(on)})
    elif feature.name == "pm-inbox":
        from agent_discord.orchestration.pm_inbox import (
            PM_INBOX_CHANNEL_PREF,
            enable_pm_inbox,
        )

        if on:
            enable_pm_inbox(store, cid)
        elif _pref(store, PM_INBOX_CHANNEL_PREF) == cid:
            _set_pref(store, PM_INBOX_CHANNEL_PREF, "")
    return feature_state(
        store, feature, channel_id=cid, workspace_id=workspace_id, env=target
    )


def format_feature_list(states: list[FeatureState]) -> str:
    lines = ["Features (off by default):"]
    for state in states:
        lines.append(f"- {state.line} - {state.feature.summary}")
    return "\n".join(lines)
