# Reactive cards (P2.14 spike)

One live Components v2 card per job. That card already reacts: write-gate park swaps in Allow / Always allow / Deny; a live cook shows Cancel; an idle session tip shows Continue. This page names that mapping so the next paint does not invent a second button set.

This is a spike. It is not a product rewrite. Discord Activities stay never. There is no client UI.

## What exists today

The live card is a `FLAG_COMPONENTS_V2` container edited in the job thread (`send_card` / `edit_card`). Button rows come from `job_action_row` in `cards.py`. HOST Jobs reprints a receipt through the same row.

| State | How we get there | Buttons | Accent | Stage |
|---|---|---|---|---|
| parked | write-gate implement, HOST Jobs on `pending` | Allow / Always allow / Deny | work gold | Allow write |
| running | live cook | **Cancel** (phone interrupt on the live v2 card) | work gold | Working |
| idle | Done / Failed / Cancelled **and** a job thread | Continue | live / fail / idle | Done / Failed / Cancelled |
| done | settled receipt without a session thread | Continue + Retry | receipt chrome | receipt title |

`progress` without a live-running flag still paints **done** (Continue + Retry). Live flushes pass `actions="running"` explicitly. That split is honest, not a bug to "fix" in this spike.

Custom ids stay `discord-os:job:<verb>:<run_id>`. Verbs are approve / always / deny / cancel / retry / continue. They never toggle HOST power and they never dispatch Puppetmaster by themselves — `apply_job_action` does that. Cancel is the phone interrupt for a live cook — tap the job-thread card, not HOST Off.

Parked Allow expires after `DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` (default 20) with spoken `Expired. Write was not started.`

## Proposed framework (the seam)

`src/agent_discord/orchestration/reactive.py` is the named extension point:

```text
SQLite job row
  → reactive_paint / reactive_for_job
      → ReactivePaint(actions, accent, stage)
          → job_action_row(run_id, actions=paint.actions)
          → working_card / receipt_card / HOST Jobs reprint
```

Callers that already know the mode still pass `actions=`. New surfaces that only have a status + thread id call `reactive_for_job`. Do not add a widget tree, a render loop, or a second card type.

HOST Jobs already uses the seam (`_publish_job_card`). Write-gate park in the orchestrator still passes `actions="parked"` because it already knows it parked.

## What we will not build yet

- Discord Activities. The v2 card is the console. Presence `working_presence` is a status line, not an Activity app.
- A full client UI, a dashboard rewrite of the card, or a React/web component that mirrors buttons.
- Per-token re-layout, inner-scroll APIs Discord does not have, or a generic reactive widget kit.
- New verbs. Allow / Always / Deny / Continue / Cancel / Retry are the set.
- Voice join + TTS — see [../host/voice.md](../host/voice.md) (P2.13 spike; out of scope for cards).

## Code

- `src/agent_discord/orchestration/reactive.py` — `ReactivePaint`, `reactive_paint`, `reactive_for_job`
- `src/agent_discord/orchestration/cards.py` — builders + `job_action_row`
- `src/agent_discord/host/panel.py` — HOST Jobs reprint via `reactive_for_job`
- Tests: `tests/test_reactive_cards.py`, `tests/test_cards.py`, `tests/test_write_gate_buttons.py`
