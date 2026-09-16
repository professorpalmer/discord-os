"""Stall one-liner on Live after N steers without progress (Wave 6 P2e).

Quiet; opt-in via ``DISCORD_OS_STALL_STEERS`` (truthy) and optional
``DISCORD_OS_STALL_N`` (default 3). Single JobPool Live card only.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Sequence


DEFAULT_STALL_N = 3


def stall_opt_in(env: Optional[Mapping[str, str]] = None) -> bool:
    source = os.environ if env is None else env
    raw = str(source.get("DISCORD_OS_STALL_STEERS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def stall_threshold(env: Optional[Mapping[str, str]] = None) -> int:
    source = os.environ if env is None else env
    raw = str(source.get("DISCORD_OS_STALL_N") or "").strip()
    if not raw:
        return DEFAULT_STALL_N
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_STALL_N
    return max(2, min(n, 20))


def count_steers_without_progress(
    steers: Sequence[Mapping[str, Any]],
    *,
    progress_marks: Sequence[Any] = (),
) -> int:
    """How many recent steers landed with no intervening progress mark.

    ``progress_marks`` are timestamps (float) of Done-ish / stage advances.
    Steers after the latest progress mark count toward stall.
    """

    if not steers:
        return 0
    last_progress = 0.0
    for mark in progress_marks or ():
        try:
            ts = float(mark)
        except (TypeError, ValueError):
            continue
        if ts > last_progress:
            last_progress = ts
    n = 0
    for row in steers:
        try:
            ts = float(row.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts >= last_progress:
            n += 1
    return n


def should_show_stall(
    steers: Sequence[Mapping[str, Any]],
    *,
    progress_marks: Sequence[Any] = (),
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    if not stall_opt_in(env):
        return False
    n = count_steers_without_progress(steers, progress_marks=progress_marks)
    return n >= stall_threshold(env)


def format_stall_oneliner(*, steer_count: int = 0, job_code: str = "") -> str:
    """Quiet Live one-liner — no storm."""

    n = max(0, int(steer_count or 0))
    code = (job_code or "").strip()
    prefix = f"{code} · " if code else ""
    return (
        f"{prefix}Stall? {n} steers without progress — "
        "claim/steer with a concrete next step (opt-in)."
    )


__all__ = [
    "DEFAULT_STALL_N",
    "count_steers_without_progress",
    "format_stall_oneliner",
    "should_show_stall",
    "stall_opt_in",
    "stall_threshold",
]
