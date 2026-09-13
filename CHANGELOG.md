# Changelog

## Unreleased

### TIDY ALL polish (pre-0.5.57)

- **Quiet listen drain / Errno 49**: REST retries `TimeoutError` and transient
  OSError (macOS **EADDRNOTAVAIL=49**, reset/refused/unreachable) in addition to
  URLError / 502–504. Listen quiet-logs those after retries — **no fake Gateway
  READY**. `note_gateway_expected` no longer sets `connected=True`.
- **HARD locks policy page**: [`docs/host/policy.md`](docs/host/policy.md)
  stamps all 10 locks (SSH bridge OPT-IN, no forum auto-tags, Path A never
  silent local, single gateway, Update=PyPI, voice local TTS/memo, spend
  honesty, desk single-user OK, slash self-heal, CU/docker PARKED).
- **Slash self-heal residual**: pass `listen --guild-id` / `DISCORD_GUILD_ID`
  into version-aware register.
- **Forum tags soak**: extra status name aliases (todo/active/blocked/cancel/
  stopped/…); doctor WARN when forum realm lacks a status tag map; still never
  auto-creates guild `available_tags`.
- Doctor tip cites policy locks; `.env.example` documents `DISCORD_OS_SSH_GATES`
  OPT-IN + `DISCORD_GUILD_ID`.

## 0.5.56

Policy #7 slash self-heal (tip `e713a0a`).

### Policy #7 — slash self-heal

- When `AGENT_DISCORD_INTERACTIONS` is exposed (http/public), the listen host
  **self-heals** slash registration (same as `discord-os interactions --register`).
- **Version-aware**: re-registers when installed package version or opt-in
  command-set stamp differs; stamp in workspace `slash_registration.json`.
- **Fail soft** if missing `DISCORD_APPLICATION_ID` / bot token / public key —
  WARN + doctor honesty; host does not crash. Manual `--register` optional.
- Docs: [slash](docs/host/slash.md), setup. Module:
  `maybe_self_heal_slash_registration`.

## 0.5.55

Next-wave ship: SSH live gate bridge, forum tags-as-tickets, Path A edge races, voice DAVE fail-closed + local TTS/memo, CI drain flake (tip `9751530`).

### Voice (next-wave #4) — DAVE-honest join surface

- Re-checked Discord guild voice join for the phone-remote model: lasting join
  needs Gateway Opcode 4 + voice WS + UDP, and since **2026-03-01** **DAVE
  E2EE** (libdave; close **4017**). Discord OS does not ship that stack.
- `join_voice_channel` still **Deny** (no half-wired Opcode 4). Opt-in
  `DISCORD_OS_VOICE_JOIN=1` remains intent-only, not an unlock.
- `leave_voice_channel` idle no-op (never holds a live session).
- `speak_in_voice_channel` / `listen_in_voice_channel` parked **Deny** (no
  guild duplex TTS/STT). Local Mac TTS + voice memos unchanged.
- `layout.voice_state_update` payload helper (does not send).
- `voice_capabilities()` matrix; doctor WARN cites DAVE / 4017.
- Docs: [voice](docs/host/voice.md). Tests: `test_tts.py`, half-p2 voice.

### Path A edge races (beyond 0.5.54 Cancel/progress)

- **Orphaned remote PIDs after Mac crash**: remote wrap keeps bash as process-group
  leader with HUP/INT/TERM trap + parent-death watchdog (no `exec`); durable
  remote-pid sidecar + `reap_orphaned_remote_pids` on next Path A cook.
- **ControlMaster socket stale**: `ensure_ssh_controlmaster_fresh` (`ssh -O check`
  → `-O exit` / unlink literal path) before cook spawn and gate-bridge writeback.
- **Gate-bridge writeback races with Cancel**: Cancel Denies pending bridged holds
  and skips Allow/Always SSH writeback (fail closed; remote unblocks).
- **Settle-vs-Cancel / SSH exit vs Discord settle**: Cancel wins over a late
  COMPLETED receipt — orchestrator settle re-checks Cancelled before final
  `update_run` / Done paint; Path A stream prefers CANCEL over RECEIPT/ERROR
  once Cancel is requested.
- **Progress-marker loss on reconnect**: GATE_PENDING already mirrored locally
  survives a dead multiplex socket; stale ControlMaster cleared before writeback
  so Allow is not lost on a hung master. Mid-pipe SSH drop still fail-closed
  (honest Deny / Cancel) — no silent local cook.

Tests: `test_cancel_honesty.py`, `test_remote_cook.py`.
Docs: [compute](docs/compute/README.md), [ask-gate](docs/cards/ask-gate.md).

### Forum tags-as-tickets (forum-as-realm deepen)

- Honest Discord **forum tag ↔ JobPool ticket status** mapping when the forum
  already has `available_tags` named like queued / running / done / failed /
  cancelled (aliases listed in [realms](docs/realms/README.md)).
- On job start and terminal settle, `PATCH` the post thread's `applied_tags`
  (preserve non-status tags; Discord max 5). Soft-skip when no status tags
  exist; spoken **Need** on ACL miss. Does **not** invent guild tags or a
  second job system.
- Bind/probe caches `tags_as_tickets` + `status_tag_ids` on the forum binding;
  discovery remembers each post's `applied_tags`.
- REST: `modify_channel` / `set_thread_applied_tags`. Tests:
  `tests/test_forum_tags_as_tickets.py`.

### SSH live gate bridge (Path A)

- **`DISCORD_OS_SSH_GATES=bridge`**: phone Allow / Deny / Always (and Ask /
  Plan parks) hold the remote Path A worker mid-cook. Remote sitecustomize
  emits `DISCORD_OS_GATE_PENDING` markers; Mac mirrors into the local gate
  queue; listen parks Discord cards; Path A SSH-writes results back.
  ControlMaster auto when unset. Fail closed when bridge cannot arm.
- Default unset unchanged: write-gate on → spoken Need + remote Deny inject
  (honest gap). Docs: [ask-gate](docs/cards/ask-gate.md), host README.
- Tests: `tests/test_remote_cook.py` bridge wrap / pending / fail-closed.

### CI drain flake

- Loosen JobPool drain timing assert for CI jitter:
  `test_drain_with_pool_returns_while_jobs_run` lost a strict <hold wall
  check by ~0.2ms on Actions 3.11. Soften to hold+0.1s and assert backends
  have not all finished when drain returns.

## 0.5.54

Polish Wave 1+2 + HOST Update-available pill (tip `faed868`).

### Polish Wave 1 — swarm-incomplete honesty + Path A Cancel races

- **Swarm-incomplete honesty (DOS-10036 class)**: when agentic / `workers:0` /
  analyze-only streams a usable prose answer then Puppetmaster exits
  `swarm exited with incomplete tasks`, Discord OS salvages the spoken answer
  as **Completed** instead of painting a false failed Need. Backend exit
  parsing, Path A remote cook, and orchestrator settle all share
  `salvage_swarm_incomplete_answer`. Real provider failures stay Failed.
- **Path A Cancel / progress races**: dual stdout/stderr PID echo; brief wait
  for `DISCORD_OS_REMOTE_PID` before remote `kill`; optional ControlMaster via
  `DISCORD_OS_SSH_CONTROL_PATH` (auto on cook argv); keep remote pid while
  Cancel races unregister; orchestrator Cancel hits the **active SSH cook
  backend** (not only local agentic). Progress pipe stays honest; never silent
  local cook for `kind=ssh`.

Tests: `test_swarm_incomplete_honesty.py`, `test_cancel_honesty.py`.
Docs: [jobs](docs/jobs/README.md), [compute](docs/compute/README.md),
[reactive](docs/cards/reactive.md).

### Polish Wave 2 — vault probe, slash re-register, Roles/poll honesty

- **Remote OpenRouter vault probe deepen**: Path A BatchMode probe reports
  `openrouter=env|vault|vault-sealed|missing`. `vault` means entry + `master.key`
  (decrypt-ready presence); `vault-sealed` is honest WARN/Deny (entry without
  master — cannot decrypt). No secrets on argv / probe stdout.
- **Slash re-register after upgrade**: docs/copy stress
  `discord-os interactions --register` after pip upgrade so phone autocomplete
  and new slash options land.
- **Roles / poll honesty**: Roles stays **modal-only** (no ephemeral Roles
  fantasy). Preference poll remains non-blocking — never a live gate replace.

### HOST Update-available pill

- HOST master-controller card shows **Update available · X.Y.Z** when the
  installed `discord-os` version is behind PyPI latest. Fail soft when PyPI is
  unreachable. No auto-upgrade. Disable with `DISCORD_OS_UPDATE_CHECK=0`.
- Upgrade: `pip install -U discord-os` into the host venv, then bounce the
  LaunchAgent (`discord-os host restart` / kick `com.discord-os.host`).


## 0.5.53

Discord-half EXTRAS — forum-as-realm experiment, slash deepen, poll surfaces, voice honesty.

### Forum-as-realm (scoped experiment)

- Bind a Discord **forum** (type 15) as a normal realm; new forum posts →
  existing **JobPool** intake with `thread_id = post thread`. Not a second job
  system.
- Fail closed with spoken **Need** when channel is not a forum (`--forum`) or
  bot cannot list active threads (missing perms).
- `discord-os add realm NAME --channel-id ID --forum`; in-channel `bind`
  auto-marks forums after REST probe.
- Catalog `forum-tags` rank **experiment** (was never). Docs:
  [realms](docs/realms/README.md).

### Slash deepen

- Richer `/job` ephemeral (task/run/intake/settle/dest).
- Optional `/clear-needs` (requires `failed=True`; optional `dry_run`).
- Re-run `discord-os interactions --register` after upgrade. Docs:
  [slash](docs/host/slash.md).

### Polls (non-blocking only)

- CLI `discord-os poll --channel-id … --question … --option …`
- HOST More → **Post preference poll** modal.
- Still never replaces live ask-gate cards (`live=True` refuses).

### Voice honesty

- Clearer spoken Deny when `DISCORD_OS_VOICE_JOIN` is set (not an unlock).
- `discord-os host doctor` **WARN** while that env is set. Still no real join.

## 0.5.52

Discord-half haul complete — P0–P2 from 0.5.50 through 0.5.52.

### Discord-half haul complete (0.5.50–0.5.52)

- **P0 Dismiss / thread-bind / panel refresh / clear-needs (0.5.50)**: failed-card
  Dismiss/Ack; always bind job threads; HOST Jobs panel refresh after settle;
  bulk `jobs clear-needs --failed` (+ HOST More).
- **P1 accent+Section / File / dos:router / ACK-first / ephemeral Pair-Gate
  (0.5.51)**: Need/Live/Done chrome + accent; settle File; persistent
  `dos:<verb>:<jobCode>:<nonce>` router; ACK-first then edit-in-place;
  ephemeral Pair/Gate Confirm-Cancel menus.
- **P2 slash autocomplete / non-blocking polls / forum skip / voice honesty
  (0.5.52)**: opt-in `/bind` + `/job` autocomplete; polls only for non-blocking
  asks (`live=True` hard-refuses); forum-as-realm skipped; `DISCORD_OS_VOICE_JOIN`
  reserved spoken Deny (stub only).

### Discord-half P2 (10–13) — slash autocomplete, non-blocking polls, forum skip, voice honesty

- **Slash progressive enhancement (opt-in)**: `/bind name` and new read-only
  `/job code` register with Discord autocomplete (realms / memory / host ids;
  recent `DOS-*`). Text listen + HOST panel remain default. No `/add`.
- **Polls only for non-blocking asks**: `ask_poll.build_nonblocking_poll` /
  `post_nonblocking_ask_poll` post Discord native polls for preference-style
  choices. Live gate holds stay on Components cards — `live=True` hard-refuses
  polls (`LiveGatePollError`). Docs: [ask-poll](docs/cards/ask-poll.md).
- **Forum-as-realm**: **skipped** (not S–M; would duplicate JobPool; catalog
  `forum-tags` rank **never**). Documented in [realms](docs/realms/README.md).
- **Voice honesty polish**: `DISCORD_OS_VOICE_JOIN` reserved but still spoken
  Deny; TTS opt-in still does not unlock join. Stub only — not a desk/voice
  product. Docs: [voice](docs/host/voice.md).

## 0.5.51

Discord-half P1 pack — accent+Section chrome, File settle, dos: router, ACK-first, ephemeral Pair/Gate.

### Discord-half P1 (5–9) — chrome, File, dos: router, ACK-first, ephemeral menus

- **Accent + Section by job state**: job cards and HOST Jobs chrome use Need /
  Live / Done Section layout + matching `accent_color` (Waiting ranks Live).
- **File on settle/fail**: size-capped Components V2 File for last log/diff when
  present (`error.log` fallback on fail).
- **Persistent `dos:<verb>:<jobCode>:<nonce>` router**: restart-safe job buttons
  (legacy `discord-os:job:` still parses). Resolve via SQLite job_code + nonce.
- **ACK-first then edit-in-place**: panel / Jobs / gates defer (type 6) then
  edit; ephemeral Confirm paths repaint HOST by `card_message_id`.
- **Ephemeral operator menus**: Pair / Gate Confirm-Cancel menus; Roles keeps
  modal (feasible). Docs: [reactive](docs/cards/reactive.md),
  [host](docs/host/README.md), [jobs](docs/jobs/README.md).
  Tests: `test_discord_half_p1.py`.

## 0.5.50

Discord-half P0 pack — Dismiss, thread bind, panel refresh, clear-needs.

### Discord-half P0 pack

- **P0.1 Dismiss / Ack failed Need**: failed cards show **Dismiss**;
  `apply_job_action("dismiss"|"ack")` → cancelled/`dismissed`, clears GitHub
  attention Need, briefing ranks **Last**. HOST Jobs → Dismiss.
- **P0.2 Always bind job thread**: channel-parent asks with empty `thread_id`
  always create a Discord job thread; fail closed with spoken **Need** on
  create failure (incl. rate limit).
- **P0.3 HOST Jobs panel refresh**: after dismiss/ack/cancel settle, edit Jobs
  select + Need line immediately; recover/repaint panel when id missing;
  spoken **Need** once if neither possible.
- **P0.4 Bulk clear stale failed Needs**: CLI `jobs clear-needs --failed`
  (+ `--older-than` / `--channel-id` / `--dry-run`); HOST More → **Clear failed
  Needs** with confirm; refreshes panel (P0.3).

Docs: [cli](docs/cli/README.md), [jobs](docs/jobs/README.md),
[host](docs/host/README.md), [cards](docs/cards/README.md),
[reactive](docs/cards/reactive.md).
Tests: `test_dismiss_failed_need.py`, `test_bind_job_thread.py`,
`test_host_jobs_panel_refresh.py`, `test_clear_failed_needs.py`.

## 0.5.49

Round-4 complete — reliability haul from 0.5.43 through 0.5.49 (P0–P2).

### Round-4 complete (P0–P2 highlights since 0.5.43)

- **Cancel honesty (0.5.43)**: spoken Cancel / abort paths match what Discord shows.
- **Path A progress (0.5.44)**: remote SSH cook progress and honesty improvements.
- **Live gate-hook (0.5.45)**: local agentic PreToolUse really fires via sitecustomize inject.
- **ARG_MAX handoff (0.5.46)**: oversized prompts spill to stdin/file instead of E2BIG.
- **Remote SSH doctor (0.5.47)**: cook-capable hosts probed for remote CLI + OpenRouter.
- **P1 pack (0.5.48)**: watchdog install, never-READY Need, exact-tool Always, plan hold,
  REQUIRE_OPERATORS when exposed, SSH gates honesty (Need + remote write Deny).
- **AskUser multi-select (0.5.49)**: `allow_multiple` parks toggle options + Confirm/Deny;
  empty Confirm stays parked (Need).

### Round-4 P2 (scoped)

- **AskUserQuestion multi-select Confirm row**: `raise_ask_user(..., allow_multiple=True)`
  parks toggle option buttons + **Confirm** / Deny. Empty Confirm stays parked
  (Need). Single-select unchanged (immediate option resolve); five options keep
  Deny on a second row. Gate-hook reads `allow_multiple` / `allowMultiple` /
  `multiSelect` from ask tool input. Docs: [ask-gate](docs/cards/ask-gate.md).
- **Deferred**: SSH gate live Discord bridge — still not shipped (not M-sized / not
  honest as phone cards). Need + remote write Deny inject remain the Path A
  contract; `DISCORD_OS_SSH_GATES=bridge` reserved.
- Daemon/mux/queue + voice: no Round-4 honesty leftover beyond shipped spikes
  (Cancel / inbound queue / voice Deny stubs already honest).

## 0.5.48

Round-4 P1 pack: watchdog real install, never-READY Need, exact-tool Always, plan hold without ExitPlanMode, REQUIRE_OPERATORS when Interactions exposed, SSH gates honesty.

### Round-4 P1 pack

- **Watchdog real install**: `install_doctor_notify_watchdog` + `host doctor
  --install-watchdog` / setup / host start write the live LaunchAgent (not
  example-only). Docs: liveness.
- **Never-READY Need**: panel gateway marks `note_gateway_expected`; quiet
  forever past grace → HOST Need / doctor FAIL. Cold start still quiet.
- **Exact-tool Always**: Always remembers the concrete tool (`tool_exact_allow:` /
  `gate_tool`); wildcards rejected; class-wide Always no longer from exact.
- **Plan hold without ExitPlanMode**: `is_plan_ready_signal` parks Approve on
  PresentPlan / plan_ready / `plan_status=ready` body — not ExitPlanMode-only.
- **REQUIRE_OPERATORS when exposed**: public Interactions auto-require
  operators (dispatch + doctor harden).
- **Gates across SSH**: live Discord hold still local-only; write-gate on →
  spoken Need + remote write/edit/shell Deny inject (honest Path A). Bridge
  reserved (`DISCORD_OS_SSH_GATES=bridge`).

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
