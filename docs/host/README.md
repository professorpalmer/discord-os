# Host


**HARD locks:** [policy.md](policy.md) — SSH bridge OPT-IN, no forum auto-tags, Path A never silent local, single gateway, Update=PyPI, voice local TTS/memo, spend honesty, desk single-user OK, slash self-heal, CU/docker PARKED.
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
| SSH gate bridge | `DISCORD_OS_SSH_GATES=bridge` — live phone Allow/Deny/Always across Path A (pending markers + SSH result writeback). Default unset = Need + remote Deny when write-gate on. Fail closed if bridge cannot arm. |

```bash
# JSON (preferred)
DISCORD_OS_HOSTS=[{"id":"lab","label":"Lab Mac","ssh":"cary@lab.local","channels":["CHANNEL_ID"],"workdir":"/Users/cary/Projects"}]

# Compact CSV
DISCORD_OS_HOSTS=lab:ssh:cary@lab.local,nas:path:/Volumes/work
```

Bind a channel: `bind host lab` (or `/bind host lab`). Doctor reports allowlist status, **OK**s cook-capable ssh hosts (`cook via ssh BatchMode` plus remote `cli=` / `openrouter=env|vault` — never secrets), **WARN**s unreachable ssh, missing remote `puppetmaster`/`agentic`, or missing remote OpenRouter (env/vault) so phone sees Need before a blind cook Deny, and **FAIL**s unsafe entries (duplicate ids, empty target, ssh targets that look like flag/password soup).

**Path A (remote cook).** Oversized prompts use SSH **stdin** handoff (not argv) so OS ``ARG_MAX`` does not abort the cook — see [compute README](../compute/README.md).  Allowlisted `kind=ssh` hosts cook off this Mac: control plane builds `host_runner_argv` (`ssh -o BatchMode=yes user@host …`) and runs remote `puppetmaster agentic` (OpenRouter). Doctor/preflight probe checks SSH **and** remote CLI + OpenRouter presence (no key tunnel). Probe fails or `DISCORD_OS_SSH_COOK=0` → spoken Deny — never a silent local cook. Remote must already have OpenRouter configured (key never on argv). Live progress pipe: remote agentic stdout/stderr → Discord `PROGRESS` cards while SSH runs (same parsers as local). Phone **Cancel** kills the local ssh process group and best-effort remote pid / ControlMaster; failure speaks **Cancel unconfirmed** (no false Cancelled paint).


`discord-os setup` / `host start` detaches it and posts the HOST card: On, Off, Ask, a More menu (Pair / Halt or Resume / Clear failed Needs / Gate / Roles / GitHub / Files here or on host / Terminal on host / Browser here or on host), and Jobs. Dest is a noun: **here** stays in Discord (the tapping client — phone or desktop — opens the link or reads the listing). **host** opens a GUI on the listen machine. Discord does not send which client tapped; presence `client_status` is not a dest. The job line and select are a deterministic briefing over SQLite: parked / failed first, then waiting-on-CI, then live, then last Done. Not a second board. Selecting a job answers **ephemerally** — status line, job code, a link to that job's thread card, and the same buttons (**Dismiss** on a failed Need, Continue / Retry on a done one). It never posts a second copy of the job card into the HOST channel: one live card per job, in its thread. Dismiss / ack / cancel settle immediately refresh the HOST Jobs select (and Need line); if the panel message id is missing the host recovers or repaints it, else speaks Need once. Message intake is REST. A Gateway is open **only** so those controls work. Do not run a second bot process on the same token. Discord has no tabs — the More select is the grouping. Pair / Gate open ephemeral Confirm menus; Roles opens the role-id **modal** (not an ephemeral Roles fantasy). More → Post preference poll is a non-blocking survey only — never a live gate replace. HOST Jobs select labels prefix Need / Live / Done; panel accent follows the top job.

## Power

| Discord | Meaning |
|---|---|
| On | Armed. First click may become owner when require is **off** (default). |
| Off → Confirm | Disarmed. Helper stays so On still works. |
| Ask | Prompt into that channel. |
| Pair | Owner / operators. Intentional bootstrap even when require is on. |
| Halt / Resume | Halt stops new jobs (OpenRouter usage cost on agentic receipts). While halted the More option reads **Resume** instead, so the state is visible and each action is named — not one label that toggles. Both are idempotent. `discord-os spend --resume` also clears it. |
| Clear failed Needs | Confirm, then bulk-dismiss failed / attention Needs for this channel (same as job-card Dismiss). CLI: `discord-os jobs clear-needs --failed`. |

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

macOS LaunchAgent (`com.discord-os.host`) or the Windows equivalent from `host/install.py`.
`KeepAlive` is paired with **`ThrottleInterval` 30** (systemd: `RestartSec=30`) so a
host that dies at startup — bad token, `ConfigError`, sqlite lock — backs off into a
readable `host.log` instead of a silent 10 s respawn loop. After a PyPI bump, install into that venv and kick the helper. The HOST card shows an **Update available · X.Y.Z** pill when the installed package lags PyPI latest (fail soft if PyPI is unreachable; no auto-upgrade). Upgrade: `pip install -U discord-os` in `~/discord-os/.venv`, then `discord-os host restart` (or bounce `com.discord-os.host`).

```bash
discord-os host status
discord-os host doctor          # LaunchAgent / workspace / pid / gateway
discord-os host doctor --fix   # clear dead-pid gateway locks only
discord-os host doctor --notify # refresh Need state; never posts to Discord
discord-os host stop
discord-os host start --channel-id ID
```

## Workspace and .env resolution

Resolution is **CWD-independent**. Running `discord-os ...` from a git checkout
used to create or open a second SQLite database next to the source; it no longer
can.

| Input | Resolves to |
|---|---|
| `AGENT_DISCORD_WORKSPACE` set | That path, expanded and resolved. Unchanged. |
| Unset, `~/discord-os/.agent-discord` exists | **That** — the documented live workspace. |
| Unset, live layout absent | `~/.discord-os/workspace`. |
| `.env` | Beside the workspace: `<workspace>/../.env`, i.e. `~/discord-os/.env` for the live layout. Never the current directory. |
| Explicit `dotenv_path=` / `workspace=` | Honored exactly as passed. |

A `.env` may still declare `AGENT_DISCORD_WORKSPACE`; the file is located from
the stable default first, then that declaration wins over the default.
`host doctor`'s preferred-workspace WARN uses the same resolver, so it cannot
warn against a path the product would never choose. Code:
`default_workspace` / `default_dotenv_path` in `src/agent_discord/config.py`.

## Host log

`.agent-discord/logs/host.log` is the LaunchAgent's `StandardOutPath` **and**
`StandardErrorPath`. The host process wraps `sys.stdout` / `sys.stderr` once at
startup (`src/agent_discord/host/logstream.py`) so every bare `print()` line in
the codebase lands with an ISO-8601 local timestamp. Call sites stay plain.

| Rule | Behavior |
|---|---|
| Who stamps | Only the long-running `host run` / `listen` entry point. One-shot CLI commands print plain. |
| Foreground | No-op when both streams are a terminal. |
| Partial line | Held until its newline, so one logical line is never split across two stamps. |

### Rotation

The host rotates its own log — at startup and then at most once a minute from
the writer. No logrotate, no cron.

| Rule | Behavior |
|---|---|
| Ceiling | `host.log` over **10 MB** rotates. |
| Generations | `host.log.1` .. `host.log.3`; the fourth is deleted. |
| Method | **Copy-truncate.** launchd opens `StandardOutPath` once per spawn and holds that descriptor for the life of the process, so a rename would leave the host writing into an unlinked inode until the next respawn. The bytes are copied to `host.log.1` and `host.log` is truncated in place; launchd and `start_detached` both open it append, so writes resume at the new end of file. |

## Approval timeout (P0.3)

Parked write-gate Allow / Always allow / Deny does not sit forever. After
`DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` (default 20) the listen tick auto-denies
with spoken `Expired. Write was not started.` Set `0` or `off` to disable.

## Phone-visible host liveness (P0.2)

Desk doctor stays on the Mac. A thin digest (`power` / `pid` / `doctor` /
`gateway`) ranks as a HOST **Need** line. It does **not** post to the host
channel (0.5.87). See [status.md](status.md).

## Discord RO status digest (P2.7)

Phone-visible read-only facts (power / spend / jobs / allowlist ids). Posts to
the host channel (or `DISCORD_OS_STATUS_THREAD_ID`) on **On**, `/status`, and
listen on-change. Debounced. Never mutates power. See
[status.md](status.md).

## Morning summary

One HOST card per local day at 07:30 (`DISCORD_OS_MORNING_AT`), built from
overnight settles, open Needs, and bound-repo PR/CI state. Silent when there
is nothing to report. `DISCORD_OS_MORNING=0` disables. See
[morning.md](morning.md).


## Other host verbs

- `/open [here|host] terminal|files|browser` — dest-explicit. `here` lists files or returns a link in Discord. `host` opens a GUI. Browser with a URL defaults to here.
- `schedule every 1h: run tests` — SQLite cron, listen loop fires it
- GitHub rules — exact repo/branch/conclusion filters; `new` cooks an unbound match, `single` follows up in the owning job
- voice memo — local whisper CLI if on PATH ([voice.md](voice.md) for TTS / join spike)

## Voice join + TTS (beyond P2.13)

Opt-in local spoken Done on this Mac. Discord guild voice join re-checked:
**DAVE E2EE** required since 2026-03-01 — fail closed (no libdave). See
[voice.md](voice.md).

| Rule | Behavior |
|---|---|
| Default | `DISCORD_OS_TTS` unset/off — no subprocess, no sound. |
| Opt-in | `DISCORD_OS_TTS=1` + `say` / `espeak` on PATH. Argv only; keys never in argv. |
| Missing CLI | Spoken Deny. Host keeps running. |
| Voice join | Always Denied (DAVE / libdave not shipped; no half-wired Opcode 4). |
| Guild speak/listen | Parked Deny — use local TTS + voice memos. |
| Activities | Never. |

## Mac Rich Presence (optional)

Desktop Discord on this Mac can show HOST as an activity. Independent of bot gateway presence. Install `discord-os[presence]`. Default ON when `pypresence` and `DISCORD_APPLICATION_ID` are present. Set `DISCORD_OS_PRESENCE=0` to disable. Fail soft if Discord desktop is not running. See [band-b-pypresence](../co-work/band-b-pypresence.md).

## Ops webhook (optional side-channel)

HTTP-only alerts to a Discord webhook. **Not** JobPool / HOST cards. Install `discord-os[webhook]`. Set `DISCORD_OS_WEBHOOK_URL` (comma-separated URLs ok). `DISCORD_OS_WEBHOOK=0` **or** empty URL = off. Fires host start / version kick (once), Job fail, Halt, and a debounced rate-limit storm hook. Fail soft — never blocks gateway, cards, or JobPool. See [band-c-webhook](../co-work/band-c-webhook.md).

## jishaku (Cary tip debugging only)

Not a product feature. Optional extra `discord-os[debug]`. Default **off.** `DISCORD_OS_JISHAKU=1` **and** owner / allowlisted operator. Flag alone does not enable. Cog attach parked (REST host; no second gateway). See [band-d-jishaku](../co-work/band-d-jishaku.md).

## Code

- `src/agent_discord/host/panel.py` — HOST card, Ask channel; `refresh_host_jobs_panel` after ranking flips
- `src/agent_discord/host/presence.py` — optional pypresence (Job title + On/Off/Halt)
- `src/agent_discord/host/webhook.py` — optional discord-webhook ops side-channel
- `src/agent_discord/host/jishaku.py` — optional jishaku tip-debug gate (default off; owner only)
- `src/agent_discord/host/power.py` — armed / pid
- `src/agent_discord/host/runners.py` — multi-host allowlist (fail-closed)
- `src/agent_discord/orchestration/service.py` — operators / REQUIRE_OPERATORS
- `src/agent_discord/host/doctor.py` — operators require check
- `src/agent_discord/host/status.py` — RO snapshot, HOST Need digest (P0.2), Discord RO status digest (P2.7)
- `src/agent_discord/discord/tts.py` — local TTS + voice join/leave honesty (DAVE Deny)
- `src/agent_discord/host/install.py` — login item
- `src/agent_discord/host/logstream.py` — timestamped host.log lines + copy-truncate rotation
- `src/agent_discord/host/actions.py` — Terminal / files / browser
- `src/agent_discord/cli.py` — `cmd_host_*`, `cmd_setup`

## Slash (opt-in)

Text binds and the HOST panel are the default. Slash is optional (default off) and mirrors the same verbs when registered — `/bind` (name autocomplete), `/ask` (prompt + realm autocomplete), `/job` (DOS-* autocomplete), `/status`, `/on`, `/off`, `/stop`, `/open`, `/connect`, plus the `Send to Discord OS` message context menu. `AGENT_DISCORD_INTERACTIONS=gateway` carries them on the Gateway the host already owns (no public URL, no public key); `=http` keeps the HTTPS endpoint. Commands are guild- and user-installable; an interaction from outside the host server is answered on the interaction webhook and needs a paired operator. When interactions are exposed, the host self-heals registration (version-aware; fail soft). Not required for doctor, binds, or jobs. No `/add`. See [slash.md](slash.md). Code: `src/agent_discord/discord/interactions.py`.

## Forwarded messages

Discord forwarding sends an **empty** outer `content` with
`message_reference.type = 1` (FORWARD) and the real payload in
`message_snapshots[].message`. `message_from_rest_payload` merges snapshot
content, attachments, and embeds into the intake behind a `forwarded`
provenance line (the forwarder's own comment, when they wrote one, stays
first) and stamps `metadata["forwarded"]`. A reply (`type` 0) is not a
forward and keeps its own content. Without the merge a forwarded ask lands
blank.

## Schedules while Off

Due schedules do **not** queue as a job storm when HOST is Off. Listen posts one
**Catch-up** briefing (`skipped_while_disarmed`) and bumps each schedule forward.
Turn On for the next interval — not a flood of overdue cooks.

