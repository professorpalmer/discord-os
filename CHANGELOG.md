# Changelog

## Unreleased

## 0.5.47

Remote SSH doctor probe — completes Round-4 P0 (Cancel, Path A progress, gate-hook, ARG_MAX).

### P0.5 Remote OpenRouter/CLI doctor probe

Allowlisted `kind=ssh` hosts are doctor-probed for **remote** readiness, not
only SSH reachability: `puppetmaster`/`agentic` on PATH and OpenRouter present
(env or vault fingerprint). Doctor **OK**s cook-capable hosts with
`cli=` / `openrouter=` (never secrets); **WARN**s unreachable, missing CLI, or
missing OpenRouter so phone/doctor speaks honest Need before cook-time Deny.
Path A preflight / `assert_ssh_remote_cook_ready` still fail closed. Keys never
on argv. Tests mock SSH (`tests/test_remote_cook.py`,
`tests/test_host_runners.py`). Docs: host README.

With Cancel honesty (0.5.43), Path A progress (0.5.44), live gate-hook (0.5.45),
and ARG_MAX handoff (0.5.46), this closes Round-4 P0.

## 0.5.46

ARG_MAX stdin/file handoff for oversized agentic prompts (local + Path A).

### P0.4 ARG_MAX stdin/file handoff

Large agentic prompts no longer die on opaque OS ``ARG_MAX`` / ``E2BIG``.
Local OpenRouter/agentic and Path A SSH remote cook measure planned argv
against a conservative budget (``DISCORD_OS_ARGV_MAX``, default ~128KiB).
Oversized bodies spill to a temp file (local) or SSH stdin (remote) and
re-enter ``puppetmaster.cli.main`` in-process so the prompt never crosses
``execve``. Keys stay off argv. If handoff is still impossible → spoken
Deny. Tests: ``tests/test_prompt_handoff.py``. Docs: compute README.

## 0.5.45

Live gate-hook inject for local agentic PreToolUse (sitecustomize / PreToolUse wrap; Ask park; SSH gates still not crossed).

### P0.3 Gate-hook really fires

- Local OpenRouter/agentic cooks no longer only *stamp* `DISCORD_OS_GATE_*`.
  Spawns prepend `orchestration/gate_inject/` to `PYTHONPATH` so
  `sitecustomize.py` wraps Puppetmaster `AgenticAdapter._execute_tool` and
  runs `discord-os gate-hook` before each tool (hold → Discord Ask/Allow card).
- Listen drain auto-allows when write-gate is off or session Always applies
  (hook still enqueues; worker unblocks without a spurious card).
- Path A SSH: gate file-queue does **not** cross SSH yet — residual P1
  "gates across SSH". Docs: [docs/cards/ask-gate.md](docs/cards/ask-gate.md).
- Tests prove inject arms + patched `_execute_tool` invokes the hook (not
  install-only).

## 0.5.44

Path A live SSH progress pipe to Discord + CI flake hardens (drain/JobPool timing).

### P0.2 Path A progress pipe

SSH remote cook (`SshRemoteCookBackend.stream`) no longer waits blind until the
SSH one-shot finishes. Remote agentic stdout/stderr is parsed with the same
line helpers as local agentic (NDJSON token/reasoning, `progress:` lines,
prose) and yields live `PROGRESS` events to Discord before the final receipt.
`DISCORD_OS_REMOTE_PID` capture + Cancel honesty unchanged. Unreachable /
missing remote CLI still fail closed (spoken Deny; never silent local cook).
Tests: `tests/test_remote_cook.py` (mocked SSH popen). Docs: host README.

### CI flake hardens (drain / JobPool timing)

Drain+JobPool timing assert uses `backend.hold` instead of a tight 0.15s wall
budget (CI load flake on 3.12). Parallel JobPool test hardened against
wall-clock flake.

## 0.5.43

CI green after OpenRouter fail-closed, concurrency honesty, Cancel honesty docs.

### CI: OpenRouter fail-closed check tests

Happy-path CLI `check` tests set a dummy `OPENROUTER_API_KEY` so offline check
returns 0 after OpenRouter-only fail-closed. Focused test asserts missing key
exits non-zero. (No product semantics change.)

### Concurrency honesty (`DISCORD_OS_MAX_LIVE`)

- `JobPool` live ceiling is tunable via `DISCORD_OS_MAX_LIVE` (default **8**).
- Product voice: analyze can overlap; implement/swarm serialize per checkout.
  Real ceilings are OpenRouter RPM/TPM/spend + machine + Discord — not a hard
  "two cooks" product voice. Do not pretend unbounded.
- `discord-os check` prints `max live`. Docs/README/AGENTS refreshed through
  Cancel honesty + round-1–3 seams.

### P0.1 Cancel honesty (local agentic + Path A SSH)

Phone **Cancel** must not lie. Today Cancel painted SQLite `cancelled` while
OpenRouter (local or SSH remote) could keep cooking.

- Track killable child process groups for local `AgenticPuppetmasterBackend`
  and Path A `SshRemoteCookBackend` (`start_new_session` / SIGTERM→SIGKILL).
- SSH wraps remote argv with `DISCORD_OS_REMOTE_PID=$$` so cancel can
  `kill` the remote process group over BatchMode ssh; optional ControlMaster
  `-O exit` when a control path is configured.
- If interrupt is unsupported or kill fails → spoken **Cancel unconfirmed**
  and do **not** paint Done/Cancelled as success (`cancellation_pending`
  receipt, gjc-remote-shaped).
- Confirmed kill → `cancelled` + `CANCEL_REQUESTED` event.
- Tests: `tests/test_cancel_honesty.py` (local + mocked SSH).
- Docs: [docs/cards/reactive.md](docs/cards/reactive.md),
  [docs/jobs/README.md](docs/jobs/README.md),
  [docs/host/README.md](docs/host/README.md),
  [docs/compute/README.md](docs/compute/README.md).

## 0.5.42

Round-3 full P1 pack.

### Plan ExitPlanMode → `raise_plan_approve` (live)

- Agentic PreToolUse / `ExitPlanMode` and in-process `request_plan_hold` park
  **Approve / Cancel** (no Always), reuse approval timeout, and **block
  implement** until allow / deny / expire.
- Gate-hook file queue drains plan kind via `raise_plan_approve`.
- Docs: [docs/cards/plan-approve.md](docs/cards/plan-approve.md).

### Listen-dead phone notify watchdog

- LaunchAgent / cron-ready `doctor --notify` helpers
  (`render_doctor_notify_plist`, example plist + crontab). Phone wakes without
  a live listen process when `host.pid` is stale / doctor FAIL.
- Docs: [docs/host/liveness.md](docs/host/liveness.md).

### Gateway WS ACK liveness

- Heartbeat ACK age / READY / socket health (Hermes-shaped). HOST Need +
  doctor FAIL when unhealthy. REST-up ≠ receiving. Cold start stays quiet
  (low false-positive).
- Code: `src/agent_discord/discord/gateway_health.py`.

### REQUIRE_OPERATORS push

- Setup recommends the flag; doctor WARN→FAIL when interactions are public
  and operators are empty. Single-user Mac (interactions off) stays workable.
- Docs: [docs/host/README.md](docs/host/README.md).

### Honest OpenRouter / PM-adapter spend

- When usage omits `cost_usd`, status digest + Halt show **unknown** not `$0`.
  Real OpenRouter costs still display when present.

Tests: plan hold, gateway health, spend honesty, doctor-notify watchdog,
operators public FAIL.

Closes round-3 haul (0.5.39–0.5.42): Cursor purge, Path A remote cook, live ask-gate, plan hold, watchdog, WS ACK, operators push, honest spend.

## 0.5.41

P0 live ask-gate / PreToolUse hold.

- Phone Allow / Deny / Always blocks the **live worker** mid-cook: `tool_class_decision` → park Discord card → hold until `gate_result_for` or approval timeout self-denies.
- Durable file-queue hook (`discord-os gate-hook`, always exit 0) for when Puppetmaster agentic has no in-process `canUseTool`. Listen/orch drains `pending/` and writes `results/`.
- Agentic spawn stamps `DISCORD_OS_GATE_DIR` / `DISCORD_OS_RUN_ID`. Fail closed if unanswered.
- Docs: [docs/cards/ask-gate.md](docs/cards/ask-gate.md). Tests: fake worker hold.

Closes round-3 P0 pack (Path A remote cook + live ask-gate).

## 0.5.40

P0 Path A: real SSH / remote cook.

- Allowlisted `kind=ssh` hosts cook via `host_runner_argv` + SSH `BatchMode=yes` → remote `puppetmaster agentic` (OpenRouter on the remote).
- Unreachable ssh / `DISCORD_OS_SSH_COOK=0` → spoken Deny; **never** silent local cook on the control-plane Mac.
- `kind=local` / path still cooks on this Mac. Empty allowlist single-host unchanged.
- Doctor **OK**s cook-capable ssh hosts; **WARN**s unreachable (`ssh unreachable / Deny`).
- Credentials never in argv (no OpenRouter key tunnel). Tests mock ssh/probe.
- Docs: [docs/host/README.md](docs/host/README.md).

## 0.5.39


Rip Cursor / PM-cursor adapter out of Discord OS. Product compute is OpenRouter / agentic only.

- Remove `puppetmaster cursor` product path and `PuppetmasterCliBackend` cursor invocation.
- Drop `AGENT_DISCORD_COMPUTE=cursor`; `auto` means agentic-or-fail (no Cursor fallback).
- Canonical pin is `openrouter/auto`. Missing OpenRouter fails closed (`discord-os connect` / spoken Deny).
- Retarget Marionette pin + tests to OpenRouter/agentic; purge Cursor framing from `.env.example`, compute docs, catalog notes.
- Spoken provider failures no longer say "locked to Cursor" / "Unlock … under Cursor".

## 0.5.38

P2.9 Slash progressive enhancement (still opt-in).

- Thin slash aliases `/bind`, `/status`, `/on`, `/off`, `/stop` (stop = off) registered only when `AGENT_DISCORD_INTERACTIONS=http` + `discord-os interactions --register`.
- Handlers reuse power/bind absorb parse paths against workspace SQLite; text listen + HOST panel stay default. No `/add`.
- Docs: [docs/setup/README.md](docs/setup/README.md), [docs/host/slash.md](docs/host/slash.md).

Closes round-2 haul (P0–P2).

## 0.5.37


P2.8 Plan-mode Approve card (c-lord ExitPlanMode shape).

- When plan is ready, park with **Approve / Cancel** (not write-gate Always) via `raise_plan_approve`.
- Reuses approval timeout; reactive `actions=plan` row; spoken Deny / Cancel / expire.
- Fail closed on empty / unknown plan status. Full PM plan-hook deferred.
- Docs: [docs/cards/plan-approve.md](docs/cards/plan-approve.md).

## 0.5.36

P2.7 Discord RO status digest from dashboard data.

- Push read-only snapshot (power / spend / jobs / allowlist ids) to the host channel or `DISCORD_OS_STATUS_THREAD_ID` on On, `/status`, and listen on-change (debounced).
- Reuses `build_status_snapshot`; fail closed — never mutates power; no secrets / SSH targets.
- Docs: [docs/host/status-digest.md](docs/host/status-digest.md).

## 0.5.35

P1.6 Reactive seam finish.

- Park / live running / settle / deny / ask-gate parked rows route through `reactive_paint` (`reactive_working_card` / `reactive_progress_card` / `reactive_receipt_card`).
- HOST Jobs already used `reactive_for_job`; hardcoded `actions="parked"` / `"running"` dual-paths removed at those call sites.
- Docs: [docs/cards/reactive.md](docs/cards/reactive.md). Not Activities.


## 0.5.34

P1.5 Operator bootstrap harden (REQUIRE_ALLOWLIST-style).

- Env `DISCORD_OS_REQUIRE_OPERATORS=1` (alias `DISCORD_OS_REQUIRE_ALLOWLIST=1`): refuse dispatch until an operator/owner is paired — no silent first-armed-human seed.
- Default remains off (single-user Mac UX: first On / first armed human may seed owner).
- Intentional bootstrap kept: HOST **Pair**, `discord-os pair`, `DISCORD_OWNER_ID` / `DISCORD_OPERATOR_ROLE_IDS`.
- Doctor **FAIL**s when require is on and operators are empty.
- Docs: [docs/host/README.md](docs/host/README.md).


## 0.5.33

P1.4 Per-tool / AskUserQuestion gate (surgical phone approve).

- Tool-class Allow / Always allow / Deny mid-run via `raise_tool_gate`; AskUserQuestion option cards via `raise_ask_user`.
- Tool-class session prefs (`tool_class_allow:<class>:<scope>`, 4h, cleared on HOST Off). Unknown classes fail closed.
- Reuses write-gate button custom_ids + approval timeout; spoken Allow / Deny / Always allow in the parked thread.
- Docs: [docs/cards/ask-gate.md](docs/cards/ask-gate.md). Full PM `canUseTool` hook deferred.

## 0.5.32

P0.3 Approval timeout + Cancel clarity + inbound queue while RUNNING.

- Parked write-gate auto-denies after `DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` (default 20). Spoken expire. `0` / `off` disables.
- Live Components v2 cook cards keep **Cancel** (`discord-os:job:cancel:<run_id>`). Phone interrupt is that button on the job-thread card, not HOST Off.
- Phone texts in a live job thread are not dropped: durable SQLite `inbound_queue`, mid-cook steer when possible, else follow-up in the same thread after the cook. Default on; `DISCORD_OS_INBOUND_QUEUE=0` restores steer-or-miss. Fail closed if the target thread is ambiguous.

## 0.5.31

P0.2 Phone-visible host liveness / status Need.

- Thin digest (`power` / `pid` / `doctor`) ranks as a HOST **Need** line on Jobs / HOST card.
- Listen loop posts an on-change spoken status line in the host channel (debounced; Discord mobile push).
- `discord-os host doctor --notify` posts FAIL digests from the desk when the listen process is down.
- No tokens in posts; dashboard stays read-only. Docs: [docs/host/liveness.md](docs/host/liveness.md).


## 0.5.30

P0.1 SSH cook-or-Deny (honesty). Fail closed.

- Cook that resolves to `kind=ssh` spoken Denies (`routing only / Deny until remote cook`) — no silent local cook on the control-plane Mac.
- `kind=local` / path hosts may still supply a local cwd. Empty allowlist single-host unchanged.
- Doctor **WARN**s ssh hosts with that status; `host_runner_argv` kept as Path A building block (credentials never in argv).
- Docs: [docs/host/README.md](docs/host/README.md).

## 0.5.29

Voice channel join + TTS spike (P2.13). Thin. Fail closed.

- Env opt-in `DISCORD_OS_TTS=1` (default off). Local `say` / `espeak` argv-only helper speaks Done strings when enabled.
- Missing CLI → spoken Deny; no shell, keys never in argv.
- `join_voice_channel` stub always Denies (gateway voice + Opus/UDP deferred). Docs: [docs/host/voice.md](docs/host/voice.md).
- Not Activities. No heavy native voice libs required.


## 0.5.28

Reactive card spike (P2.14).

- `reactive_paint` maps job state → button set / accent / stage used by write-gate Allow / Always allow / Deny and Continue.
- Docs: [docs/cards/reactive.md](docs/cards/reactive.md). Not Activities. Not a client UI.

## 0.5.27

Companion web dashboard (P2.12). Read-only.

- `discord-os host dashboard` serves loopback HTML + `/api/status` JSON.
- Fail-closed bind (127.0.0.1); no write endpoints; no SSH targets or tokens in responses.

## 0.5.26

Multi-host runners allowlist (P2.11). Fail-closed.

- `DISCORD_OS_HOSTS` explicit allowlist; empty keeps single-host.
- Unknown host id → spoken Deny; no silent local fallback.
- `bind host <id>`; doctor reports allowlist; Off/power stay local.
- Runner argv never carries credentials.

## 0.5.25

DisCode write-gate. Jobs Continue. Honest Done. V2 console.

- Parked implement cards: Allow / Always allow / Deny; Always-allow is a 4h session prefer cleared on HOST Off.
- HOST Jobs → Continue starts a tip-parented job in the same thread.
- Spoken Done for platform lock, missing agentic CLI, and no_model; voice memos without whisper speak instead of silent skip.
- Live cards stay Components v2; embeds are TypeError fallback only. Slash stays opt-in in docs.

## 0.5.24

Host doctor. Spend strings parse. Idle sessions soak two follow-ups.

- `discord-os host doctor [--fix]` checks LaunchAgent workspace, pid, gateway locks.
- Halt spend accepts `$0.04`-style provider costs.
- Two sequential idle-thread follow-ups each mint a job and advance the thread watermark.

## 0.5.23

Parallel cooks no longer collide on DOS-* job codes.

- `create_task` mints under `BEGIN IMMEDIATE` and retries on unique/locked races.
- Docs: live session threads, per-thread watermarks, spend receipts into Halt.

## 0.5.22

Idle Discord threads stay live sessions. Spend receipts tell the truth. Folder prefer is discord-os.

- After Done, follow-ups in the same thread start a new job (parented at the prior tip). Running threads still steer.
- Session-thread drains watermark by thread id so HOST panel tips cannot hide unread follow-ups.
- JobPool cap is eight cooks; product copy matches. OpenRouter usage cost reaches Halt.
- Repo discovery prefers `~/Projects/discord-os` over the historical `agent-discord` folder.

## 0.5.21

The host associates the ask before the worker hunts. Done speaks the finding.

- Named checkout leads the worker prompt: `Associated: <name> at <path>`. Do not hunt.
- Host scans GitHub on that cwd for associated asks, not only "list my PRs".
- Spoken change asks (`enable`, `I'd like to`) are implement.
- Reasoning stays in the fence. `## Findings` is the Done body.

## 0.5.20

GitHub talks back in the job thread. Stacked PRs are lineage children. Unbound checks cook.

- Failing checks and human review wake the owning job thread. HOST ranks Need, then Waiting, then Live, then Last. Speakable ids are `DOS-*`.
- A PR whose base is another job's head is a child in `discord-os lineage`.
- Stored GitHub rules: `new` cooks the stored prompt when no bind exists. `single` steers a live job or cooks in that thread. The host bot is the principal. Not a webhook.

## 0.5.19

More dest is here or host. The panel Gateway reconnects after a peer reset.

- Files here lists the folder in Discord. Browser here returns a link the tapping client opens. Terminal dest is host.
- Discord does not send which client tapped. Presence is not a dest.
- Gateway lookup failures and ConnectionResetError reconnect. A REST blip no longer kills listen.

## 0.5.18

HOST briefs parked and failed jobs before last Done.

- Latest run per task. Order is parked, failed, live, then Done.
- The HOST line is Need / Live / Last. The Jobs select uses the same ranking.
- No second board and no pull-queue.

## 0.5.17

Thinking stays on the card. Done is the spoken summary.

- The live card puts reasoning in a fenced zone. The body is the answer.
- Process diary is dropped from the Done body. A matching fence is omitted.

## 0.5.16

A Discord 503 after the thread opens no longer leaves an empty thread.

- REST retries 502 / 503 / 504. Auth failures stay fail-closed.
- A failed first card does not kill the job. The worker still runs.

## 0.5.15

Approve write and Done stay in the job thread.

- Write-gate park edits the live thread card. It does not post Approve write in the parent channel.
- Approve resumes the same thread and the same card.
- HOST stays in the channel.

## 0.5.14

The job stays in the thread. The parent channel does not get a leftover line.

- No parent-channel TLDR. The channel stays the ask plus the thread starter.
- The live card keeps the start of the current beat so the thought chain stays readable.
- A stream phase change resets the token buffer. Done uses the start of the answer, not a mid-word tail.

## 0.5.13

The job thread is the cowork space. Done is a deliverable or a named failure.

- OpenRouter 401 no longer settles as OK plus "Worker finished without a written answer." The card speaks the dead key and the run is FAILED.
- FINDING lines keep the body. Scaffolding memories do not poison the next prompt.
- The live 3:21 AM 5thnode ask was this bug: provider died, Discord painted green.

## 0.5.12

Public copy names the host computer, not a harness UI.

- GitHub, PyPI, README, CLI `--help`, and feature docs lead with Discord as the screen and this Mac as SQLite + JobPool + Puppetmaster.
- Artifacts stay snowflake IDs plus sha256. Phone is the remote.

## 0.5.11

SQLite execution lineage. Retry parents a new run. Activities stay never.

- Each run records intake / dispatch / finding / diff / settle nodes. Done cites sha256. `discord-os lineage` dumps the DAG.
- Steer appends a lineage node. Retry queues `replay_of` at the previous tip. A dead process still fails closed; this is not Temporal.
- The live Components v2 card is the console. Discord Activities stay never.

## 0.5.10

Steer, claim-before-watermark, analyze-without-implement, cwd write lock, and REST-poll of live job threads.

- Live-thread follow-ups flush into the Cursor CLI worker (sidecar + stdin). Analyze omits `--implement --allow-dirty`.
- Claim inbound before advancing the listen watermark. Duplicate claims do not spawn a second job.
- Implement and swarm serialize on resolved realm cwd. The listen loop drains live job thread ids over REST. Gateway stays buttons-only.
- CLI cost/tokens survive the safe summary filter. The 3.11 job-pool timing assert is 2.5s, not 0.45s.

## 0.5.9

AWS names as Discord OS analogs, queryable from the host.

- `discord-os map` reads packaged JSON (`S3` is snowflake objects, not a CDN URL). Text and JSON both include world lifts.
- Ranks are shipped / now / next / never. World lifts (arxiv lineage, OpenHands durable handles, Restate approve-and-wait) sit in the same catalog.
- Docs: [docs/aws](docs/aws/README.md).

## 0.5.8

Live-thread follow-ups steer the running worker. Long Done answers split; the channel gets one TLDR line.

- A message in a live job thread calls `orchestrator.steer` instead of starting a sibling. Idle-thread follow-ups still start a new job.
- Long public Done answers settle as 2–3 thread messages at sentence boundaries. Short answers stay one message.
- Parent channel gets a one-line TLDR. Start and Done reactions land on the user message.
- Public card text drops mid-sentence scaffolding and repeated bodies.

## 0.5.7

README shots are the live HOST card plus a job thread, and two asks cooking.

## 0.5.6

PyPI listing leads with `pip install discord-os`. Doc links on the package page go to GitHub, not pypi.org paths.

## 0.5.5

Reply-first job threads, persist-then-settle, and host GitHub auth.

- New channel asks open a Discord thread on the user message and post the live card ("On it.") before the worker starts.
- Token flushes edit that one card. Meaningful beats settle as normal thread messages so history survives edits.
- In-thread follow-ups stay in the same thread (steer) and keep thread history.
- Worker monologue and host-reach / `gh auth login` dumps never reach Discord.
- `discord-os add github` writes `GH_TOKEN` into the host `.env`. Workers inherit host PATH + tokens.
- Unauthenticated `gh` paints a one-line how-to and Done. No worker essay.
- HOST card shows a github row (ok / sign-in). More includes GitHub.
