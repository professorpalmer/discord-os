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

from agent_discord import PRODUCT_NAME
from agent_discord.discord.layout import (
    FLAG_COMPONENTS_V2,
    container,
    discord_time,
    section,
    separator,
    text_display,
    thumbnail,
)


def host_page_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Feature flag. Default ON — thin Page layout. Set ``0`` to restore monolith."""

    source = env if env is not None else os.environ
    raw = str(source.get("DISCORD_OS_HOST_PAGE") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def kagekit_spike_adopted() -> bool:
    """Always False after Band A spike — kept for docs/tests honesty."""

    return False


POWER_ON = "on"
POWER_OFF = "off"
POWER_HALTED = "halted"

# Titles that are painted while the host is still armed. "Stop?" is the Off
# confirm screen: power stays on until Confirm, and "Halted" is armed intake
# that is holding new jobs.
_ARMED_TITLES = {"Running": POWER_ON, "Stop?": POWER_ON, "Halted": POWER_HALTED}


def power_from_host_title(title: str) -> str:
    """Fallback for callers that do not carry the host power state."""

    return _ARMED_TITLES.get((title or "").strip(), POWER_OFF)


def host_power_table(power: str) -> tuple[tuple[str, str], ...]:
    """`power` / `listen` rows. Armed-but-halted is on + halted, never off."""

    state = (power or "").strip() or POWER_OFF
    if state == POWER_HALTED:
        return (("power", POWER_ON), ("listen", POWER_HALTED))
    if state == POWER_ON:
        return (("power", POWER_ON), ("listen", "live"))
    return (("power", POWER_OFF), ("listen", "idle"))


def host_power_lines(power: str) -> list[str]:
    return [f"`{name}`  {value}" for name, value in host_power_table(power)]


def split_host_v2_components(
    *,
    title: str,
    description: str,
    fields: Sequence[tuple[str, str, bool]] = (),
    color: Optional[int] = None,
    action_rows: Optional[list[dict[str, Any]]] = None,
    update_pill: str = "",
    avatar_url: str = "",
    updated_ts: Optional[int] = None,
    power: str = "",
) -> list[dict[str, Any]]:
    """Build top-level CV2: status Container + outer action rows (kagekit-shaped)."""

    table_lines = host_power_lines(power or power_from_host_title(title))
    for name, value, _inline in fields:
        table_lines.append(f"`{name}`  {value}")
    heading = f"### {title}"
    pill = (update_pill or "").strip()
    desc = (description or "").strip()
    head_lines = [heading]
    if pill:
        head_lines.append(pill)
    if desc:
        head_lines.append(desc)
    children: list[dict[str, Any]] = []
    face = (avatar_url or "").strip()
    if face:
        children.append(section(head_lines[:3], thumbnail(face)))
        leftover = head_lines[3:]
        if leftover:
            children.append(text_display("\n\n".join(leftover)))
    else:
        children.append(text_display("\n\n".join(head_lines)))
    children.append(text_display("\n".join(table_lines)))
    stamp = discord_time(updated_ts)
    footer = f"-# {PRODUCT_NAME}  ·  board + brain lakes  ·  {stamp}"
    children.extend(
        [
            separator(divider=True, spacing=1),
            text_display(footer),
        ]
    )
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
    avatar_url: str = "",
    updated_ts: Optional[int] = None,
    power: str = "",
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
            avatar_url=avatar_url,
            updated_ts=updated_ts,
            power=power,
        ),
    }
