"""P2.13 local TTS + voice-join stub — off by default, fail closed."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_discord.discord.tts import (
    ENV_TTS,
    VoiceJoinError,
    available,
    join_voice_channel,
    maybe_speak_done,
    speak_done,
    spoken_tts_deny,
    spoken_voice_join_deny,
    tts_enabled,
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
    assert "not implemented" in result.spoken.lower() or "deferred" in result.spoken.lower()

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


def test_spoken_deny_helpers() -> None:
    assert spoken_tts_deny().startswith("Denied.")
    assert spoken_voice_join_deny().startswith("Denied.")
