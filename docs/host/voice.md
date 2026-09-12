# Voice join + TTS (P2.13 spike)

Thin spike. Not a product surface. Local spoken Done on the listen Mac is
opt-in. Discord **voice-channel join** is documented and stubbed fail-closed.
No Discord Activities. No CDN. No model download. No heavy native voice libs
(`PyNaCl`, Opus, discord.py voice) required to install or run Discord OS.

Voice **memos** (attachment → local whisper → intake) already live in
`discord/voice.py`. This page is outbound speech + the deferred join path.

## What shipped

| Piece | Behavior |
|---|---|
| Env opt-in | `DISCORD_OS_TTS=1` (also `true` / `yes` / `on`). **Default off.** |
| Local TTS | `say` (macOS) or `espeak` / `espeak-ng` on PATH. Argv lists only. |
| Done hook | `maybe_speak_done(summary)` after a settle — best-effort, never raises. |
| Voice join | `join_voice_channel(guild_id, channel_id)` → spoken **Deny**. Always. |
| `DISCORD_OS_VOICE_JOIN` | Reserved knob. Truthy still **Deny** in this spike (not an unlock). |
| Secrets | Keys never in argv. Assignment / PEM-shaped utterances refused. |

```bash
# Off (default) — no subprocess, no sound
unset DISCORD_OS_TTS

# On — speak Done strings on this Mac when a say/espeak CLI exists
DISCORD_OS_TTS=1
```

When TTS is enabled but no CLI is on PATH, the helper returns a spoken Deny
(`Denied. TTS is enabled but no local say/espeak CLI on PATH.`) and does not
shell out. Missing deps never crash the host.

## Approach: Discord gateway voice (deferred)

To actually join a guild voice channel and play TTS audio, a bot needs roughly:

1. **Gateway Voice State Update** (opcode 4) with `guild_id` + `channel_id`.
2. A second **voice WebSocket** (`VOICE_SERVER_UPDATE` → endpoint + token).
3. **UDP** discovery + encrypt/decrypt (libsodium / `PyNaCl`).
4. **Opus** encode of PCM from the TTS engine (or stream a file).
5. Speaking flags + heartbeats on the voice WS for the session lifetime.

Blockers for this spike (why we stub):

- Native deps (`PyNaCl`, system Opus) and a long-lived voice session do not
  match Discord OS's "REST-first, Gateway only for HOST buttons" posture.
- Fail-closed security: a half-wired join that drops packets or logs voice
  tokens is worse than an honest Deny.
- Product scope: Done is already a written deliverable in the job thread.
  Local `say` covers the "spoken reply on the Mac" ask without joining.

Setting `DISCORD_OS_VOICE_JOIN=1` today is an **honest Deny** (spoken:
reserved but not implemented). A future implement would still need an explicit
allowlist of guild/channel ids and must never put the bot token in argv.

## Code

- `src/agent_discord/discord/tts.py` — `tts_enabled`, `speak_done`,
  `maybe_speak_done`, `join_voice_channel` (stub)
- `src/agent_discord/orchestration/orchestrator.py` — best-effort
  `maybe_speak_done` on settle
- `src/agent_discord/discord/voice.py` — inbound voice memos (unchanged)
- Tests: `tests/test_tts.py`

## Out of scope

- Discord Activities / Rich Presence apps
- Cloud TTS vendors, API keys for speech, or model downloads
- Auto-joining a voice channel when a job starts
- Streaming worker tokens as audio
