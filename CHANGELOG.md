# Changelog

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
