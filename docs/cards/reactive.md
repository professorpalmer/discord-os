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
| idle | Done / Failed / Cancelled **and** a job thread | Continue | live / fail / idle | Done / Failed / Cancelled |
| done | settled receipt without a session thread | Continue + Retry | receipt chrome | receipt title |

`progress` without a live-running flag still paints **done** (Continue + Retry). Live flushes go through `reactive_progress_card` (Cancel). Settle with a job thread paints **idle** Continue; without a thread paints **done** Continue + Retry. That split is owned by `reactive_paint(..., has_thread=)`.

Custom ids stay `discord-os:job:<verb>:<run_id>`. Verbs are approve / always / deny / cancel / retry / continue. They never toggle HOST power and they never dispatch Puppetmaster by themselves — `apply_job_action` does that. Cancel is the phone interrupt for a live cook — tap the job-thread card, not HOST Off.

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
- New verbs. Allow / Always / Deny / Continue / Cancel / Retry are the set.
- Voice join + TTS — see [../host/voice.md](../host/voice.md) (P2.13 spike; out of scope for cards).

## Code

- `src/agent_discord/orchestration/reactive.py` — `ReactivePaint`, `reactive_paint` (`awaiting_plan` → `ACTIONS_PLAN`), `reactive_for_job`, `reactive_working_card`, `reactive_progress_card`, `reactive_receipt_card`
- `src/agent_discord/orchestration/cards.py` — builders + `job_action_row`
- `src/agent_discord/orchestration/orchestrator.py` — park / running / settle / deny via reactive helpers
- `src/agent_discord/orchestration/ask_gate.py` — tool / ask parked rows via `reactive_paint`
- `src/agent_discord/host/panel.py` — HOST Jobs reprint via `reactive_for_job`
- Tests: `tests/test_reactive_cards.py`, `tests/test_cards.py`, `tests/test_write_gate_buttons.py`
