# Host

The host is the long-running process on this Mac: listen loop, JobPool, SQLite, Puppetmaster workers. Discord is only the remote.

## Multi-host runners (fail-closed)

Security posture first. Multi-host is an **explicit allowlist** seam — never a discovery protocol.

| Rule | Behavior |
|---|---|
| Empty `DISCORD_OS_HOSTS` | Current single-host behavior only (this Mac is the computer). |
| Unknown host id | **Fail closed** — spoken `Denied. Host '…' is not allowlisted.` No silent local fallback. |
| On / Off / status | Always local on the control-plane Mac. Power never routes remotely. |
| Credentials | Never in argv. SSH uses agent / `~/.ssh/config` only (`BatchMode=yes`). |

```bash
# JSON (preferred)
DISCORD_OS_HOSTS=[{"id":"lab","label":"Lab Mac","ssh":"cary@lab.local","channels":["CHANNEL_ID"],"workdir":"/Users/cary/Projects"}]

# Compact CSV
DISCORD_OS_HOSTS=lab:ssh:cary@lab.local,nas:path:/Volumes/work
```

Bind a channel: `bind host lab` (or `/bind host lab`). Doctor reports allowlist status and **FAIL**s unsafe entries (duplicate ids, empty target, ssh targets that look like flag/password soup).

This commit is the allowlist + routing seam. A later daemon can plug into `host_runner_argv` — full SSH fleet productization is out of scope here.


`discord-os setup` / `host start` detaches it and posts the HOST card: On, Off, Ask, a More menu (Pair / Halt / Gate / Roles / GitHub / Files here or on host / Terminal on host / Browser here or on host), and Jobs. Dest is a noun: **here** stays in Discord (the tapping client — phone or desktop — opens the link or reads the listing). **host** opens a GUI on the listen machine. Discord does not send which client tapped; presence `client_status` is not a dest. The job line and select are a deterministic briefing over SQLite: parked / failed first, then waiting-on-CI, then live, then last Done. Not a second board. Message intake is REST. A Gateway is open **only** so those controls work. Do not run a second bot process on the same token. Discord has no tabs — the More select is the grouping.

## Power

| Discord | Meaning |
|---|---|
| On | Armed. First click may become owner. |
| Off → Confirm | Disarmed. Helper stays so On still works. |
| Ask | Prompt into that channel. |
| Pair | Owner / operators. |
| Halt | Spend cap (OpenRouter usage cost on agentic receipts). `discord-os spend --resume` clears it. |

Work is accepted only while On, and only from a paired operator after the first pair.

## Login helper

macOS LaunchAgent (`com.discord-os.host`) or the Windows equivalent from `host/install.py`. After a PyPI bump, install into that venv and kick the helper.

```bash
discord-os host status
discord-os host doctor          # LaunchAgent / workspace / pid / gateway
discord-os host doctor --fix   # clear dead-pid gateway locks only
discord-os host dashboard       # read-only companion at http://127.0.0.1:8765/
discord-os host stop
discord-os host start --channel-id ID
```

## Companion dashboard (read-only)

Local HTTP glance at host status — version, power/armed, spend, recent jobs, doctor summary, and multi-host allowlist **ids** (no secrets). Mutating controls stay on the Discord HOST panel.

```bash
discord-os host dashboard          # http://127.0.0.1:8765/
discord-os dashboard               # same (alias)
discord-os host dashboard --once   # print JSON snapshot, no server
```

| Rule | Behavior |
|---|---|
| Bind | **Fail closed** to `127.0.0.1` (or `DISCORD_OS_DASHBOARD_HOST` if loopback). |
| Non-loopback | Refused unless `--allow-non-loopback` (not recommended; no auth). |
| Methods | GET / HEAD only. POST/PUT/PATCH/DELETE → 405. |
| Secrets | No bot tokens, env dumps, SSH targets, or credentials in responses. |
| Allowlist | Ids / labels / kinds only — never `target` / ssh user@host. |

JSON: `GET /api/status`. HTML: `GET /`. Code: `src/agent_discord/host/dashboard.py`.

## Other host verbs

- `/open [here|host] terminal|files|browser` — dest-explicit. `here` lists files or returns a link in Discord. `host` opens a GUI. Browser with a URL defaults to here.
- `schedule every 1h: run tests` — SQLite cron, listen loop fires it
- GitHub rules — exact repo/branch/conclusion filters; `new` cooks an unbound match, `single` follows up in the owning job
- voice memo — local whisper CLI if on PATH ([voice.md](voice.md) for TTS / join spike)

## Voice join + TTS (P2.13 spike)

Opt-in local spoken Done on this Mac. Discord voice-channel join is stubbed
**fail closed**. See [voice.md](voice.md).

| Rule | Behavior |
|---|---|
| Default | `DISCORD_OS_TTS` unset/off — no subprocess, no sound. |
| Opt-in | `DISCORD_OS_TTS=1` + `say` / `espeak` on PATH. Argv only; keys never in argv. |
| Missing CLI | Spoken Deny. Host keeps running. |
| Voice join | Always Denied in this spike (gateway + Opus/UDP deferred). |
| Activities | Never. |

## Code

- `src/agent_discord/host/panel.py` — HOST card, Ask channel
- `src/agent_discord/host/power.py` — armed / pid
- `src/agent_discord/host/runners.py` — multi-host allowlist (fail-closed)
- `src/agent_discord/host/dashboard.py` — read-only companion web dashboard
- `src/agent_discord/discord/tts.py` — local TTS + voice-join stub (P2.13)
- `src/agent_discord/host/install.py` — login item
- `src/agent_discord/host/actions.py` — Terminal / files / browser
- `src/agent_discord/cli.py` — `cmd_host_*`, `cmd_setup`

## Slash (opt-in)

Text binds and the HOST panel are the default. Slash commands are optional and should mirror the same verbs when registered; they are not required for doctor, binds, or jobs.
