# Plan-mode Approve card (ExitPlanMode live hold)

Implement Gate (write-gate Allow / Always / Deny) is the blunt tool. **Plan →
Approve** is safer phone cowork in the c-lord ExitPlanMode shape: the worker
finishes a plan, Discord parks with **Approve / Cancel**, and the phone
greenlights implement. No **Always** on this card — that stays write-gate only.

Live path (not docs-only): agentic PreToolUse / `ExitPlanMode` **or**
`PresentPlan` / `plan_ready` / tool input with `plan_status=ready` + plan body
(file-queue hook), or in-process `request_plan_hold`, parks via
`raise_plan_approve` and **blocks implement** until Allow / Deny / approval
timeout. Plan Approve does **not** rely solely on ExitPlanMode. Fail closed
when plan text or status is unknown.

## What shipped

| Seam | Behavior |
|---|---|
| Decision | `plan_ready_decision(plan_text, plan_status=)` → `ask` / `deny` |
| Empty / unknown | **Fail closed** (`deny`, reason `unknown plan` / `unknown plan status`) |
| Discord card | `plan_approve_card` / `raise_plan_approve` — **Approve / Cancel** |
| Live hold | `request_plan_hold` / gate-hook `ExitPlanMode` → block until resolve |
| Timeout | Same `DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` auto-deny as write-gate |
| Spoken | Exact `Approve` / `Allow` / `Deny` / `Cancel` in the parked thread (never Always) |
| Reactive | `reactive_paint(awaiting_plan=True)` → actions `plan` |

## How adapters / hooks signal plan-ready

```python
# In-process
orch.request_plan_hold(run_id, plan_text=plan, summary="…")

# Or park only (poll gate_result_for yourself)
orch.raise_plan_approve(run_id, plan_text=plan, plan_status="ready")
```

Agentic subprocess: stamp `DISCORD_OS_GATE_*` (same as ask-gate) and attach
`discord-os gate-hook`. When the worker emits `ExitPlanMode` / plan-ready,
the hook enqueues `gate_kind=plan_approve`; listen/orch parks Approve / Cancel
and writes `results/` when the phone resolves. No Always.

Do **not** call `raise_plan_approve` with an empty plan body. Known
`plan_status` tokens: `ready`, `complete`, `completed`, `done`, `plan_ready`,
`awaiting_approval`, `parked`, or empty (treated as ready when body is present).

## custom_ids

| Button | custom_id |
|---|---|
| Approve | `discord-os:job:approve:<run_id>` |
| Cancel | `discord-os:job:cancel:<run_id>` |

Metadata `awaiting_gate` + `gate_kind=plan_approve` (+ `awaiting_plan`) routes
approve / cancel / deny / expire to the plan resolver. Cancel on a plan park
denies the plan; it does not mean live-cook Cancel. Write-gate Always is
ignored on a plan park (fail closed).

Spoken expire: `Expired. Plan was not approved.`

## Code

- `src/agent_discord/orchestration/plan_approve.py` — decision, card, ExitPlanMode detect
- `src/agent_discord/orchestration/gate_hook.py` — live hold / drain for plan kind
- `src/agent_discord/orchestration/orchestrator.py` — `raise_plan_approve` / `request_plan_hold`
- `src/agent_discord/orchestration/listen.py` — spoken Approve / Deny / Cancel
- Tests: `tests/test_plan_approve.py`
