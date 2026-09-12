# Plan-mode Approve card (P2.8)

Implement Gate (write-gate Allow / Always / Deny) is the blunt tool. **Plan →
Approve** is safer phone cowork in the c-lord ExitPlanMode shape: the worker
finishes a plan, Discord parks with **Approve / Cancel**, and the phone
greenlights implement. No **Always** on this card — that stays write-gate only
unless intentional.

Full Puppetmaster ExitPlanMode / plan-hook wiring is **deferred**. This page is
the Discord park / resume seam + adapter contract. Fail closed when plan text
or status is unknown.

## What shipped

| Seam | Behavior |
|---|---|
| Decision | `plan_ready_decision(plan_text, plan_status=)` → `ask` / `deny` |
| Empty / unknown | **Fail closed** (`deny`, reason `unknown plan` / `unknown plan status`) |
| Discord card | `plan_approve_card` / `raise_plan_approve` — **Approve / Cancel** |
| Timeout | Same `DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` auto-deny as write-gate |
| Spoken | Exact `Approve` / `Allow` / `Deny` / `Cancel` in the parked thread (never Always) |
| Reactive | `reactive_paint(awaiting_plan=True)` → actions `plan` |

## How adapters signal plan-ready

```python
from agent_discord.orchestration.plan_approve import plan_ready_decision

decision = plan_ready_decision(plan_text, plan_status="ready")
if decision.decision == "deny":
    # empty plan or unknown status — do not invent a plan
    return deny(decision.reason)
# ask — park the Discord card and wait for gate_result
orch.raise_plan_approve(
    run_id,
    plan_text=decision.plan_text,
    summary="Edit backend then flush the card.",
    plan_status="ready",
)
# later: orch.gate_result_for(run_id) → gate_result allow|deny
# allow → proceed to implement; deny / expire → stop
```

Do **not** call `raise_plan_approve` with an empty plan body. Known
`plan_status` tokens: `ready`, `complete`, `completed`, `done`, `plan_ready`,
`awaiting_approval`, `parked`, or empty (treated as ready when body is present).

Puppetmaster stream phase `plan` / `plan_summary` is informational today — the
adapter (or a future PM plan-hook) must call `raise_plan_approve` explicitly
when the plan phase is done and implement must wait for the phone.

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

## Deferred

- Puppetmaster / agent SDK ExitPlanMode hook that blocks the worker until the
  Discord button resolves
- Auto-park from stream phase transitions alone
- Always-allow for plans (intentional write-gate only)

## Code

- `src/agent_discord/orchestration/plan_approve.py` — decision, card, spoken parse
- `src/agent_discord/orchestration/reactive.py` — `ACTIONS_PLAN` / `awaiting_plan`
- `src/agent_discord/orchestration/cards.py` — `job_action_row(..., actions="plan")`
- `src/agent_discord/orchestration/orchestrator.py` — `raise_plan_approve` / resolve
- `src/agent_discord/orchestration/listen.py` — spoken Approve / Deny / Cancel
- Tests: `tests/test_plan_approve.py`
