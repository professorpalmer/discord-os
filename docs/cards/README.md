# Cards

One live card per job. That card lives in the **job thread**, not the channel. Channel-parent asks always bind a job thread first (HOST Ask included). Components v2 is the console (``FLAG_COMPONENTS_V2`` container/section). Embeds are legacy only — ``send_card`` / ``edit_card`` keep a narrow TypeError embed fallback for ancient fakes; production Discord REST always paints v2. Discord Activities stay never. Done is a deliverable or a named failure, not a green card with no answer.

The moment an ask lands, Discord OS opens a thread on the user message and posts "On it." Then the worker starts. A Discord 503 on that first card is retried and does not kill the job. The channel stays free. Write-gate **Approve write** edits that same thread card. Approve resumes the same thread. HOST stays in the channel.

Token flushes edit that same card. Reasoning stays in a fenced thinking zone on the card (Discord's native code-block scroll; there is no inner-scroll API). Combined V2 text stays under 4000 characters, so the fence is clipped so the spoken summary always fits. The card body is the spoken summary, not the diary. When a user-facing summary beat changes (or the job hits Done / Failed), the previous spoken beat is persisted as a normal thread message first (Hermes persist-then-settle). Thinking is not reprinted as thread prose. A long public Done answer splits into 2–3 thread messages at sentence boundaries; the Done card can keep the first bubble and extras follow. Short answers stay one message. Do not post a parent-channel excerpt. Do not settle "On it." / "Starting." / empty / percent-only / prompt-echo / host-reach dumps. Do not spam a new message per token.

Done is the spoken summary after process diary is dropped from the body. The diary can remain inside the thinking fence. Worker monologue (`report:`, host-reach dumps) never reaches Discord as the answer.

Harness cards (`**Card**`, `**Receipt**`, HOST, NOTE) are skipped on intake so the bot does not dispatch itself. HOST stays the settings analog — do not dump metrics into job cards. The HOST job line is Need / Waiting / Live / Last over the same SQLite jobs. It is not a second board. Dest-remote opens (Browser here, Files here) post a separate OPEN card with a Discord link button or a folder listing. They do not open a GUI on the listen Mac.

A follow-up in a **live** job thread steers that worker (or queues in SQLite if the cook cannot take it yet). A follow-up after Done starts a new job in the same thread (session), parented at the prior tip. Do not start a nested thread.

**Cancel** is on the live Components v2 card while the cook is running (`discord-os:job:cancel:<run_id>`). Tap that button on the job-thread card from the phone. It is not HOST Off. If the cook cannot be interrupted, the phone hears **Cancel unconfirmed** (no false Cancelled paint). Parked Allow / Always allow / Deny auto-denies after `DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` (default 20) with a spoken expire.

State → button set / accent / stage (write-gate Allow / Always / Deny, plan Approve / Cancel, Continue) is the [reactive spike](reactive.md). Per-tool / AskUserQuestion mid-run park (live worker hold) is [ask-gate](ask-gate.md). Plan-mode Approve is [plan-approve](plan-approve.md). Not Activities. Not a client UI.

![next-level cards](../screenshots/next-level-cards.png)

## Code

- `src/agent_discord/orchestration/cards.py` — builders, skip rules, `send_card` / `edit_card` (v2 primary)
- `src/agent_discord/orchestration/reactive.py` — state → button set / accent / stage (P2.14 spike)
- `src/agent_discord/orchestration/orchestrator.py` — reply-first thread, one live card, persist-then-settle
- `src/agent_discord/host/panel.py` — HOST + Jobs Continue receipts via `reactive_for_job`
- Tests: `tests/test_cards.py`, `tests/test_reactive_cards.py`, `tests/test_write_gate_buttons.py`, `tests/test_orchestration.py`
- Spike: [reactive.md](reactive.md), [ask-gate.md](ask-gate.md), [plan-approve.md](plan-approve.md)
- Tests: also `tests/test_ask_gate.py`, `tests/test_plan_approve.py`
