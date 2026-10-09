# Features (opt-ins)

Every proactive or behavior-changing feature is off by default. One
switchboard turns each one on or off. Three surfaces call it:

| Surface | How |
|---|---|
| Slash | `/features` lists them. `/features feature:<name> state:on` changes one. Operators only. |
| HOST panel | **More > Features** shows one button per feature. Tap a button to flip it. Operators only. |
| CLI | `discord-os features`, `discord-os features on <name>`, `discord-os features off <name> --channel-id ID` |

A change takes effect on the next listen tick. You do not need to restart the
host.

## The features

| Name | Scope | What it does | Env flag |
|---|---|---|---|
| `ci-watch` | host | Red CI on a bound repo posts one card with a Fix CI button. See [ci-watch](../realms/ci-watch.md). | `DISCORD_OS_CI_WATCH` |
| `morning` | host | One HOST card a day with overnight results, open Needs, and red CI. See [morning](morning.md). | `DISCORD_OS_MORNING` |
| `voice-done` | host | Speak the Done line as a voice message in the job thread. Needs `say` or `espeak`, and a working `ffmpeg`. See [voice](voice.md). | `DISCORD_OS_VOICE_DONE` |
| `capture` | channel | Short thoughts in this channel go to memory instead of a job. See [capture](capture.md). | `DISCORD_OS_CAPTURE_CHANNELS` |
| `pm-inbox` | channel | Card Puppetmaster jobs started elsewhere in this channel. One channel at a time. See [pm-inbox](../jobs/pm-inbox.md). | `DISCORD_OS_PM_INBOX_CHANNEL` |

A per-channel feature applies to the channel where you run the command or
tap the button.

## Where the state lives

The toggles live in the SQLite store. The CLI and the bot share the store.

- A host toggle wins over the `.env` value. With no toggle, the `.env` value
  applies.
- A channel feature that only `.env` turns on shows its env key in the list.
  Remove the key from `.env` to turn it off.
