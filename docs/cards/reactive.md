# Reactive cards (P1.6 / P2.14)

One live Components v2 card per job. That card already reacts: write-gate park swaps in Allow / Always allow / Deny; a live cook shows Cancel; an idle session tip shows Continue. This page names that mapping so the next paint does not invent a second button set.

Seam finish for P1.6 (spike was P2.14). It is not a product rewrite. Discord Activities stay never. There is no client UI.

## What exists today

The live card is a `FLAG_COMPONENTS_V2` container edited in the job thread (`send_card` / `edit_card`). Button rows come from `job_action_row` in `cards.py` via the reactive seam. HOST Jobs, write-gate park, ask-gate parked rows, live cook flushes, and settle/deny receipts all route through it.

| State | How we get there | Buttons | Accent | Stage |
|---|---|---|---|---|
| parked | write-gate implement, HOST Jobs on `pending`, or mid-run tool/ask gate ([ask-gate](ask-gate.md)) | Allow / Always allow / Deny | work gold | Allow write / tool |
| plan | plan-ready park ([plan-approve](plan-approve.md)) | Approve / Cancel | work gold | Approve plan |
| running | live cook | **Cancel** (phone interrupt on the live v2 card) | work gold | Working |
| idle | Done / Cancelled **and** a job thread | Continue | live / idle | Done / Cancelled |
| failed | Failed **and** a job thread | Continue + **Dismiss** | fail | Failed |
| failed_done | Failed without a session thread | Continue + Retry + **Dismiss** | fail | Failed |
| done | settled receipt without a session thread | Continue + Retry | receipt chrome | receipt title |

`progress` without a live-running flag still paints **done** (Continue + Retry). Live flushes go through `reactive_progress_card` (Cancel). Settle with a job thread paints **idle** Continue (Done / Cancelled); **failed** paints Continue + Dismiss (or Continue + Retry + Dismiss without a thread). That split is owned by `reactive_paint(..., has_thread=)`.

Custom ids prefer restart-safe `dos:<verb>:<jobCode>:<nonce>` when a speakable job code is known; legacy `discord-os:job:<verb>:<run_id>` still parses. Verbs are approve / always / deny / cancel / retry / continue / dismiss (ack alias). They never toggle HOST power and they never dispatch Puppetmaster by themselves — `apply_job_action` does that. Job cards use Need / Live / Done Section chrome + accent. Cancel is the phone interrupt for a live cook — tap the job-thread card, not HOST Off. **Dismiss** acks a failed Need (marks cancelled / clears attention) so HOST briefing ranks Last; HOST Jobs panel refreshes on dismiss/cancel settle (P0.3).

Parked Allow expires after `DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` (default 20) with spoken `Expired. Write was not started.`

## Framework (the seam)

`src/agent_discord/orchestration/reactive.py` is the single source of truth:

```text
SQLite job row / status + thread
  → reactive_paint / reactive_for_job
      → ReactivePaint(actions, accent, stage)
          → reactive_working_card / reactive_progress_card / reactive_receipt_card
          → job_action_row(run_id, actions=paint.actions)
          → HOST Jobs reprint (`_publish_job_card`)
```

Do not hardcode `actions="parked"` / `"running"` / `"idle"` / `"done"` at park, live, or settle call sites — ask the seam. Card builders still accept `actions=` for tests and explicit overrides. Do not add a widget tree, a render loop, or a second card type.

## What we will not build yet

- Discord Activities. The v2 card is the console. Presence `working_presence` is a status line, not an Activity app.
- A full client UI, a dashboard rewrite of the card, or a React/web component that mirrors buttons.
- Per-token re-layout, inner-scroll APIs Discord does not have, or a generic reactive widget kit.
- New verbs beyond Allow / Always / Deny / Continue / Cancel / Retry / **Dismiss**.
- Voice join + TTS — see [../host/voice.md](../host/voice.md) (P2.13 spike; out of scope for cards).

## Code

- `src/agent_discord/orchestration/reactive.py` — `ReactivePaint`, `reactive_paint` (`awaiting_plan` → `ACTIONS_PLAN`), `reactive_for_job`, `reactive_working_card`, `reactive_progress_card`, `reactive_receipt_card`
- `src/agent_discord/orchestration/cards.py` — builders + `job_action_row`
- `src/agent_discord/orchestration/orchestrator.py` — park / running / settle / deny via reactive helpers
- `src/agent_discord/orchestration/ask_gate.py` — tool / ask parked rows via `reactive_paint`
- `src/agent_discord/host/panel.py` — HOST Jobs reprint via `reactive_for_job`
- Tests: `tests/test_reactive_cards.py`, `tests/test_cards.py`, `tests/test_write_gate_buttons.py`

## Cancel honesty (P0.1)

Phone **Cancel** on a live cook must interrupt the worker, not just paint
SQLite `cancelled`.

| Path | Kill | Confirmed paint |
|---|---|---|
| Local agentic | SIGTERM → SIGKILL process group of the tracked `puppetmaster agentic` child | Cancelled |
| Path A SSH | Remote `kill` on echoed `DISCORD_OS_REMOTE_PID` (stdout+stderr; brief wait), optional ControlMaster `-O exit` via `DISCORD_OS_SSH_CONTROL_PATH`, then local ssh process-group kill. Orchestrator cancels the active SSH cook backend. Cancel wins over late Completed settle; bridge pending → Deny (no Allow writeback). | Cancelled |
| No live child / kill fails | Spoken **Cancel unconfirmed**; status stays running (`cancellation_pending`) | Do **not** paint Done/Cancelled |

Receipts are gjc-remote-shaped: `confirmed` vs `cancellation_pending`. Plan-park Cancel still denies ExitPlanMode (not a live-cook interrupt).

