# Compute

Not a compute host. Discord OS dispatches Puppetmaster on this Mac. That is the worker plane: analyze uses `--mode analyze`, implement takes the cwd write lock, live-thread steer flushes into the CLI process.

`AGENT_DISCORD_COMPUTE=auto` (default): agentic `openrouter/auto` when an OpenRouter key is in env or the workspace vault; **fail closed** when missing — spoken config Deny / `discord-os connect`. No Cursor fallback. No silent model remap. Requests for any other model fail closed.

Questions: `--mode analyze`. File work: `--mode implement --allow-dirty` on agentic. Spoken change asks (`enable`, `I'd like to`) are implement. Auto writes unless HOST Gate is on.

## Keys

```bash
discord-os connect --from-env
# or /connect in Discord (inherit / ticket / shred)
```

Vault: `{workspace}/keys/`. Key goes into the **subprocess env** as `OPENROUTER_API_KEY`, never argv, never logs. Agentic usage receipts carry `cost_usd` into Halt spend tracking.

Optional Marionette HTTP: `AGENT_DISCORD_BACKEND=marionette` plus `MARIONETTE_BASE_URL`. Unconfigured Marionette fails closed. Marionette uses the same `openrouter/auto` pin (or fails closed).

## Code

- `src/agent_discord/config.py` — `resolve_compute` (agentic-or-fail)
- `src/agent_discord/puppetmaster/agentic.py` — OpenRouter via `puppetmaster agentic`
- `src/agent_discord/puppetmaster/backend.py` — shared CLI helpers
- `src/agent_discord/host/remote_cook.py` — Path A SSH remote cook
- `src/agent_discord/keys/` — connect + vault

## Path A progress pipe

`SshRemoteCookBackend.stream` yields live `PROGRESS` from remote agentic stdout/stderr (mocked-SSH covered in `tests/test_remote_cook.py`). No local `deltas --follow` for remote jobs. Fail closed on unreachable SSH, missing remote CLI, or missing/sealed remote OpenRouter (doctor WARN; cook Deny). Probe reports `openrouter=env|vault|vault-sealed|missing` over BatchMode — `vault` is decrypt-ready presence (entry + master.key); `vault-sealed` means the entry exists but cannot decrypt. Secrets never on argv.

## Cancel honesty

Local agentic and Path A SSH cooks register a killable child process group.
Phone Cancel terminates that group (and best-effort remote pid on SSH). Path A
echoes `DISCORD_OS_REMOTE_PID` on stdout and stderr, waits briefly for the pid
before remote `kill`, and optionally uses ControlMaster (`DISCORD_OS_SSH_CONTROL_PATH` (also auto when `DISCORD_OS_SSH_GATES=bridge`))
so `ssh -O exit` can confirm more often. Orchestrator Cancel targets the active
SSH cook backend for the run — never silent local cook. If interrupt cannot be
confirmed, Discord speaks **Cancel unconfirmed** and does not paint Cancelled.
See [cards/reactive.md](../cards/reactive.md).

## Path A edge races (beyond 0.5.54)

Best-effort hardenings for residual Path A races:

| Race | Behavior |
|---|---|
| Orphaned remote pid after Mac crash | Remote bash trap + parent-death watchdog; durable pid sidecar reaped on next cook |
| Stale ControlMaster socket | `ssh -O check` → exit/unlink before cook spawn and bridge writeback |
| Gate-bridge writeback vs Cancel | Cancel Denies pending holds; skips Allow SSH writeback |
| Settle vs Cancel / SSH exit vs settle | Cancelled wins over late Completed receipt (no Done double-write) |
| Progress / GATE_PENDING on reconnect | Local mirror kept; stale master cleared before writeback; mid-pipe drop fail-closed |

Never silent local cook for `kind=ssh`. Residual: a mid-cook SSH drop still loses
live progress lines that were not yet received — Discord keeps the last card and
fails closed (Cancel / Deny / spoken Need), it does not invent progress.

## Swarm-incomplete honesty

Puppetmaster may exit `swarm exited with incomplete tasks` after an analyze-only
/ `workers:0` run already streamed a full prose answer. Discord OS salvages that
answer as Completed (not a false failed Need). Provider auth / missing-CLI
failures still fail closed.


## ARG_MAX / oversized prompts

Huge Discord prompts can exceed OS ``ARG_MAX`` when Discord OS spawns
``puppetmaster agentic`` (local) or wraps it in Path A SSH argv. Discord OS
detects oversized argv and hands the prompt via a **temp file** (local
in-process bridge) or **SSH stdin** (remote bash → temp file → same bridge).
Override the budget with ``DISCORD_OS_ARGV_MAX`` (bytes). Keys never on argv.
If handoff cannot run, Discord speaks a Deny instead of an opaque OS error.

