# Voice join + TTS (beyond P2.13)

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

# Intent only — still Deny (DAVE not shipped)
# DISCORD_OS_VOICE_JOIN=1
```

When TTS is enabled but no CLI is on PATH, the helper returns a spoken Deny
(`Denied. TTS is enabled but no local say/espeak CLI on PATH.`) and does not
shell out. Missing deps never crash the host.

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
  `maybe_speak_done`, `join_voice_channel`, `leave_voice_channel`,
  `speak_in_voice_channel`, `listen_in_voice_channel`, `voice_capabilities`
- `src/agent_discord/discord/layout.py` — `voice_state_update` (payload only)
- `src/agent_discord/orchestration/orchestrator.py` — best-effort
  `maybe_speak_done` on settle
- `src/agent_discord/discord/voice.py` — inbound voice memos (unchanged)
- `src/agent_discord/host/doctor.py` — WARN when join intent env is set
- Tests: `tests/test_tts.py`, `tests/test_discord_half_p2.py`

## Out of scope / PARKED

- Discord Activities / Rich Presence apps
- Cloud TTS vendors, API keys for speech, or model downloads
- Auto-joining a voice channel when a job starts
- Streaming worker tokens as audio
- libdave / DAVE MLS / guild voice duplex
- Computer-use / discord-os-computer / Automaton
