"""P2.8 Plan-mode Approve card — c-lord ExitPlanMode shape.

Implement Gate (write-gate) is binary Allow / Always / Deny for writes.
Plan → Approve is safer phone cowork: park when a plan is ready, greenlight
implement with **Approve / Cancel** (no Always unless intentional write-gate).

Full Puppetmaster ExitPlanMode / plan-hook wiring is deferred. Adapters call
``plan_ready_decision`` then ``AgentOrchestrator.raise_plan_approve``. Fail
closed when plan text or status is unknown. Docs: ``docs/cards/plan-approve.md``.
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
