# Voice join + TTS (beyond P2.13)

Turn it on or off with `/features`, HOST More > Features, or
`discord-os features on voice-done`. See [features](features.md).

Thin surface. Local spoken Done on the listen Mac is opt-in. Discord
**guild voice-channel join** was re-checked against the live bot API for the
phone-remote model. Result: **fail closed** — no lasting join without DAVE.

No Discord Activities. No CDN. No model download. No computer-use / desk GUI.
No Automaton. No heavy native voice stack (`libdave`, Opus duplex, discord.py
voice) required to install or run Discord OS.

Voice **memos** (attachment → local whisper → intake) already live in
`discord/voice.py`. This page is outbound local speech + guild voice honesty.

## What ships

| Piece | Behavior |
|---|---|
| Env opt-in TTS | `DISCORD_OS_TTS=1` (also `true` / `yes` / `on`). **Default off.** |
| Local TTS | `say` (macOS) or `espeak` / `espeak-ng` on PATH. Argv lists only. Mac speakers — **not** guild voice. |
| Done hook | `maybe_speak_done(summary)` after a settle — best-effort, never raises. |
| Env opt-in voice message | `DISCORD_OS_VOICE_DONE=1`. **Default off.** Posts the Done summary as a native Discord **voice message** in the job thread. |
| Voice join | `join_voice_channel(guild_id, channel_id)` → spoken **Deny**. Always (see DAVE). |
| Voice leave | `leave_voice_channel(guild_id)` → idle **no-op** (`ok=True`, not attempted) — we never hold a live session. |
| Guild speak / listen | `speak_in_voice_channel` / `listen_in_voice_channel` → parked **Deny** (no duplex TTS/STT in guild voice). |
| `DISCORD_OS_VOICE_JOIN` | Intent knob. Truthy still **Deny** (not an unlock) until DAVE ships. |
| Payload helper | `layout.voice_state_update` builds Gateway Opcode 4 JSON only — does **not** send. |
| Secrets | Keys never in argv. Assignment / PEM-shaped utterances refused. |

```bash
# Off (default) — no subprocess, no sound
unset DISCORD_OS_TTS

# On — speak Done strings on this Mac when a say/espeak CLI exists
DISCORD_OS_TTS=1

# On — also post Done as a voice message in the job thread (needs ffmpeg)
DISCORD_OS_VOICE_DONE=1

# Intent only — still Deny (DAVE not shipped)
# DISCORD_OS_VOICE_JOIN=1
```

When TTS is enabled but no CLI is on PATH, the helper returns a spoken Deny
(`Denied. TTS is enabled but no local say/espeak CLI on PATH.`) and does not
shell out. Missing deps never crash the host.

## Done as a voice message (opt-in)

`DISCORD_OS_VOICE_DONE=1` posts the Done summary as a **native Discord voice
message** in the job thread, so the phone plays "Done" while you are walking.
This is an attachment Discord renders with a play button and a waveform — not a
guild voice session, so HARD lock 6 still holds. Nothing joins a voice channel.

Pipeline, all local, no cloud TTS and no model download:

1. **Local TTS** writes a speech file — `say -o speech.aiff "<summary>"` on
   macOS, `espeak -w speech.wav "<summary>"` elsewhere (same resolver as
   `speak_done`).
2. **`ffmpeg` → OGG/Opus** for Discord: `-ac 1 -ar 48000 -c:a libopus`.
3. **`ffmpeg` → mono 8k s16le** probe stream. The waveform bytes and the
   duration come from that decoded PCM with stdlib `array` + `base64` only —
   no ffprobe, no audio library, no deprecated `aifc`.

The spoken body is the same `safe_final_summary` the Done card shows, run
through `redaction.py` (`redact_text_markers`) and clipped to
`MAX_VOICE_CHARS` (420). Assignment / PEM-shaped argv is refused exactly as it
is for `speak_done`.

| Rule | Behavior |
|---|---|
| Default | **Off.** No `DISCORD_OS_VOICE_DONE` = no render, no subprocess, no send. |
| Missing `say`/`espeak` or `ffmpeg` | **No voice message**, one stderr line, the Done card is unaffected. |
| Either tool exits non-zero, or the audio decodes silent | Same fail-soft path. |
| Where | **Job thread only** (`thread_id` required). Never the channel — it would bury the card. |
| How often | **Once per run**, on the settle path next to `maybe_speak_done`. |
| Never for | Cancelled runs and eval runs (`intake.metadata["eval"]`). |
| Hot path | A short daemon thread (`post_voice_done_async`); the card is already posted. |

The message Discord receives:

| Field | Value |
|---|---|
| message `flags` | `IS_VOICE_MESSAGE` = `1 << 13` (`8192`) |
| `content` | empty — a voice message carries no text, embeds, or components |
| `attachments[0].filename` | `voice-message.ogg` |
| `attachments[0].duration_secs` | seconds, from the decoded PCM frame count |
| `attachments[0].waveform` | base64 of up to **256** bytes, each a `0-255` bucket peak |
| file part MIME | `audio/ogg` (not octet-stream — `send_channel_attachment` takes `attachment_content_type`) |

`discord-os host doctor` reports the knob either way: `OK … off`, `OK …=1`
with the resolved `say` and `ffmpeg` paths, or `WARN …=1 but <tool> not on
PATH — voice message fails soft`.

### Unverified field names

Checked against Discord's documented voice-message shape from knowledge, not
against a live request at build time. Two details could not be confirmed:

- Whether `duration_secs` must be an **integer** or accepts a float. We send a
  float rounded to milliseconds; if the API rejects it, the send fails soft.
- Whether Discord requires the multipart file part's `Content-Type` to be
  `audio/ogg`, or infers it from the filename. We set it explicitly — harmless
  either way.

A rejected send is one log line and no card change, so a wrong guess here
degrades to today's behavior rather than breaking Done.

## Investigation: can we join for real?

Discord bot join in principle:

1. **Gateway Voice State Update** (opcode 4) with `guild_id` + `channel_id`.
2. A second **voice WebSocket** (`VOICE_SERVER_UPDATE` → endpoint + token).
3. **UDP** discovery + transport encryption (`aead_xchacha20_poly1305_rtpsize`, …).
4. Since **2026-03-01**: **DAVE E2EE** (libdave / MLS). Non-DAVE clients are
   rejected with voice close code **4017**.
5. Speaking / listening additionally needs Opus encode/decode + Speaking
   flags — not required for a silent mute/deaf seat, but still behind DAVE.

Why Discord OS stays Deny:

- Product posture is REST-first; Gateway exists for HOST buttons, not a voice
  client. No `discord.py` dependency.
- Shipping `libdave` + voice UDP + Opus is a native stack and ongoing
  protocol surface — out of scope for phone-remote OpenRouter cooks.
- Half-wiring Opcode 4 alone (appear briefly, then drop) is worse than an
  honest Deny — we refuse to send it without a completable DAVE session.
- Full duplex guild TTS/STT is not honest on the phone-remote model; use
  local `say` for Mac Done speech and voice **memos** for intake.

`discord-os host doctor` emits a **WARN** while `DISCORD_OS_VOICE_JOIN` is set.
`voice_capabilities()` returns the can/can't matrix for tests and tooling.

## Code

- `src/agent_discord/discord/tts.py` — `tts_enabled`, `speak_done`,
  `maybe_speak_done`, `voice_done_enabled`, `voice_done_tools`,
  `render_voice_done`, `maybe_post_voice_done`, `post_voice_done_async`,
  `join_voice_channel`, `leave_voice_channel`, `speak_in_voice_channel`,
  `listen_in_voice_channel`, `voice_capabilities`
- `src/agent_discord/discord/layout.py` — `voice_state_update` (payload only),
  `FLAG_IS_VOICE_MESSAGE`
- `src/agent_discord/discord/rest.py` — `send_channel_attachment`
  `attachment_extra` / `attachment_content_type`
- `src/agent_discord/orchestration/orchestrator.py` — best-effort
  `maybe_speak_done` + `post_voice_done_async` on settle
- `src/agent_discord/discord/voice.py` — inbound voice memos (unchanged)
- `src/agent_discord/host/doctor.py` — WARN when join intent env is set;
  voice-Done knob + tool readiness line
- Tests: `tests/test_tts.py`, `tests/test_voice_message_done.py`,
  `tests/test_discord_half_p2.py`

## Out of scope / PARKED

- Discord Activities / Rich Presence apps
- Cloud TTS vendors, API keys for speech, or model downloads
- Auto-joining a voice channel when a job starts
- Streaming worker tokens as audio
- Voice messages for anything but Done — no spoken progress, no spoken asks
- libdave / DAVE MLS / guild voice duplex
- Computer-use / discord-os-computer / Automaton
