"""HOST Page-shaped CV2 layout (Band A thin fallback).

Spike of ``discord-kagekit`` failed for Discord OS (Interaction-centric
``LayoutView``, random Tab custom_ids, buttons disabled without handlers —
fights REST/FakeDiscord + stable ``discord-os:*`` custom IDs).

This module steals kagekit's **layout contract** only:
tabs/status card inside Container(s); **action bar outside** the Container.
Uses in-tree ``layout.py`` dicts — same JobPool/HOST custom IDs.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Sequence

from agent_discord.discord.layout import (
    FLAG_COMPONENTS_V2,
    container,
    separator,
    text_display,
)


def host_page_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Feature flag. Default ON — thin Page layout. Set ``0`` to restore monolith."""

    source = env if env is not None else os.environ
    raw = str(source.get("DISCORD_OS_HOST_PAGE") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def kagekit_spike_adopted() -> bool:
    """Always False after Band A spike — kept for docs/tests honesty."""

    return False


def split_host_v2_components(
    *,
    title: str,
    description: str,
    fields: Sequence[tuple[str, str, bool]] = (),
    color: Optional[int] = None,
    action_rows: Optional[list[dict[str, Any]]] = None,
    update_pill: str = "",
) -> list[dict[str, Any]]:
    """Build top-level CV2: status Container + outer action rows (kagekit-shaped)."""

    live = (title or "").strip() == "Running"
    table_lines = [
        f"`power`  {'on' if live else 'off'}",
        f"`listen`  {'live' if live else 'idle'}",
    ]
    for name, value, _inline in fields:
        table_lines.append(f"`{name}`  {value}")
    body_bits: list[str] = [f"### {title}"]
    pill = (update_pill or "").strip()
    desc = (description or "").strip()
    if pill:
        body_bits.append(pill)
    if desc:
        body_bits.append(desc)
    body_bits.append("\n".join(table_lines))
    children: list[dict[str, Any]] = [
        text_display("\n\n".join(body_bits)),
        separator(divider=True, spacing=1),
        text_display("-# Discord OS  ·  board + brain lakes"),
    ]
    accent = 0x6E6E6E if color is None else int(color)
    top: list[dict[str, Any]] = [container(children, color=accent)]
    for row in action_rows or []:
        if isinstance(row, dict):
            top.append(row)
    return top


def host_v2_payload(
    *,
    title: str,
    description: str,
    fields: Sequence[tuple[str, str, bool]] = (),
    color: Optional[int] = None,
    action_rows: Optional[list[dict[str, Any]]] = None,
    update_pill: str = "",
) -> dict[str, Any]:
    return {
        "flags": FLAG_COMPONENTS_V2,
        "components": split_host_v2_components(
            title=title,
            description=description,
            fields=fields,
            color=color,
            action_rows=action_rows,
            update_pill=update_pill,
        ),
    }
