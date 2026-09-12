# Non-blocking Ask polls (Discord-half P2)

Discord **native polls** are available only for fire-and-forget preference /
style choices. They never park a worker and never replace a live gate hold.

| Surface | When | Mechanism |
|---|---|---|
| Live AskUserQuestion / write gate | Worker blocked (`live=True`) | Components card (`ask_user_question_card` / Approve-Deny) |
| Non-blocking preference ask | Survey only — no gate park | `build_nonblocking_poll` / `post_nonblocking_ask_poll` |

Hard guard: `refuse_live_gate_poll(live=True)` raises `LiveGatePollError`.

Code: `src/agent_discord/orchestration/ask_poll.py`.
REST: optional `poll=` on `send_channel_message`.

## Surfaces (EXTRAS)

| Surface | Notes |
|---|---|
| CLI | `discord-os poll --channel-id ID --question "…" --option A --option B` |
| HOST More | **Post preference poll** → modal (question + comma-separated options) |

Both call `post_nonblocking_ask_poll(..., live=False)`. Live ask-gate cards are untouched.

