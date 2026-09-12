"""P1.4 Per-tool / AskUserQuestion gate — Discord card seam.

Coarse Always-allow is a footgun on a shared Mac; the phone needs
surgical approve. This module is the zebbern / DisCode-shaped seam:

- tool-class Allow / Always allow / Deny cards mid-run
- AskUserQuestion option buttons
- fail closed when the tool class is unknown

Full Puppetmaster / agent-hook ``canUseTool`` wiring is deferred.
PM and host adapters should call ``tool_class_decision`` then
``AgentOrchestrator.raise_tool_gate`` / ``raise_ask_user``. Docs:
``docs/cards/ask-gate.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from agent_discord.discord.layout import CUSTOM_ID_MAX
from agent_discord.orchestration.cards import (
    COLOR_WORK,
    CardMessage,
    job_action_row,
)
from agent_discord.orchestration.reactive import reactive_paint
from agent_discord.redaction import redact_text_markers

ASK_ID_PREFIX = "discord-os:ask:"
GATE_KIND_TOOL = "tool_class"
GATE_KIND_ASK = "ask_user"

# Canonical classes adapters may request. Unknown → fail closed.
KNOWN_TOOL_CLASSES = frozenset(
    {
        "shell",
        "write",
        "edit",
        "browser",
        "network",
        "git",
        "mcp",
        "ask",
        "implement",
    }
)

_TOOL_CLASS_ALIASES = {
    "bash": "shell",
    "shell": "shell",
    "terminal": "shell",
    "run_command": "shell",
    "write": "write",
    "createfile": "write",
    "create_file": "write",
    "edit": "edit",
    "multiedit": "edit",
    "strreplace": "edit",
    "browser": "browser",
    "webfetch": "network",
    "websearch": "network",
    "network": "network",
    "fetch": "network",
    "git": "git",
    "gh": "git",
    "mcp": "mcp",
    "ask": "ask",
    "askuserquestion": "ask",
    "ask_user": "ask",
    "ask_user_question": "ask",
    "implement": "implement",
    "write_gate": "implement",
}

DENIED_TOOL_SPOKEN = "Denied. Tool was not allowed."
EXPIRED_TOOL_SPOKEN = "Expired. Tool was not allowed."
DENIED_ASK_SPOKEN = "Denied. Question was not answered."
EXPIRED_ASK_SPOKEN = "Expired. Question was not answered."
ALLOWED_TOOL_SPOKEN = "Allowed."
ALWAYS_TOOL_SPOKEN = "Always allowed for this class this session."

_SPOKEN_ALLOW = frozenset({"allow", "allowed", "approve", "yes", "y", "ok", "okay"})
_SPOKEN_DENY = frozenset({"deny", "denied", "no", "n", "reject", "block"})
_SPOKEN_ALWAYS = frozenset(
    {
        "always",
        "always allow",
        "always-allow",
        "alwaysallowed",
        "allow always",
    }
)


@dataclass(frozen=True)
class AskOption:
    """One selectable AskUserQuestion choice."""

    label: str
    description: str = ""


@dataclass(frozen=True)
class AskAction:
    """Parsed AskUserQuestion button intent."""

    run_id: str
    option_index: int


@dataclass(frozen=True)
class ToolClassDecision:
    """Adapter-facing gate decision. ``ask`` means raise a Discord card."""

    decision: str  # allow | ask | deny
    tool_class: str = ""
    reason: str = ""


def normalize_tool_class(raw: str) -> Optional[str]:
    """Map a tool name to a known class. Unknown → None (fail closed)."""

    text = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    if text in KNOWN_TOOL_CLASSES:
        return text
    mapped = _TOOL_CLASS_ALIASES.get(text)
    if mapped is not None:
        return mapped
    # Strip provider prefixes like mcp__server__tool
    if "__" in text:
        tail = text.rsplit("__", 1)[-1]
        if tail in KNOWN_TOOL_CLASSES or tail in _TOOL_CLASS_ALIASES:
            return normalize_tool_class(tail)
    return None


def tool_class_decision(
    store: Any,
    tool_class: str,
    *,
    channel_id: str = "",
    thread_id: str = "",
    write_gate_on: Optional[bool] = None,
) -> ToolClassDecision:
    """Decide allow / ask / deny for a tool class.

    Fail closed: unknown class → deny. When the coarse write-gate is off,
    known classes allow (surgical gate is opt-in on top of write-gate).
    Session Always for that class skips the card.
    """

    from agent_discord.orchestration.service import (
        tool_class_session_allows,
        writes_need_approval,
    )

    canonical = normalize_tool_class(tool_class)
    if canonical is None:
        return ToolClassDecision(
            decision="deny",
            tool_class=(tool_class or "").strip(),
            reason="unknown tool class",
        )
    if tool_class_session_allows(store, canonical, thread_id) or tool_class_session_allows(
        store, canonical, channel_id
    ):
        return ToolClassDecision(
            decision="allow",
            tool_class=canonical,
            reason="session always allow",
        )
    # AskUserQuestion always surfaces a card (unless session-always on class ask).
    if canonical == "ask":
        return ToolClassDecision(decision="ask", tool_class=canonical, reason="ask user")
    gated = writes_need_approval(store) if write_gate_on is None else bool(write_gate_on)
    if not gated:
        return ToolClassDecision(decision="allow", tool_class=canonical, reason="write gate off")
    return ToolClassDecision(decision="ask", tool_class=canonical, reason="needs approval")


def ask_custom_id(run_id: str, option_index: int) -> str:
    rid = (run_id or "").strip()
    prefix = f"{ASK_ID_PREFIX}{rid}:"
    budget = max(0, CUSTOM_ID_MAX - len(prefix))
    idx = str(int(option_index))[:budget]
    return prefix + idx


def ask_action_from_custom_id(custom_id: str) -> Optional[AskAction]:
    raw = (custom_id or "").strip()
    if not raw.startswith(ASK_ID_PREFIX):
        return None
    rest = raw[len(ASK_ID_PREFIX) :]
    run_id, sep, idx_raw = rest.rpartition(":")
    if not sep or not run_id.strip():
        return None
    try:
        option_index = int(idx_raw.strip())
    except ValueError:
        return None
    if option_index < 0:
        return None
    return AskAction(run_id=run_id.strip(), option_index=option_index)


def parse_spoken_gate_verb(text: str) -> Optional[str]:
    """Map phone/desktop prose to approve / always / deny. Else None."""

    raw = (text or "").strip().lower()
    if not raw:
        return None
    compact = " ".join(raw.split())
    if compact in _SPOKEN_ALWAYS or compact.startswith("always allow"):
        return "always"
    # Exact short verbs only — do not steal "please allow writes in foo".
    if compact in _SPOKEN_ALLOW:
        return "approve"
    if compact in _SPOKEN_DENY:
        return "deny"
    return None


def describe_tool_action(tool_class: str, detail: str = "") -> str:
    klass = normalize_tool_class(tool_class) or (tool_class or "tool").strip()
    tip = redact_text_markers((detail or "").strip())
    if tip:
        clipped = tip if len(tip) <= 240 else tip[:237] + "..."
        return f"Use `{klass}`: {clipped}"
    return f"Use tool class `{klass}`"


def tool_gate_card(
    run_id: str,
    *,
    tool_class: str,
    detail: str = "",
    message: str = "",
) -> CardMessage:
    """DisCode-style Allow / Always allow / Deny for one tool class."""

    klass = normalize_tool_class(tool_class) or (tool_class or "tool").strip() or "tool"
    action = describe_tool_action(klass, detail)
    body = redact_text_markers(message or f"Allow `{klass}`?\n{action}")
    return CardMessage(
        kind="GATE",
        title=f"Allow {klass}",
        description=body,
        color=COLOR_WORK,
        fields=(
            ("Class", f"`{klass}`", True),
            ("Detail", action, False),
        ),
        rows=(job_action_row(run_id, actions=reactive_paint(awaiting_approval=True).actions),),
    )


def ask_user_question_card(
    run_id: str,
    *,
    question: str,
    options: Sequence[AskOption | Mapping[str, Any] | str],
    header: str = "Need input",
) -> CardMessage:
    """AskUserQuestion Discord card — option buttons, fail closed if empty."""

    from agent_discord.discord.layout import STYLE_PRIMARY, action_row, button

    q = redact_text_markers((question or "").strip() or "Choose one.")
    parsed = _coerce_options(options)
    if not parsed:
        return CardMessage(
            kind="ASK",
            title=header or "Need input",
            description=q + "\n\nDenied. No options provided.",
            color=COLOR_WORK,
            rows=(job_action_row(run_id, actions=reactive_paint(awaiting_approval=True).actions),),
        )
    items = []
    fields: list[tuple[str, str, bool]] = []
    for idx, opt in enumerate(parsed[:5]):
        label = (opt.label or f"Option {idx + 1}")[:80]
        items.append(
            button(label, ask_custom_id(run_id, idx), style=STYLE_PRIMARY)
        )
        desc = opt.description or label
        fields.append((f"{idx + 1}. {label}", redact_text_markers(desc)[:200], True))
    # Also offer Deny so the phone can bail without picking.
    from agent_discord.host.actions import job_custom_id
    from agent_discord.discord.layout import STYLE_DANGER

    items.append(button("Deny", job_custom_id("deny", run_id), style=STYLE_DANGER))
    return CardMessage(
        kind="ASK",
        title=header or "Need input",
        description=q,
        color=COLOR_WORK,
        fields=tuple(fields),
        rows=(action_row(items),),
    )


def _coerce_options(
    options: Sequence[AskOption | Mapping[str, Any] | str],
) -> list[AskOption]:
    out: list[AskOption] = []
    for raw in options or ():
        if isinstance(raw, AskOption):
            label = (raw.label or "").strip()
            if label:
                out.append(AskOption(label=label, description=raw.description or ""))
            continue
        if isinstance(raw, Mapping):
            label = str(raw.get("label") or raw.get("value") or "").strip()
            if not label:
                continue
            desc = str(raw.get("description") or raw.get("detail") or "").strip()
            out.append(AskOption(label=label, description=desc))
            continue
        label = str(raw or "").strip()
        if label:
            out.append(AskOption(label=label))
    return out


def gate_meta_payload(
    *,
    kind: str,
    tool_class: str = "",
    detail: str = "",
    question: str = "",
    options: Sequence[AskOption | Mapping[str, Any] | str] = (),
    parked_at_ms: int,
) -> dict[str, Any]:
    """Task metadata patch for a parked tool / ask gate."""

    parsed = _coerce_options(options)
    return {
        "awaiting_approval": True,
        "awaiting_gate": True,
        "gate_kind": kind,
        "gate_class": normalize_tool_class(tool_class) or (tool_class or "").strip(),
        "gate_detail": redact_text_markers(detail or "")[:500],
        "gate_question": redact_text_markers(question or "")[:500],
        "gate_options": [
            {"label": opt.label, "description": opt.description} for opt in parsed
        ],
        "gate_result": "",
        "gate_answer": "",
        "parked_at_ms": int(parked_at_ms),
    }
