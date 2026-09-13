"""Local TTS + Discord voice-channel join honesty (beyond P2.13 stub).

Opt-in spoken Done on the listen Mac (local ``say`` / espeak). Discord
**voice-channel join** is investigated against the live bot API:

- Gateway Opcode 4 + voice WebSocket + UDP are required to stay in channel.
- Since 2026-03-01 Discord requires **DAVE E2EE** (libdave / MLS) for guild
  voice; non-DAVE clients get voice close **4017**.
- Discord OS is REST-first, stdlib gateway for HOST buttons only — no
  discord.py voice client, no libdave, no Opus speak/listen path, no
  computer-use / desk fantasy.

Therefore ``join_voice_channel`` / Discord speak / Discord listen **fail
closed** with spoken Deny. ``leave_voice_channel`` is an idle no-op (we never
hold a live voice session). Local Mac TTS and inbound voice-memo whisper
remain separate and unchanged.

Env: ``DISCORD_OS_TTS=1`` (default off). ``DISCORD_OS_VOICE_JOIN=1`` is an
explicit opt-in **intent** knob — still Deny until DAVE ships (not an unlock).
Argv lists only. Keys never in argv.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ENV_TTS = "DISCORD_OS_TTS"
ENV_VOICE_JOIN = "DISCORD_OS_VOICE_JOIN"
SPEAK_TIMEOUT_S = 45
MAX_SPEAK_CHARS = 800

# Discord voice E2EE mandate (public docs / close code 4017).
DAVE_REQUIRED_SINCE = "2026-03-01"
VOICE_CLOSE_DAVE_REQUIRED = 4017

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
    "DAVE_REQUIRED_SINCE",
    "ENV_TTS",
    "ENV_VOICE_JOIN",
    "SpeakResult",
    "VOICE_CLOSE_DAVE_REQUIRED",
    "VoiceJoinError",
    "available",
    "join_voice_channel",
    "leave_voice_channel",
    "listen_in_voice_channel",
    "maybe_speak_done",
    "speak_done",
    "speak_in_voice_channel",
    "spoken_tts_deny",
    "spoken_voice_join_deny",
    "spoken_voice_listen_deny",
    "spoken_voice_speak_deny",
    "tts_enabled",
    "voice_capabilities",
    "voice_join_enabled",
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


def voice_join_enabled(*, env: Optional[Mapping[str, str]] = None) -> bool:
    """True when ``DISCORD_OS_VOICE_JOIN`` is truthy (intent only — not unlock)."""

    source = dict(os.environ if env is None else env)
    raw = str(source.get(ENV_VOICE_JOIN) or "").strip().lower()
    return raw in _TRUTHY


def voice_capabilities(*, env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Honest matrix for doctor / docs. No network."""

    return {
        "local_tts": tts_enabled(env=env),
        "voice_join_opt_in": voice_join_enabled(env=env),
        "voice_join": False,
        "voice_leave_live": False,
        "voice_speak": False,
        "voice_listen": False,
        "dave_required_since": DAVE_REQUIRED_SINCE,
        "dave_close_code": VOICE_CLOSE_DAVE_REQUIRED,
        "blocker": (
            f"Discord DAVE E2EE required since {DAVE_REQUIRED_SINCE} "
            f"(voice close {VOICE_CLOSE_DAVE_REQUIRED}); Discord OS does not "
            "ship libdave / voice UDP / Opus duplex"
        ),
        "local_voice_memos": True,
        "computer_use": False,
    }


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


def spoken_voice_join_deny(*, reason: str = "") -> str:
    why = (reason or "").strip() or (
        f"blocked — Discord requires DAVE E2EE voice since {DAVE_REQUIRED_SINCE} "
        f"(close {VOICE_CLOSE_DAVE_REQUIRED}); Discord OS does not ship libdave / "
        "voice UDP"
    )
    return (
        f"Denied. Voice channel join is {why}. "
        "No lasting guild voice session in this build — spoken Deny only "
        "(not computer-use / desk)."
    )


def spoken_voice_speak_deny(*, reason: str = "") -> str:
    why = (reason or "").strip() or (
        "parked — Discord voice speak needs DAVE + Opus duplex; phone-remote "
        "model keeps full-duplex TTS out of guild voice"
    )
    return f"Denied. Voice channel speak is {why}."


def spoken_voice_listen_deny(*, reason: str = "") -> str:
    why = (reason or "").strip() or (
        "parked — Discord voice listen needs DAVE + Opus decode; use voice "
        "memo attachments + local whisper for intake instead"
    )
    return f"Denied. Voice channel listen is {why}."


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
    env keys into argv. Local Mac speakers only — not Discord guild voice.
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
    gateway_send: Optional[Any] = None,
) -> SpeakResult:
    """Best-effort guild voice join — fail closed without DAVE.

    Discord's bot API can join voice in principle (Gateway Opcode 4 → voice
    WS → UDP). Lasting join since ``DAVE_REQUIRED_SINCE`` requires libdave.
    This product does not ship that stack, does not half-wire Opcode 4 alone
    (drops / fantasy), and does not use computer-use or a desk GUI.

    ``DISCORD_OS_TTS`` does not unlock join. ``DISCORD_OS_VOICE_JOIN`` marks
    operator intent but is still an honest Deny (not an unlock).
    ``gateway_send`` is accepted for forward wiring and ignored — we refuse
    to send a half-open voice state without DAVE completion.
    """

    _ = gateway_send  # intentional: no half-wired Opcode 4 without DAVE
    source = dict(os.environ if env is None else env)
    guild = str(guild_id or "").strip()
    channel = str(channel_id or "").strip()
    join_opt = voice_join_enabled(env=source)
    if not guild or not channel:
        deny = spoken_voice_join_deny(reason="missing guild or channel id")
    elif join_opt:
        deny = spoken_voice_join_deny(
            reason=(
                f"{ENV_VOICE_JOIN}=1 is set but join requires Discord DAVE E2EE "
                f"(mandatory since {DAVE_REQUIRED_SINCE}, close "
                f"{VOICE_CLOSE_DAVE_REQUIRED}); Discord OS does not ship "
                "libdave / voice UDP / Opus — still Deny, not an unlock"
            )
        )
    else:
        deny = spoken_voice_join_deny(
            reason=(
                f"opt-in required ({ENV_VOICE_JOIN}=1) and DAVE E2EE voice is "
                f"not shipped (required since {DAVE_REQUIRED_SINCE})"
            )
        )
    if raise_on_deny:
        raise VoiceJoinError(deny)
    return SpeakResult(ok=False, spoken=deny, attempted=True)


def leave_voice_channel(
    guild_id: Any = "",
    *,
    env: Optional[Mapping[str, str]] = None,
    raise_on_deny: bool = False,
    gateway_send: Optional[Any] = None,
) -> SpeakResult:
    """Leave guild voice — idle no-op because we never hold a live session.

    When a future DAVE transport lands, this will send Opcode 4 with
    ``channel_id=null`` via ``gateway_send``. Today: succeed as idle
    (``ok=True``, ``attempted=False``) so callers can always clear local
    intent without lying about a Discord disconnect.
    """

    _ = (guild_id, env, gateway_send, raise_on_deny)
    return SpeakResult(ok=True, spoken="", attempted=False)


def speak_in_voice_channel(
    text: str = "",
    *,
    guild_id: Any = "",
    channel_id: Any = "",
    env: Optional[Mapping[str, str]] = None,
    raise_on_deny: bool = False,
) -> SpeakResult:
    """Discord guild-voice speak — parked Deny (not local Mac TTS)."""

    _ = (text, guild_id, channel_id, env)
    deny = spoken_voice_speak_deny()
    if raise_on_deny:
        raise VoiceJoinError(deny)
    return SpeakResult(ok=False, spoken=deny, attempted=True)


def listen_in_voice_channel(
    *,
    guild_id: Any = "",
    channel_id: Any = "",
    env: Optional[Mapping[str, str]] = None,
    raise_on_deny: bool = False,
) -> SpeakResult:
    """Discord guild-voice listen/STT — parked Deny (use voice memos)."""

    _ = (guild_id, channel_id, env)
    deny = spoken_voice_listen_deny()
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
