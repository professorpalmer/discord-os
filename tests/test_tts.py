"""Local TTS + Discord voice join honesty — off by default, fail closed."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_discord.discord.layout import voice_state_update
from agent_discord.discord.tts import (
    DAVE_REQUIRED_SINCE,
    ENV_TTS,
    ENV_VOICE_JOIN,
    VOICE_CLOSE_DAVE_REQUIRED,
    VoiceJoinError,
    available,
    join_voice_channel,
    leave_voice_channel,
    listen_in_voice_channel,
    maybe_speak_done,
    speak_done,
    speak_in_voice_channel,
    spoken_tts_deny,
    spoken_voice_join_deny,
    spoken_voice_listen_deny,
    spoken_voice_speak_deny,
    tts_enabled,
    voice_capabilities,
    voice_join_enabled,
)


def test_tts_off_by_default() -> None:
    assert tts_enabled(env={}) is False
    assert tts_enabled(env={ENV_TTS: ""}) is False
    assert tts_enabled(env={ENV_TTS: "0"}) is False
    assert tts_enabled(env={ENV_TTS: "false"}) is False
    assert available(env={}) is False
    assert available(env={ENV_TTS: "0"}, say_cmd="/usr/bin/say") is False


def test_tts_opt_in_truthy() -> None:
    assert tts_enabled(env={ENV_TTS: "1"}) is True
    assert tts_enabled(env={ENV_TTS: "true"}) is True
    assert tts_enabled(env={ENV_TTS: "YES"}) is True
    assert tts_enabled(env={ENV_TTS: "on"}) is True


def test_speak_done_noop_when_off(monkeypatch) -> None:
    calls: list = []

    def boom(*_a, **_k):
        calls.append(True)
        raise AssertionError("subprocess must not run when TTS is off")

    monkeypatch.setattr("agent_discord.discord.tts.subprocess.run", boom)
    result = speak_done("Done. Tests passed.", env={})
    assert result.ok is True
    assert result.attempted is False
    assert result.spoken == ""
    assert calls == []


def test_speak_done_missing_cli_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_discord.discord.tts.shutil.which",
        lambda _name: None,
    )
    recorded: list = []

    def boom(*_a, **_k):
        recorded.append(True)
        raise AssertionError("subprocess must not run without a CLI")

    monkeypatch.setattr("agent_discord.discord.tts.subprocess.run", boom)
    result = speak_done(
        "Done. Tests passed.",
        env={ENV_TTS: "1"},
        say_cmd="discord-os-missing-say-cli",
    )
    assert result.ok is False
    assert result.attempted is True
    assert "Denied" in result.spoken
    assert "say" in result.spoken.lower() or "espeak" in result.spoken.lower()
    assert recorded == []
    assert available(env={ENV_TTS: "1"}, say_cmd="discord-os-missing-say-cli") is False


def test_speak_done_uses_argv_list_no_shell(monkeypatch, tmp_path: Path) -> None:
    fake = tmp_path / "fake-say"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    recorded: dict = {}

    def fake_run(argv, **kwargs):
        recorded["argv"] = list(argv)
        recorded["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("agent_discord.discord.tts.subprocess.run", fake_run)
    result = speak_done(
        "Done. The PR is green.",
        env={ENV_TTS: "1"},
        say_cmd=str(fake),
    )
    assert result.ok is True
    assert result.attempted is True
    assert recorded["argv"][0] == str(fake)
    assert "Done. The PR is green." in recorded["argv"]
    assert recorded["kwargs"].get("shell") is False
    # Keys never in argv — only cli + utterance.
    assert len(recorded["argv"]) == 2
    joined = " ".join(recorded["argv"])
    assert "DISCORD_BOT_TOKEN" not in joined
    assert "OPENROUTER" not in joined


def test_speak_done_refuses_secret_shaped_utterance(monkeypatch, tmp_path: Path) -> None:
    fake = tmp_path / "fake-say"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    calls: list = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("agent_discord.discord.tts.subprocess.run", fake_run)
    result = speak_done(
        "leak DISCORD_BOT_TOKEN=super-secret-value-here",
        env={ENV_TTS: "1"},
        say_cmd=str(fake),
    )
    assert result.ok is False
    assert "Denied" in result.spoken
    assert calls == []


def test_maybe_speak_done_never_raises(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("explode")

    monkeypatch.setattr("agent_discord.discord.tts.speak_done", boom)
    result = maybe_speak_done("x", env={ENV_TTS: "1"})
    assert result.ok is False
    assert "Denied" in result.spoken


def test_join_voice_channel_fail_closed() -> None:
    result = join_voice_channel("guild", "voice-ch")
    assert result.ok is False
    assert result.attempted is True
    assert "Denied" in result.spoken
    assert "dave" in result.spoken.lower() or DAVE_REQUIRED_SINCE in result.spoken

    missing = join_voice_channel("", "")
    assert missing.ok is False
    assert "Denied" in missing.spoken

    # TTS opt-in does not unlock join.
    still = join_voice_channel("g", "c", env={ENV_TTS: "1"})
    assert still.ok is False

    try:
        join_voice_channel("g", "c", raise_on_deny=True)
        raise AssertionError("expected VoiceJoinError")
    except VoiceJoinError as exc:
        assert "Denied" in exc.spoken


def test_join_voice_channel_opt_in_still_deny_dave() -> None:
    assert voice_join_enabled(env={ENV_VOICE_JOIN: "1"}) is True
    reserved = join_voice_channel("g", "c", env={ENV_VOICE_JOIN: "1"})
    assert reserved.ok is False
    spoken = reserved.spoken.lower()
    assert "denied" in spoken
    assert "not an unlock" in spoken or "dave" in spoken
    assert str(VOICE_CLOSE_DAVE_REQUIRED) in reserved.spoken or "4017" in reserved.spoken

    # Injected gateway_send must not be called (no half-wired Opcode 4).
    calls: list = []

    def send(_payload):
        calls.append(_payload)
        raise AssertionError("must not send voice state without DAVE")

    denied = join_voice_channel(
        "g",
        "c",
        env={ENV_VOICE_JOIN: "1"},
        gateway_send=send,
    )
    assert denied.ok is False
    assert calls == []


def test_leave_voice_channel_idle_noop() -> None:
    left = leave_voice_channel("guild")
    assert left.ok is True
    assert left.attempted is False
    assert left.spoken == ""

    left_opt = leave_voice_channel("guild", env={ENV_VOICE_JOIN: "1"})
    assert left_opt.ok is True
    assert left_opt.attempted is False


def test_speak_and_listen_in_voice_parked() -> None:
    speak = speak_in_voice_channel("hello", guild_id="g", channel_id="c")
    assert speak.ok is False
    assert "Denied" in speak.spoken
    assert "parked" in speak.spoken.lower() or "dave" in speak.spoken.lower()

    listen = listen_in_voice_channel(guild_id="g", channel_id="c")
    assert listen.ok is False
    assert "Denied" in listen.spoken

    try:
        speak_in_voice_channel("x", raise_on_deny=True)
        raise AssertionError("expected VoiceJoinError")
    except VoiceJoinError as exc:
        assert "Denied" in exc.spoken


def test_voice_capabilities_matrix() -> None:
    caps = voice_capabilities(env={ENV_VOICE_JOIN: "1", ENV_TTS: "1"})
    assert caps["voice_join"] is False
    assert caps["voice_speak"] is False
    assert caps["voice_listen"] is False
    assert caps["voice_join_opt_in"] is True
    assert caps["local_tts"] is True
    assert caps["local_voice_memos"] is True
    assert caps["computer_use"] is False
    assert caps["dave_required_since"] == DAVE_REQUIRED_SINCE
    assert caps["dave_close_code"] == VOICE_CLOSE_DAVE_REQUIRED


def test_voice_state_update_payload_only() -> None:
    join = voice_state_update("111", "222", self_mute=True, self_deaf=True)
    assert join["op"] == 4
    assert join["d"]["guild_id"] == "111"
    assert join["d"]["channel_id"] == "222"
    assert join["d"]["self_mute"] is True
    assert join["d"]["self_deaf"] is True

    leave = voice_state_update("111", None)
    assert leave["op"] == 4
    assert leave["d"]["channel_id"] is None


def test_spoken_deny_helpers() -> None:
    assert spoken_tts_deny().startswith("Denied.")
    assert spoken_voice_join_deny().startswith("Denied.")
    assert "dave" in spoken_voice_join_deny().lower() or DAVE_REQUIRED_SINCE in spoken_voice_join_deny()
    assert spoken_voice_speak_deny().startswith("Denied.")
    assert spoken_voice_listen_deny().startswith("Denied.")
