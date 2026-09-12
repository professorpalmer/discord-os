"""Non-blocking Discord polls for preference-style asks (Discord-half P2).

Live gate holds (write Approve/Deny, AskUserQuestion that parks the worker)
stay on Components cards via ``raise_ask_user`` / ``ask_user_question_card``.
Native Discord polls are **only** for non-blocking, fire-and-forget choices
(style / preference surveys). They must never replace a live gate hold.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from agent_discord.orchestration.ask_gate import AskOption


class LiveGatePollError(ValueError):
    """Raised when a caller tries to use a poll for a live gate hold."""


def refuse_live_gate_poll(*, live: bool) -> None:
    """Hard guard: live holds never become Discord polls."""

    if live:
        raise LiveGatePollError(
            "Denied. Live gate holds use Components cards, not Discord polls."
        )


def _poll_options(
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


def build_nonblocking_poll(
    question: str,
    options: Sequence[AskOption | Mapping[str, Any] | str],
    *,
    allow_multiselect: bool = False,
    duration_hours: int = 24,
    live: bool = False,
) -> dict[str, Any]:
    """Build a Discord message ``poll`` object for a non-blocking ask.

    Discord caps answers at 10; we keep at most 10 labels. Empty options
    fail closed (no poll body).
    """

    refuse_live_gate_poll(live=live)
    q = (question or "").strip() or "Choose one."
    parsed = _poll_options(options)
    if not parsed:
        raise ValueError("Denied. No options provided for non-blocking poll.")
    hours = max(1, min(int(duration_hours or 24), 768))
    answers = []
    for opt in parsed[:10]:
        label = (opt.label or "Option")[:55]
        answers.append({"poll_media": {"text": label}})
    return {
        "question": {"text": q[:300]},
        "answers": answers,
        "duration": hours,
        "allow_multiselect": bool(allow_multiselect),
        "layout_type": 1,
    }


def post_nonblocking_ask_poll(
    *,
    token: str,
    channel_id: str,
    question: str,
    options: Sequence[AskOption | Mapping[str, Any] | str],
    thread_id: Optional[str] = None,
    content: str = "",
    allow_multiselect: bool = False,
    duration_hours: int = 24,
    live: bool = False,
    opener: Any = None,
) -> Any:
    """POST a preference poll. Never parks a gate; never for ``live=True``."""

    refuse_live_gate_poll(live=live)
    from agent_discord.discord.rest import send_channel_message

    poll = build_nonblocking_poll(
        question,
        options,
        allow_multiselect=allow_multiselect,
        duration_hours=duration_hours,
        live=False,
    )
    return send_channel_message(
        token=token,
        channel_id=channel_id,
        content=content or "",
        thread_id=thread_id,
        poll=poll,
        opener=opener,
    )


__all__ = [
    "LiveGatePollError",
    "build_nonblocking_poll",
    "post_nonblocking_ask_poll",
    "refuse_live_gate_poll",
]
