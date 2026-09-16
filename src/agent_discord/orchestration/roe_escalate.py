"""OCL-shaped ROE escalate copy on Halt / gate Deny (Wave 6 P2d).

Wording + receipt only — no new control plane. Spoken Need-style escalate
when spend Halt blocks intake or a write/ask/plan gate Denies.
"""

from __future__ import annotations

from typing import Any, Optional


def format_halt_escalate(*, reason: str = "") -> str:
    """Need-style escalate when HOST spend Halt blocks new jobs."""

    why = (reason or "").strip() or "spend Halt is on"
    return (
        f"Need: ROE escalate — {why}. "
        "Resume only after an operator clears Halt (economic gate). "
        "OCL-shaped wording; no new control plane."
    )


def format_deny_escalate(
    *,
    tool: str = "",
    reason: str = "",
    gate_kind: str = "write",
) -> str:
    """Need-style escalate when a gate Denies before env mutation."""

    kind = (gate_kind or "write").strip() or "write"
    tip = (reason or "").strip() or "Denied before env mutation"
    tool_bit = (tool or "").strip()
    prefix = f"Need: ROE escalate ({kind}"
    if tool_bit:
        prefix += f"/{tool_bit}"
    prefix += ") — "
    return (
        f"{prefix}{tip}. "
        "Pair or Allow with an operator; do not silent-continue. "
        "OCL-shaped wording; no new control plane."
    )


def escalate_for_halt_receipt() -> str:
    """Summary/error text for halted intake receipt."""

    return format_halt_escalate()


def escalate_for_deny(
    *,
    spoken: str = "",
    tool: str = "",
    gate_kind: str = "write",
) -> str:
    """Prefer existing spoken when already Need-shaped; else wrap Deny."""

    body = (spoken or "").strip()
    if body.lower().startswith("need:"):
        return body
    if body and "roe escalate" in body.lower():
        return body
    # Preserve short Deny tip inside escalate copy.
    return format_deny_escalate(tool=tool, reason=body or "Denied", gate_kind=gate_kind)


def is_escalate_copy(text: str) -> bool:
    tip = (text or "").strip().lower()
    return tip.startswith("need:") and "roe escalate" in tip


__all__ = [
    "escalate_for_deny",
    "escalate_for_halt_receipt",
    "format_deny_escalate",
    "format_halt_escalate",
    "is_escalate_copy",
]
