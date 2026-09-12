# Per-tool / AskUserQuestion gate (P1.4)

Coarse HOST **Always allow** is a footgun on a shared Mac. The phone needs
surgical approve: one tool class, or one AskUserQuestion, with Allow / Deny
(and Always for that class this session). Steal DisCode write-gate chrome and
zebbern / c-lord permission + AskUserQuestion button patterns — not Activities.

## What shipped

| Seam | Behavior |
|---|---|
| Tool-class decision | `tool_class_decision(store, name, channel_id=, thread_id=)` → `allow` / `ask` / `deny` |
| Unknown class | **Fail closed** (`deny`, reason `unknown tool class`) |
| Discord tool card | `tool_gate_card` / `raise_tool_gate` — Allow / Always allow / Deny |
| AskUserQuestion card | `ask_user_question_card` / `raise_ask_user` — option buttons + Deny |
| Prefs | `tool_class_allow:<class>:<scope>` TTL (4h), cleared on HOST Off with write Always |
| Timeout | Same `DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` auto-deny as write-gate |
| Spoken | Exact `Allow` / `Deny` / `Always allow` in the parked thread resolves the gate |

## How PM / adapters request a gate

Full agent-hook (`canUseTool` / Puppetmaster hook) integration is **deferred**.
Adapters and host tools should:

```python
from agent_discord.orchestration.ask_gate import tool_class_decision
from agent_discord.orchestration.ask_gate import normalize_tool_class

decision = tool_class_decision(
    store, tool_name, channel_id=channel_id, thread_id=thread_id
)
if decision.decision == "deny":
    # unknown class or explicit deny — do not run the tool
    return deny(decision.reason)
if decision.decision == "allow":
    return run_tool(...)
# ask — park the Discord card and wait for gate_result
orch.raise_tool_gate(run_id, tool_class=decision.tool_class, detail=preview)
# later: orch.gate_result_for(run_id) → gate_result allow|always|deny
```

AskUserQuestion:

```python
orch.raise_ask_user(
    run_id,
    question="Ship the patch?",
    options=["Yes", "Later", "No"],
)
# option button → gate_answer label; Deny → gate_result deny
```

Do **not** invent a tool class. If `normalize_tool_class` returns `None`, deny.
Known classes: `shell`, `write`, `edit`, `browser`, `network`, `git`, `mcp`,
`ask`, `implement`. Aliases (`Bash` → `shell`, `AskUserQuestion` → `ask`) live
in `ask_gate.py`.

## custom_ids

| Button | custom_id |
|---|---|
| Allow / Always / Deny (tool or write park) | `discord-os:job:approve\|always\|deny:<run_id>` |
| Ask option N | `discord-os:ask:<run_id>:<N>` |

Write-gate park (whole implement) and tool-class park share the job button
prefix. Metadata `awaiting_gate` routes approve/always/deny to the tool/ask
resolver instead of resuming an implement.

## Deferred

- Puppetmaster / agent SDK `canUseTool` hook that blocks the worker until the
  Discord button resolves
- Per-tool (exact tool name) allowlists beyond class
- Multi-select AskUserQuestion confirm row

## Code

- `src/agent_discord/orchestration/ask_gate.py` — decision, cards, spoken parse
- `src/agent_discord/orchestration/service.py` — tool-class session prefs
- `src/agent_discord/orchestration/orchestrator.py` — `raise_tool_gate` /
  `raise_ask_user` / resolve
- `src/agent_discord/host/panel.py` — ask button → `on_job("ask", run#idx)`
- `src/agent_discord/orchestration/listen.py` — spoken Allow / Deny / Always
- Tests: `tests/test_ask_gate.py`
