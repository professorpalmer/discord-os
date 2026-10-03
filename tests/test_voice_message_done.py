"""Native Discord voice message on Done — opt-in, fail soft, thread only.

Fakes only: the TTS and ffmpeg runners are injected, so no ``say`` / ``ffmpeg``
process ever starts. Audio bytes are hand-built PCM.
"""

from __future__ import annotations

import base64
import struct
from pathlib import Path
from typing import Any, Optional, Sequence

import pytest

from agent_discord.contracts import DiscordMessage
from agent_discord.discord.layout import FLAG_IS_VOICE_MESSAGE
from agent_discord.discord.tts import (
    ENV_VOICE_DONE,
    MAX_VOICE_CHARS,
    VOICE_MESSAGE_FILENAME,
    VOICE_MESSAGE_MIMETYPE,
    WAVEFORM_BYTES,
    WAVEFORM_PCM_RATE,
    maybe_post_voice_done,
    render_voice_done,
    voice_capabilities,
    voice_done_enabled,
    voice_done_tools,
)

OGG_BYTES = b"OggS-fake-opus-payload"


def _pcm(samples: Sequence[int]) -> bytes:
    return b"".join(struct.pack("<h", int(value)) for value in samples)


class FakeTools:
    """Stands in for say/espeak + ffmpeg. Writes the files its argv names."""

    def __init__(
        self,
        *,
        pcm: Optional[bytes] = None,
        ogg: bytes = OGG_BYTES,
        fail_on: str = "",
    ) -> None:
        half = _pcm([0] * (WAVEFORM_PCM_RATE // 2))
        loud = _pcm([32767] * (WAVEFORM_PCM_RATE // 2))
        self.pcm = half + loud if pcm is None else pcm
        self.ogg = ogg
        self.fail_on = fail_on
        self.argvs: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> int:
        parts = [str(part) for part in argv]
        self.argvs.append(parts)
        if self.fail_on and self.fail_on in parts[0]:
            return 1
        out = Path(parts[-1])
        if out.suffix in {".aiff", ".wav"}:
            out.write_bytes(b"FORM-fake-speech")
        elif out.name == VOICE_MESSAGE_FILENAME:
            out.write_bytes(self.ogg)
        elif out.suffix == ".s16le":
            out.write_bytes(self.pcm)
        return 0

    @property
    def spoken_text(self) -> str:
        return self.argvs[0][-1] if self.argvs else ""


class FakeDiscord:
    def __init__(self) -> None:
        self.sends: list[dict[str, Any]] = []

    def send_attachment(
        self,
        channel_id: str,
        filename: str,
        data: bytes,
        *,
        content: str = "",
        thread_id: Optional[str] = None,
        embeds: Optional[list] = None,
        components: Optional[list] = None,
        flags: int = 0,
        attachment_extra: Optional[dict] = None,
        attachment_content_type: str = "",
    ) -> DiscordMessage:
        self.sends.append(
            {
                "channel_id": channel_id,
                "filename": filename,
                "data": data,
                "content": content,
                "thread_id": thread_id,
                "flags": flags,
                "attachment_extra": dict(attachment_extra or {}),
                "attachment_content_type": attachment_content_type,
            }
        )
        return DiscordMessage(channel_id=channel_id, content="", message_id="m1")


ON = {ENV_VOICE_DONE: "1"}
MISSING_SAY = "/nonexistent/say"
MISSING_FFMPEG = "/nonexistent/ffmpeg"


@pytest.fixture()
def clis(tmp_path: Path) -> tuple[str, str]:
    """Executable stubs so tool resolution never depends on the host PATH.

    They are never executed — every test injects ``runner``.
    """

    made: list[str] = []
    for name in ("say", "ffmpeg"):
        path = tmp_path / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
        made.append(str(path))
    return made[0], made[1]


def test_voice_done_off_by_default() -> None:
    assert voice_done_enabled(env={}) is False
    assert voice_done_enabled(env={ENV_VOICE_DONE: "0"}) is False
    assert voice_done_enabled(env={ENV_VOICE_DONE: "1"}) is True
    assert voice_capabilities(env={})["voice_message_done"] is False


def test_render_noop_when_off(clis) -> None:
    say, ffmpeg = clis
    tools = FakeTools()
    assert (
        render_voice_done(
            "Done. Tests passed.",
            env={},
            say_cmd=say,
            ffmpeg_cmd=ffmpeg,
            runner=tools,
        )
        is None
    )
    assert tools.argvs == []


def test_render_produces_ogg_duration_and_waveform(clis) -> None:
    say, ffmpeg = clis
    tools = FakeTools()
    rendered = render_voice_done(
        "Done. Tests passed.",
        env=ON,
        say_cmd=say,
        ffmpeg_cmd=ffmpeg,
        runner=tools,
    )
    assert rendered is not None
    assert rendered.data == OGG_BYTES
    assert rendered.filename == VOICE_MESSAGE_FILENAME
    assert rendered.mimetype == VOICE_MESSAGE_MIMETYPE
    # One second of fake PCM at the probe rate.
    assert rendered.duration_secs == 1.0
    raw = base64.b64decode(rendered.waveform)
    assert 0 < len(raw) <= WAVEFORM_BYTES
    assert min(raw) == 0 and max(raw) == 255

    # Mono 48k Opus for Discord; a separate mono s16le probe for the waveform.
    opus = tools.argvs[1]
    assert "libopus" in opus and "48000" in opus and opus[opus.index("-ac") + 1] == "1"
    probe = tools.argvs[2]
    assert "s16le" in probe and str(WAVEFORM_PCM_RATE) in probe


def test_render_fails_soft_when_tools_missing(clis) -> None:
    say, ffmpeg = clis
    logs: list[str] = []
    for say_cmd, ffmpeg_cmd in ((MISSING_SAY, ffmpeg), (say, MISSING_FFMPEG)):
        tools = FakeTools()
        assert (
            render_voice_done(
                "Done.",
                env=ON,
                say_cmd=say_cmd,
                ffmpeg_cmd=ffmpeg_cmd,
                runner=tools,
                log=logs.append,
            )
            is None
        )
        assert tools.argvs == []
    assert len(logs) == 2
    assert all("not on PATH" in line for line in logs)


def test_render_fails_soft_when_a_tool_exits_nonzero(clis) -> None:
    say, ffmpeg = clis
    logs: list[str] = []
    tools = FakeTools(fail_on="ffmpeg")
    assert (
        render_voice_done(
            "Done.",
            env=ON,
            say_cmd=say,
            ffmpeg_cmd=ffmpeg,
            runner=tools,
            log=logs.append,
        )
        is None
    )
    assert logs and "exited 1" in logs[0]


def test_render_fails_soft_on_silent_audio(clis) -> None:
    say, ffmpeg = clis
    logs: list[str] = []
    tools = FakeTools(pcm=b"")
    assert (
        render_voice_done(
            "Done.",
            env=ON,
            say_cmd=say,
            ffmpeg_cmd=ffmpeg,
            runner=tools,
            log=logs.append,
        )
        is None
    )
    assert logs and "no audio" in logs[0]


def test_render_redacts_and_clips_the_spoken_body(clis) -> None:
    say, ffmpeg = clis
    tools = FakeTools()
    rendered = render_voice_done(
        "Done. <thinking>secret plan</thinking> " + ("long " * 400),
        env=ON,
        say_cmd=say,
        ffmpeg_cmd=ffmpeg,
        runner=tools,
    )
    assert rendered is not None
    spoken = tools.spoken_text
    assert "secret plan" not in spoken
    assert "[redacted]" in spoken
    assert len(spoken) <= MAX_VOICE_CHARS


def test_render_refuses_secret_shaped_text(clis) -> None:
    say, ffmpeg = clis
    logs: list[str] = []
    tools = FakeTools()
    assert (
        render_voice_done(
            "Done. DISCORD_BOT_TOKEN=super-secret-value-here",
            env=ON,
            say_cmd=say,
            ffmpeg_cmd=ffmpeg,
            runner=tools,
            log=logs.append,
        )
        is None
    )
    assert tools.argvs == []
    assert logs and "secrets in argv" in logs[0]


def test_post_sends_one_voice_attachment_into_the_thread(clis) -> None:
    say, ffmpeg = clis
    discord = FakeDiscord()
    tools = FakeTools()
    assert (
        maybe_post_voice_done(
            discord,
            channel_id="ch-1",
            thread_id="thread-9",
            text="Done. Tests passed.",
            env=ON,
            say_cmd=say,
            ffmpeg_cmd=ffmpeg,
            runner=tools,
        )
        is True
    )
    assert len(discord.sends) == 1
    sent = discord.sends[0]
    assert sent["channel_id"] == "ch-1"
    assert sent["thread_id"] == "thread-9"
    assert sent["filename"] == VOICE_MESSAGE_FILENAME
    assert sent["content"] == ""
    assert sent["flags"] == FLAG_IS_VOICE_MESSAGE == 1 << 13
    assert sent["attachment_content_type"] == VOICE_MESSAGE_MIMETYPE
    extra = sent["attachment_extra"]
    assert extra["duration_secs"] == 1.0
    assert base64.b64decode(extra["waveform"])


def test_post_skips_without_a_thread_and_when_off(clis) -> None:
    say, ffmpeg = clis
    discord = FakeDiscord()
    assert (
        maybe_post_voice_done(
            discord,
            channel_id="ch-1",
            thread_id="",
            text="Done.",
            env=ON,
            say_cmd=say,
            ffmpeg_cmd=ffmpeg,
            runner=FakeTools(),
        )
        is False
    )
    assert (
        maybe_post_voice_done(
            discord,
            channel_id="ch-1",
            thread_id="thread-9",
            text="Done.",
            env={},
            say_cmd=say,
            ffmpeg_cmd=ffmpeg,
            runner=FakeTools(),
        )
        is False
    )
    assert discord.sends == []


def test_post_never_raises_when_discord_rejects(clis) -> None:
    say, ffmpeg = clis

    class Angry:
        def send_attachment(self, *_a, **_k):
            raise RuntimeError("413")

    logs: list[str] = []
    assert (
        maybe_post_voice_done(
            Angry(),
            channel_id="ch-1",
            thread_id="thread-9",
            text="Done.",
            env=ON,
            say_cmd=say,
            ffmpeg_cmd=ffmpeg,
            runner=FakeTools(),
            log=logs.append,
        )
        is False
    )
    assert logs and "rejected" in logs[0]


def test_rest_attachment_carries_voice_metadata_and_mimetype() -> None:
    """send_channel_attachment places duration_secs + waveform on attachments[0]."""

    import json

    from agent_discord.discord.rest import send_channel_attachment

    captured: dict[str, Any] = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return json.dumps(
                {"id": "m1", "channel_id": "ch", "content": "", "attachments": []}
            ).encode("utf-8")

    def opener(request, timeout=60):
        captured["body"] = request.data
        return Resp()

    send_channel_attachment(
        token="tok",
        channel_id="ch",
        thread_id="thread-9",
        filename=VOICE_MESSAGE_FILENAME,
        data=OGG_BYTES,
        content="",
        flags=FLAG_IS_VOICE_MESSAGE,
        attachment_extra={"duration_secs": 1.5, "waveform": "AAD/"},
        attachment_content_type=VOICE_MESSAGE_MIMETYPE,
        opener=opener,
    )
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b"Content-Type: audio/ogg" in body
    assert OGG_BYTES in body
    payload = json.loads(
        body.split(b"payload_json")[1].split(b"\r\n\r\n")[1].split(b"\r\n--")[0]
    )
    attachment = payload["attachments"][0]
    assert attachment["filename"] == VOICE_MESSAGE_FILENAME
    assert attachment["duration_secs"] == 1.5
    assert attachment["waveform"] == "AAD/"
    assert payload["flags"] == FLAG_IS_VOICE_MESSAGE


def test_orchestrator_settle_posts_once_and_never_for_cancelled(tmp_path: Path) -> None:
    from agent_discord.contracts import TaskIntake, TaskStatus
    from agent_discord.discord import tts as tts_module
    from agent_discord.discord.facade import DiscordFacade
    from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
    from agent_discord.orchestration.orchestrator import AgentOrchestrator
    from agent_discord.persistence.sqlite import SQLiteStore
    from agent_discord.puppetmaster.fake import FakePuppetmasterBackend

    calls: list[dict[str, Any]] = []
    original = tts_module.post_voice_done_async
    tts_module.post_voice_done_async = lambda discord, **kw: calls.append(kw)
    try:
        store = SQLiteStore(tmp_path / "voice-settle.sqlite3")
        store.initialize()
        facade = DiscordFacade(
            FakeDiscordMCPProvider(), bot_token_fingerprint="fp", owner_id="test"
        )
        orch = AgentOrchestrator(
            store=store,
            backend=FakePuppetmasterBackend(),
            discord=facade,
            post_progress_to_discord=True,
        )
        receipt = orch.run_task(
            TaskIntake(text="what is Discord OS?", channel_id="ch", workspace_id="ws")
        )
        assert receipt.status == TaskStatus.COMPLETED
        assert len(calls) == 1
        assert calls[0]["channel_id"] == "ch"
        assert calls[0]["text"] == receipt.summary

        # Eval runs stay silent.
        calls.clear()
        orch.run_task(
            TaskIntake(
                text="what is Discord OS?",
                channel_id="ch",
                workspace_id="ws",
                metadata={"eval": True},
            )
        )
        assert calls == []

        # Cancelled runs stay silent — the settle guard rewrites to CANCELLED.
        calls.clear()
        orch.backend.status = lambda _run_id: TaskStatus.CANCELLED  # type: ignore[method-assign]
        cancelled = orch.run_task(
            TaskIntake(text="what is Discord OS?", channel_id="ch", workspace_id="ws")
        )
        assert cancelled.status == TaskStatus.CANCELLED
        assert calls == []
        store.close()
    finally:
        tts_module.post_voice_done_async = original


def test_voice_done_tools_reports_readiness(clis) -> None:
    say, _ = clis
    off = voice_done_tools(env={}, say_cmd=MISSING_SAY, ffmpeg_cmd=MISSING_FFMPEG)
    assert off["enabled"] is False
    assert off["ready"] is False
    on = voice_done_tools(env=ON, say_cmd=say, ffmpeg_cmd=MISSING_FFMPEG)
    assert on["enabled"] is True
    assert on["ready"] is False


def test_doctor_reports_the_voice_done_knob(monkeypatch) -> None:
    from agent_discord.host.doctor import _report_voice_done

    monkeypatch.delenv(ENV_VOICE_DONE, raising=False)
    off: list[str] = []
    _report_voice_done(off)
    assert off == [f"OK {ENV_VOICE_DONE} off — no voice message on Done"]

    monkeypatch.setenv(ENV_VOICE_DONE, "1")
    monkeypatch.setattr(
        "agent_discord.discord.tts.voice_done_tools",
        lambda **_k: {
            "enabled": True,
            "tts_cli": "/usr/bin/say",
            "ffmpeg_cli": "",
            "ready": False,
        },
    )
    warn: list[str] = []
    _report_voice_done(warn)
    assert warn[0].startswith(f"WARN {ENV_VOICE_DONE}=1 but ffmpeg not on PATH")

    monkeypatch.setattr(
        "agent_discord.discord.tts.voice_done_tools",
        lambda **_k: {
            "enabled": True,
            "tts_cli": "/usr/bin/say",
            "ffmpeg_cli": "/opt/ffmpeg",
            "ready": True,
        },
    )
    ok: list[str] = []
    _report_voice_done(ok)
    assert ok[0].startswith(f"OK {ENV_VOICE_DONE}=1 voice message on Done")
    assert "/opt/ffmpeg" in ok[0]


def test_doctor_tools_flag_an_ffmpeg_that_does_not_start(tmp_path):
    from agent_discord.discord.tts import voice_done_tools

    say = tmp_path / "say"
    ffmpeg = tmp_path / "ffmpeg"
    for tool in (say, ffmpeg):
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
    env = {"DISCORD_OS_VOICE_DONE": "1"}
    broken = voice_done_tools(
        say_cmd=str(say), ffmpeg_cmd=str(ffmpeg), env=env, runner=lambda argv: -6
    )
    assert broken["ready"] is False and broken["ffmpeg_exit"] == -6
    healthy = voice_done_tools(
        say_cmd=str(say), ffmpeg_cmd=str(ffmpeg), env=env, runner=lambda argv: 0
    )
    assert healthy["ready"] is True
    off = voice_done_tools(say_cmd=str(say), ffmpeg_cmd=str(ffmpeg), env={}, runner=lambda argv: -6)
    assert off["ffmpeg_exit"] is None
