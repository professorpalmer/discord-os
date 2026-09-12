"""Plan-mode Approve card — c-lord ExitPlanMode shape (live hold).

Implement Gate (write-gate) is binary Allow / Always / Deny for writes.
Plan → Approve is safer phone cowork: park when a plan is ready, greenlight
implement with **Approve / Cancel** (no Always).

Live path: agentic PreToolUse / ExitPlanMode **or** plan_status-ready
signals / PresentPlan (or in-process ``request_plan_hold``) calls
``plan_ready_decision`` then parks via ``raise_plan_approve`` and **blocks
implement** until Allow / Deny / timeout. Plan Approve does not rely solely
on ExitPlanMode.
Reuse approval timeout; never Always on this card. Fail closed when plan
text or status is unknown. Docs: ``docs/cards/plan-approve.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from agent_discord.orchestration.cards import (
    COLOR_WORK,
    CardMessage,
    job_action_row,
)
from agent_discord.orchestration.reactive import reactive_paint
from agent_discord.redaction import redact_text_markers

GATE_KIND_PLAN = "plan_approve"

# PreToolUse / agentic tool names that mean "plan ready — park Approve".
# Not limited to ExitPlanMode — PresentPlan / plan_ready / SubmitPlan also park.
_EXIT_PLAN_ALIASES = frozenset(
    {
        "exitplanmode",
        "exit_plan_mode",
        "exit-plan-mode",
        "exitplan",
        "exit_plan",
        "plan_approve",
        "planapprove",
        "raise_plan_approve",
        "presentplan",
        "present_plan",
        "submitplan",
        "submit_plan",
        "plan_ready",
        "planready",
        "ready_plan",
        "readyplan",
    }
)


def is_exit_plan_tool(tool_name: str) -> bool:
    """True when the tool name itself is a plan-ready / ExitPlanMode alias."""

    text = (tool_name or "").strip()
    if not text:
        return False
    compact = text.lower().replace("-", "_")
    if compact in _EXIT_PLAN_ALIASES:
        return True
    if "__" in compact:
        tail = compact.rsplit("__", 1)[-1]
        if tail in _EXIT_PLAN_ALIASES:
            return True
    folded = text.replace("_", "").replace("-", "").lower()
    if folded in {
        "exitplanmode",
        "presentplan",
        "submitplan",
        "planready",
        "readyplan",
    }:
        return True
    return False


def plan_status_from_tool_input(tool_input: Any) -> str:
    """Pull plan_status / status from tool input when adapters signal plan-ready."""

    if not isinstance(tool_input, Mapping):
        return ""
    for key in ("plan_status", "planStatus", "status", "state"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def is_plan_ready_signal(tool_name: str = "", tool_input: Any = None) -> bool:
    """True when plan Approve should park — ExitPlanMode *or* plan_status body.

    Plan hold must not rely solely on ExitPlanMode. Adapters may pass
    ``plan_status=ready`` (with plan text) on any tool, or use PresentPlan /
    plan_ready names. Empty / unknown status still fail closed via
    ``plan_ready_decision``.
    """

    if is_exit_plan_tool(tool_name):
        return True
    status = plan_status_from_tool_input(tool_input)
    if not status:
        return False
    normalized = normalize_plan_status(status)
    if normalized is None:
        return False
    # Empty status token is only "ready" when body present — defer to decision.
    body = plan_text_from_tool_input(tool_input)
    if not body.strip():
        return False
    # Known ready-ish statuses (including "" which normalize keeps).
    return True


def plan_text_from_tool_input(tool_input: Any) -> str:
    """Extract plan body from ExitPlanMode / plan-ready tool input."""

    if isinstance(tool_input, str):
        return redact_text_markers(tool_input.strip())[:4000]
    if not isinstance(tool_input, Mapping):
        return ""
    for key in (
        "plan",
        "plan_text",
        "planText",
        "summary",
        "message",
        "text",
        "content",
        "body",
    ):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return redact_text_markers(value.strip())[:4000]
    return ""


# Statuses adapters may pass when signalling plan-ready. Unknown → fail closed.
KNOWN_PLAN_STATUSES = frozenset(
    {
        "",
        "ready",
        "complete",
        "completed",
        "done",
        "plan_ready",
        "awaiting_approval",
        "parked",
    }
)

DENIED_PLAN_SPOKEN = "Denied. Plan was not approved."
EXPIRED_PLAN_SPOKEN = "Expired. Plan was not approved."
APPROVED_PLAN_SPOKEN = "Approved. Implement may proceed."

_SPOKEN_APPROVE = frozenset(
    {"approve", "approved", "allow", "allowed", "yes", "y", "ok", "okay", "go"}
)
_SPOKEN_DENY = frozenset(
    {
        "deny",
        "denied",
        "no",
        "n",
        "reject",
        "cancel",
        "cancelled",
        "canceled",
        "stop",
    }
)


@dataclass(frozen=True)
class PlanReadyDecision:
    """Adapter-facing plan gate. ``ask`` means raise the Discord Approve card."""

    decision: str  # ask | deny
    reason: str = ""
    plan_text: str = ""


def normalize_plan_status(raw: str) -> Optional[str]:
    """Map plan status to a known token. Unknown → None (fail closed)."""

    text = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in KNOWN_PLAN_STATUSES:
        return text
    return None


def plan_ready_decision(
    plan_text: str = "",
    *,
    plan_status: str = "",
) -> PlanReadyDecision:
    """Decide whether to park an Approve / Cancel card.

    Fail closed: empty plan body or unknown ``plan_status`` → deny.
    """

    body = redact_text_markers((plan_text or "").strip())
    if not body:
        return PlanReadyDecision(
            decision="deny",
            reason="unknown plan",
            plan_text="",
        )
    status = (plan_status or "").strip()
    if status:
        known = normalize_plan_status(status)
        if known is None:
            return PlanReadyDecision(
                decision="deny",
                reason="unknown plan status",
                plan_text=body,
            )
    return PlanReadyDecision(decision="ask", reason="plan ready", plan_text=body)


def parse_spoken_plan_verb(text: str) -> Optional[str]:
    """Map phone prose to approve / deny for a plan park. No Always. Else None."""

    raw = (text or "").strip().lower()
    if not raw:
        return None
    compact = " ".join(raw.split())
    # Never treat Always as plan greenlight — that is write-gate only.
    if compact.startswith("always"):
        return None
    if compact in _SPOKEN_APPROVE:
        return "approve"
    if compact in _SPOKEN_DENY:
        return "deny"
    return None


def describe_plan(plan_text: str, *, max_len: int = 900) -> str:
    tip = redact_text_markers((plan_text or "").strip())
    if not tip:
        return "(empty plan)"
    if len(tip) <= max_len:
        return tip
    return tip[: max_len - 3] + "..."


def plan_approve_card(
    run_id: str,
    *,
    plan_text: str,
    message: str = "",
    summary: str = "",
) -> CardMessage:
    """c-lord ExitPlanMode-shaped Approve / Cancel card (no Always)."""

    body = describe_plan(plan_text)
    header = redact_text_markers(
        (message or summary or "Plan ready. Approve to implement, or Cancel.").strip()
    )
    description = f"{header}\n\n{body}" if header else body
    paint = reactive_paint(awaiting_plan=True)
    return CardMessage(
        kind="PLAN",
        title=paint.stage,
        description=description,
        color=paint.accent or COLOR_WORK,
        fields=(
            ("Plan", body[:500], False),
        ),
        rows=(job_action_row(run_id, actions=paint.actions),),
    )


def plan_meta_payload(
    *,
    plan_text: str,
    summary: str = "",
    parked_at_ms: int,
) -> dict[str, Any]:
    """Task metadata patch for a parked plan Approve card."""

    body = redact_text_markers((plan_text or "").strip())[:4000]
    return {
        "awaiting_approval": True,
        "awaiting_gate": True,
        "awaiting_plan": True,
        "gate_kind": GATE_KIND_PLAN,
        "gate_class": "plan",
        "gate_detail": redact_text_markers((summary or "").strip())[:500],
        "gate_question": "",
        "gate_options": [],
        "gate_result": "",
        "gate_answer": "",
        "plan_text": body,
        "parked_at_ms": int(parked_at_ms),
    }


def is_plan_gate_meta(meta: Mapping[str, Any] | None) -> bool:
    if not isinstance(meta, Mapping):
        return False
    if str(meta.get("gate_kind") or "") == GATE_KIND_PLAN:
        return True
    return bool(meta.get("awaiting_plan"))
