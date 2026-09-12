"""HOST Need / Waiting / Live / Last from SQLite job rows.

Waiting is work-queue attention (external checks), not a run status.
"""

from __future__ import annotations

from typing import Any, Mapping

from agent_discord.contracts import JOB_CODE_PREFIX

ATTENTION_NEED = "need"
ATTENTION_WAITING = "waiting"

PREFIX_NEED = "Need"
PREFIX_WAITING = "Waiting"
PREFIX_LIVE = "Live"
PREFIX_LAST = "Last"

DEFAULT_CONTINUE_PROMPT = "Continue from the last tip in this thread."


def job_attention(job: Mapping[str, Any]) -> str:
    return str(job.get("attention") or "").strip().lower()


def briefing_prefix(job: Mapping[str, Any]) -> str:
    status = str(job.get("status") or "").strip()
    attention = job_attention(job)
    if status in {"pending", "failed"} or attention == ATTENTION_NEED:
        return PREFIX_NEED
    if attention == ATTENTION_WAITING:
        return PREFIX_WAITING
    if status in {"running", "progress"}:
        return PREFIX_LIVE
    return PREFIX_LAST


def briefing_line(job: Mapping[str, Any]) -> str:
    prefix = briefing_prefix(job)
    status = str(job.get("status") or "").strip()
    code = str(job.get("job_code") or "").strip()
    text = str(job.get("summary") or job.get("intake_text") or "").replace("\n", " ")
    text = " ".join(text.split())
    if len(text) > 80:
        text = text[:77] + "..."
    mid = " ".join(part for part in (code, status) if part)
    head = f"{prefix}: {mid}" if mid else prefix
    if text:
        return f"{head} · {text}"
    return head


def is_job_code(value: str) -> bool:
    raw = (value or "").strip().upper()
    if not raw.startswith(JOB_CODE_PREFIX):
        return False
    digits = raw[len(JOB_CODE_PREFIX) :]
    return bool(digits) and digits.isdigit()


def normalize_job_code(value: str) -> str:
    raw = (value or "").strip().upper()
    if is_job_code(raw):
        return f"{JOB_CODE_PREFIX}{raw[len(JOB_CODE_PREFIX):]}"
    return raw


def is_idle_job(job: Mapping[str, Any]) -> bool:
    """Completed / failed / cancelled runs are idle session tips."""

    status = str(job.get("status") or "").strip().lower()
    return status in {"completed", "failed", "cancelled"}
