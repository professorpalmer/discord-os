"""Local TTS + voice-join stub (P2.13 spike).

Opt-in spoken Done on the listen Mac. Discord gateway voice join is
documented and stubbed fail-closed — no heavy native voice libs, no
Activities, no CDN, no model download.

Env: ``DISCORD_OS_TTS=1`` (default off). Argv lists only. Keys never in argv.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ENV_TTS = "DISCORD_OS_TTS"
SPEAK_TIMEOUT_S = 45
MAX_SPEAK_CHARS = 800

# Prefer macOS ``say``, then espeak variants. Never download a voice pack.
_TTS_COMMANDS = ("say", "espeak-ng", "espeak")

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Assignment / PEM shapes we refuse to place in argv (defense in depth).
_SECRET_ARGV_MARKERS = (
    "DISCORD_BOT_TOKEN=",
    "BOT_TOKEN=",
    "OPENROUTER_API_KEY=",
    "API_KEY=",
    "PASSWORD=",
    "-----BEGIN ",
)

__all__ = [
    "ENV_TTS",
    "SpeakResult",
    "VoiceJoinError",
    "available",
    "join_voice_channel",
    "maybe_speak_done",
    "speak_done",
    "spoken_tts_deny",
    "spoken_voice_join_deny",
    "tts_enabled",
]


@dataclass(frozen=True)
class SpeakResult:
    """Outcome of a TTS or voice-join attempt. Fail closed when not ok."""

    ok: bool
    spoken: str = ""
    attempted: bool = False
    cli: str = ""


class VoiceJoinError(RuntimeError):
    """Voice channel join refused — fail closed, spoken Deny."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.spoken = str(message)


def tts_enabled(*, env: Optional[Mapping[str, str]] = None) -> bool:
    """True only when ``DISCORD_OS_TTS`` is an explicit truthy opt-in."""

    source = dict(os.environ if env is None else env)
    raw = str(source.get(ENV_TTS) or "").strip().lower()
    return raw in _TRUTHY


def available(
    *,
    say_cmd: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """True when TTS is enabled and a local say/espeak CLI resolves."""

    if not tts_enabled(env=env):
        return False
    return _resolve_tts_cmd(say_cmd) is not None


def spoken_tts_deny(*, reason: str = "no local say/espeak CLI on PATH") -> str:
    why = (reason or "unavailable").strip() or "unavailable"
    return f"Denied. TTS is enabled but {why}."


def spoken_voice_join_deny(*, reason: str = "not implemented in this spike") -> str:
    why = (reason or "unavailable").strip() or "unavailable"
    return f"Denied. Voice channel join is {why}."


def speak_done(
    text: str,
    *,
    say_cmd: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> SpeakResult:
    """Speak a Done / spoken reply string when ``DISCORD_OS_TTS`` is on.

    Off by default → no-op (``ok=True``, ``attempted=False``).
    Enabled but missing CLI → fail closed with spoken Deny (no raise).
    Invokes argv lists only — never ``shell=True``, never puts tokens or
    env keys into argv.
    """

    if not tts_enabled(env=env):
        return SpeakResult(ok=True, spoken="", attempted=False)

    body = _sanitize_speak_text(text)
    if not body:
        return SpeakResult(ok=True, spoken="", attempted=False)

    cli = _resolve_tts_cmd(say_cmd)
    if cli is None:
        deny = spoken_tts_deny()
        return SpeakResult(ok=False, spoken=deny, attempted=True, cli="")

    argv = _speak_argv(cli, body)
    if _argv_looks_like_secrets(argv):
        deny = spoken_tts_deny(reason="refusing to place secrets in argv")
        return SpeakResult(ok=False, spoken=deny, attempted=True, cli=cli)

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=SPEAK_TIMEOUT_S,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        deny = spoken_tts_deny(reason="local TTS CLI failed")
        return SpeakResult(ok=False, spoken=deny, attempted=True, cli=cli)

    if proc.returncode != 0:
        deny = spoken_tts_deny(reason="local TTS CLI exited non-zero")
        return SpeakResult(ok=False, spoken=deny, attempted=True, cli=cli)

    return SpeakResult(ok=True, spoken="", attempted=True, cli=cli)


def maybe_speak_done(
    text: str,
    *,
    say_cmd: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> SpeakResult:
    """Best-effort orchestrator hook. Never raises."""

    try:
        return speak_done(text, say_cmd=say_cmd, env=env)
    except Exception:
        return SpeakResult(
            ok=False,
            spoken=spoken_tts_deny(reason="unexpected error"),
            attempted=True,
        )


def join_voice_channel(
    guild_id: Any = "",
    channel_id: Any = "",
    *,
    env: Optional[Mapping[str, str]] = None,
    raise_on_deny: bool = False,
) -> SpeakResult:
    """Stub: Discord gateway voice join is deferred (see docs/host/voice.md).

    Always fail closed. Does not open a gateway, UDP socket, or load Opus /
    NaCl. ``DISCORD_OS_TTS`` does not unlock join — that is a separate,
    heavier surface.
    """

    _ = env  # reserved for a future explicit DISCORD_OS_VOICE_JOIN opt-in
    guild = str(guild_id or "").strip()
    channel = str(channel_id or "").strip()
    if not guild or not channel:
        deny = spoken_voice_join_deny(reason="missing guild or channel id")
    else:
        deny = spoken_voice_join_deny(
            reason="not implemented (gateway voice + Opus/UDP deferred)"
        )
    if raise_on_deny:
        raise VoiceJoinError(deny)
    return SpeakResult(ok=False, spoken=deny, attempted=True)


def _sanitize_speak_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    collapsed = " ".join(raw.split())
    if len(collapsed) > MAX_SPEAK_CHARS:
        collapsed = collapsed[: MAX_SPEAK_CHARS - 1].rstrip() + "…"
    return collapsed


def _resolve_tts_cmd(say_cmd: Optional[str]) -> Optional[str]:
    if say_cmd:
        return _executable_path(say_cmd)
    for name in _TTS_COMMANDS:
        found = _executable_path(name)
        if found is not None:
            return found
    return None


def _executable_path(command: str) -> Optional[str]:
    """Resolve a single executable name or path. Never split on spaces."""

    name = (command or "").strip()
    if not name:
        return None
    found = shutil.which(name)
    if found:
        return found
    candidate = Path(name)
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _speak_argv(cli: str, text: str) -> list[str]:
    """Build argv for say / espeak. Text is one argv element — never shell."""

    name = Path(cli).name.lower()
    if name in {"espeak", "espeak-ng"}:
        return [cli, text]
    return [cli, text]


def _argv_looks_like_secrets(argv: Sequence[str]) -> bool:
    for part in argv[1:]:  # skip the binary path
        upper = str(part).upper()
        for marker in _SECRET_ARGV_MARKERS:
            if marker.upper() in upper:
                return True
    return False
