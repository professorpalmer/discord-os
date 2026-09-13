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
| Multi-select Confirm | `allow_multiple=True` — toggle options, then **Confirm** (or Deny); empty Confirm stays parked |
| Prefs | `tool_class_allow:<class>:<scope>` TTL (4h), cleared on HOST Off with write Always |
| Timeout | Same `DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` auto-deny as write-gate |
| Spoken | Exact `Allow` / `Deny` / `Always allow` in the parked thread resolves the gate |

## Live hold (P0)

Phone Allow / Deny / Always **blocks the live worker** mid-cook.

1. `tool_class_decision` → `allow` / `ask` / `deny`
2. `ask` parks a Discord card (`raise_tool_gate` / `raise_ask_user` with `live=True`)
3. The worker blocks until `gate_result_for` (or the result file) is
   `allow` / `always` / `deny`, or the approval timeout self-denies.

In-process adapters call `AgentOrchestrator.request_tool_hold`. Puppetmaster
agentic is a subprocess and has no in-process `canUseTool`, so Discord OS
stamps a durable file-queue on every agentic spawn:

```text
DISCORD_OS_GATE_DIR      per-run pending/ + results/
DISCORD_OS_GATE_ROOT     <workspace>/gates
DISCORD_OS_RUN_ID        live run id
DISCORD_OS_GATE_HOOK     discord-os gate-hook
```

Attach the PreToolUse-shaped CLI (stdin JSON, stdout `permissionDecision`,
**always exit 0**):

```bash
discord-os gate-hook
discord-os gate-hook --print-attach
```

Local agentic cooks also get `PYTHONPATH=<gate_inject>:…` so
`sitecustomize.py` wraps Puppetmaster `AgenticAdapter._execute_tool` and
**really invokes** that CLI before each tool (not env-stamp-only).

Listen/orch drains `pending/`, parks the card, and writes `results/` when
the phone (or spoken Allow / Deny / Always, or expire) resolves it. Fail
closed: unanswered → deny. Shapes stolen (not cloned): albertorsesc
PreToolUse hold, DisCode CLI hooks, dis-claude atomic file-queue.

## How adapters request a gate

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
# live worker: orch.request_tool_hold(run_id, tool_name, detail=preview)
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

orch.raise_ask_user(
    run_id,
    question="Which topics?",
    options=["Auth", "Billing", "Docs"],
    allow_multiple=True,
)
# toggle options → Confirm → gate_answer "Auth, Billing"; empty Confirm ignored
```

Do **not** invent a tool class. If `normalize_tool_class` returns `None`, deny.
Known classes: `shell`, `write`, `edit`, `browser`, `network`, `git`, `mcp`,
`ask`, `implement`, `read`. `read` always allows (no card). Aliases
(`Bash` → `shell`, `AskUserQuestion` → `ask`, `run_terminal` → `shell`) live
in `ask_gate.py`.

## custom_ids

| Button | custom_id |
|---|---|
| Allow / Always / Deny (tool or write park) | `discord-os:job:approve\|always\|deny:<run_id>` |
| Ask option N | `discord-os:ask:<run_id>:<N>` |
| Ask multi Confirm | `discord-os:ask-confirm:<run_id>` |

Write-gate park (whole implement) and tool-class park share the job button
prefix. Metadata `awaiting_gate` routes approve/always/deny to the tool/ask
resolver instead of resuming an implement.

## Residual

- **Local agentic PreToolUse now fires**: every local OpenRouter/agentic spawn
  prepends `orchestration/gate_inject/` onto `PYTHONPATH` so CPython loads
  `sitecustomize.py`, which wraps `AgenticAdapter._execute_tool` and runs
  `discord-os gate-hook` before each tool. Deny / timeout → tool does not run.
  Write-gate off / session Always still auto-allow via listen drain (no card).
- **Path A SSH gates (live bridge)**: set `DISCORD_OS_SSH_GATES=bridge` so
  remote cook emits `DISCORD_OS_GATE_PENDING` markers, this Mac mirrors them
  into `DISCORD_OS_GATE_*`, listen parks phone Allow / Deny / Always (or
  Ask / Plan) cards, and Path A SSH-writes results back to the remote queue.
  Fail closed when bridge cannot arm (missing `run_id` / wrap failure) —
  never silent ungated writes while bridge was requested. Default unset:
  write-gate on → spoken **Need** + remote Deny inject (honest gap).
  Analyze/read passthrough on the remote inject; ControlMaster auto when
  unset so writeback multiplexes with the cook. Cancel Denies pending bridged
  holds (no Allow writeback after Cancel); stale ControlMaster cleared before
  writeback.
- ~~Per-tool (exact tool name) allowlists beyond class~~ — Always remembers
  the exact tool (`gate_tool` / `tool_exact_allow:`); wildcards rejected
- ~~Multi-select AskUserQuestion confirm row~~ — `allow_multiple=True` toggles
  + Confirm; empty Confirm fail-closed

## Code

- `src/agent_discord/orchestration/ask_gate.py` — decision, cards, spoken parse
- `src/agent_discord/orchestration/gate_hook.py` — file queue, hold, hook CLI
- `src/agent_discord/orchestration/service.py` — tool-class session prefs
- `src/agent_discord/orchestration/orchestrator.py` — `request_tool_hold` /
  `raise_tool_gate` / `raise_ask_user` / resolve
- `src/agent_discord/puppetmaster/agentic.py` — stamps gate env + PYTHONPATH inject on spawn
- `src/agent_discord/orchestration/gate_inject/sitecustomize.py` — wraps agentic `_execute_tool`
- `src/agent_discord/orchestration/ssh_gate.py` — Path A gap Deny inject + live bridge
- `src/agent_discord/host/panel.py` — ask button → `on_job("ask", run#idx)`
- `src/agent_discord/orchestration/listen.py` — spoken Allow / Deny / Always;
  drain pending hook files
- CLI: `discord-os gate-hook`
- Tests: `tests/test_ask_gate.py`
