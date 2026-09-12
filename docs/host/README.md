# Host

The host is the long-running process on this Mac: listen loop, JobPool, SQLite, Puppetmaster workers. Discord is only the remote.

## Multi-host runners (fail-closed)

Security posture first. Multi-host is an **explicit allowlist** seam — never a discovery protocol.

| Rule | Behavior |
|---|---|
| Empty `DISCORD_OS_HOSTS` | Current single-host behavior only (this Mac is the computer). |
| Unknown host id | **Fail closed** — spoken `Denied. Host '…' is not allowlisted.` No silent local fallback. |
| `kind=ssh` cook | **Path A remote cook** — SSH `BatchMode=yes` invokes remote `puppetmaster agentic` (OpenRouter on the remote). Unreachable / missing remote CLI or OpenRouter / kill-switch → spoken Deny. Doctor probes readiness (WARN). **Never** silent local cook on the control-plane Mac. |
| `kind=local` / path | May supply a local cwd on this Mac (documented; not a remote runner). |
| On / Off / status | Always local on the control-plane Mac. Power never routes remotely. |
| Credentials | Never in argv. SSH uses agent / `~/.ssh/config` only (`BatchMode=yes`). Control plane does **not** tunnel `OPENROUTER_API_KEY` — configure OpenRouter on the remote. |
| Kill switch | `DISCORD_OS_SSH_COOK=0` restores spoken Deny for ssh hosts (routing-only). Default on. |

```bash
# JSON (preferred)
DISCORD_OS_HOSTS=[{"id":"lab","label":"Lab Mac","ssh":"cary@lab.local","channels":["CHANNEL_ID"],"workdir":"/Users/cary/Projects"}]

# Compact CSV
DISCORD_OS_HOSTS=lab:ssh:cary@lab.local,nas:path:/Volumes/work
```

Bind a channel: `bind host lab` (or `/bind host lab`). Doctor reports allowlist status, **OK**s cook-capable ssh hosts (`cook via ssh BatchMode` plus remote `cli=` / `openrouter=env|vault` — never secrets), **WARN**s unreachable ssh, missing remote `puppetmaster`/`agentic`, or missing remote OpenRouter (env/vault) so phone sees Need before a blind cook Deny, and **FAIL**s unsafe entries (duplicate ids, empty target, ssh targets that look like flag/password soup).

**Path A (remote cook).** Oversized prompts use SSH **stdin** handoff (not argv) so OS ``ARG_MAX`` does not abort the cook — see [compute README](../compute/README.md).  Allowlisted `kind=ssh` hosts cook off this Mac: control plane builds `host_runner_argv` (`ssh -o BatchMode=yes user@host …`) and runs remote `puppetmaster agentic` (OpenRouter). Doctor/preflight probe checks SSH **and** remote CLI + OpenRouter presence (no key tunnel). Probe fails or `DISCORD_OS_SSH_COOK=0` → spoken Deny — never a silent local cook. Remote must already have OpenRouter configured (key never on argv). Live progress pipe: remote agentic stdout/stderr → Discord `PROGRESS` cards while SSH runs (same parsers as local). Phone **Cancel** kills the local ssh process group and best-effort remote pid / ControlMaster; failure speaks **Cancel unconfirmed** (no false Cancelled paint).


`discord-os setup` / `host start` detaches it and posts the HOST card: On, Off, Ask, a More menu (Pair / Halt / Gate / Roles / GitHub / Files here or on host / Terminal on host / Browser here or on host), and Jobs. Dest is a noun: **here** stays in Discord (the tapping client — phone or desktop — opens the link or reads the listing). **host** opens a GUI on the listen machine. Discord does not send which client tapped; presence `client_status` is not a dest. The job line and select are a deterministic briefing over SQLite: parked / failed first, then waiting-on-CI, then live, then last Done. Not a second board. Selecting a failed job opens its card with **Dismiss** so phone/HOST can ack the Need without Continue/Retry; dismiss refreshes the Jobs line when the panel message id is known. Message intake is REST. A Gateway is open **only** so those controls work. Do not run a second bot process on the same token. Discord has no tabs — the More select is the grouping.

## Power

| Discord | Meaning |
|---|---|
| On | Armed. First click may become owner when require is **off** (default). |
| Off → Confirm | Disarmed. Helper stays so On still works. |
| Ask | Prompt into that channel. |
| Pair | Owner / operators. Intentional bootstrap even when require is on. |
| Halt | Spend cap (OpenRouter usage cost on agentic receipts). `discord-os spend --resume` clears it. |

Work is accepted only while On, and only from a paired operator after the first pair (or immediately when `DISCORD_OS_REQUIRE_OPERATORS=1` and operators are empty — dispatch refuses until Pair).

## Operator bootstrap (fail-closed opt-in)

Peer to gjc-remote `REQUIRE_ALLOWLIST`. Soft first-message-as-owner is convenient on a single-user Mac; harden it when the bot is exposed more broadly.

| Rule | Behavior |
|---|---|
| Default (unset / `0`) | Current UX. First armed human / On / first dispatch may seed owner. |
| `DISCORD_OS_REQUIRE_OPERATORS=1` | **Fail closed** — no silent seed. Dispatch refuses until an operator exists. Auto-on when `AGENT_DISCORD_INTERACTIONS` is public. |
| Public interactions (`AGENT_DISCORD_INTERACTIONS=http`) | Doctor **FAIL**s if operators empty even when require is unset — pair first. Desk/single-user Mac (interactions off) stays workable: doctor **WARN**s and recommends the flag. |
| Alias | `DISCORD_OS_REQUIRE_ALLOWLIST=1` same effect. |
| Intentional bootstrap | HOST **Pair**, `discord-os pair --user-id ID`, or `DISCORD_OWNER_ID` / `DISCORD_OPERATOR_ROLE_IDS` at process start. |
| Doctor | **FAIL** when require is on and operators are empty. |

```bash
# Harden (shared / multi-user / exposed bot)
DISCORD_OS_REQUIRE_OPERATORS=1
DISCORD_OWNER_ID=YOUR_DISCORD_USER_SNOWFLAKE

# Or pair after start
discord-os pair --user-id YOUR_DISCORD_USER_SNOWFLAKE --role owner
```

## Login helper

macOS LaunchAgent (`com.discord-os.host`) or the Windows equivalent from `host/install.py`. After a PyPI bump, install into that venv and kick the helper.

```bash
discord-os host status
discord-os host doctor          # LaunchAgent / workspace / pid / gateway
discord-os host doctor --fix   # clear dead-pid gateway locks only
discord-os host doctor --notify # on FAIL, post thin digest to host channel (phone)
discord-os host dashboard       # read-only companion at http://127.0.0.1:8765/
discord-os host stop
discord-os host start --channel-id ID
```

## Approval timeout (P0.3)

Parked write-gate Allow / Always allow / Deny does not sit forever. After
`DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` (default 20) the listen tick auto-denies
with spoken `Expired. Write was not started.` Set `0` or `off` to disable.

## Phone-visible host liveness (P0.2)

Desk doctor + loopback dashboard do not wake the phone when LaunchAgent / pid
dies mid-cowork. A thin digest (`power` / `pid` / `doctor`) ranks as a HOST
**Need** line and posts to the host channel **on change** (debounced). See
[liveness.md](liveness.md).

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

## Discord RO status digest (P2.7)

Phone-visible copy of the dashboard RO facts (power / spend / jobs / allowlist
ids). Posts to the host channel (or `DISCORD_OS_STATUS_THREAD_ID`) on **On**,
`/status`, and listen on-change. Debounced. Never mutates power. See
[status-digest.md](status-digest.md).


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
- `src/agent_discord/orchestration/service.py` — operators / REQUIRE_OPERATORS
- `src/agent_discord/host/doctor.py` — operators require check
- `src/agent_discord/host/dashboard.py` — read-only companion web dashboard
- `src/agent_discord/host/liveness.py` — phone-visible digest / HOST Need (P0.2)
- `src/agent_discord/host/status_digest.py` — Discord RO status digest from dashboard (P2.7)
- `src/agent_discord/discord/tts.py` — local TTS + voice-join stub (P2.13)
- `src/agent_discord/host/install.py` — login item
- `src/agent_discord/host/actions.py` — Terminal / files / browser
- `src/agent_discord/cli.py` — `cmd_host_*`, `cmd_setup`

## Slash (opt-in)

Text binds and the HOST panel are the default. Slash is optional (default off) and mirrors the same verbs when registered — `/bind`, `/status`, `/on`, `/off`, `/stop`, `/open`, `/connect`. Not required for doctor, binds, or jobs. No `/add`. See [slash.md](slash.md). Code: `src/agent_discord/discord/interactions.py`.
