"""AWS names as Discord OS analogs. Packaged JSON; no network."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Mapping, Optional, Sequence

RANKS = frozenset({"shipped", "now", "next", "never"})


@dataclass(frozen=True)
class Analog:
    aws: str
    discord: str
    module: str
    rank: str
    note: str
    source: str = ""


@dataclass(frozen=True)
class Lift:
    id: str
    title: str
    rank: str
    adapt: str
    source: str = ""


def load_catalog() -> dict[str, Any]:
    raw = files("agent_discord.data").joinpath("aws_catalog.json").read_text(
        encoding="utf-8"
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("aws_catalog.json must be an object")
    return payload


def analogs(catalog: Optional[Mapping[str, Any]] = None) -> tuple[Analog, ...]:
    payload = catalog if catalog is not None else load_catalog()
    rows: list[Analog] = []
    for item in payload.get("analogs") or ():
        if not isinstance(item, Mapping):
            continue
        rank = str(item.get("rank") or "")
        if rank not in RANKS:
            raise ValueError(f"analog rank {rank!r} is not in {sorted(RANKS)}")
        rows.append(
            Analog(
                aws=str(item.get("aws") or ""),
                discord=str(item.get("discord") or ""),
                module=str(item.get("module") or ""),
                rank=rank,
                note=str(item.get("note") or ""),
                source=str(item.get("source") or ""),
            )
        )
    return tuple(rows)


def lifts(catalog: Optional[Mapping[str, Any]] = None) -> tuple[Lift, ...]:
    payload = catalog if catalog is not None else load_catalog()
    rows: list[Lift] = []
    for item in payload.get("lifts") or ():
        if not isinstance(item, Mapping):
            continue
        rank = str(item.get("rank") or "")
        if rank not in RANKS:
            raise ValueError(f"lift rank {rank!r} is not in {sorted(RANKS)}")
        rows.append(
            Lift(
                id=str(item.get("id") or ""),
                title=str(item.get("title") or ""),
                rank=rank,
                adapt=str(item.get("adapt") or ""),
                source=str(item.get("source") or ""),
            )
        )
    return tuple(rows)


def lookup(query: str, *, catalog: Optional[Mapping[str, Any]] = None) -> tuple[Analog, ...]:
    needle = query.strip().lower()
    if not needle:
        return analogs(catalog)
    hits: list[Analog] = []
    for row in analogs(catalog):
        blob = f"{row.aws} {row.discord} {row.module}".lower()
        if needle in blob:
            hits.append(row)
    return tuple(hits)


def lookup_lifts(query: str, *, catalog: Optional[Mapping[str, Any]] = None) -> tuple[Lift, ...]:
    needle = query.strip().lower()
    if not needle:
        return lifts(catalog)
    hits: list[Lift] = []
    for row in lifts(catalog):
        blob = f"{row.id} {row.title} {row.adapt} {row.source}".lower()
        if needle in blob:
            hits.append(row)
    return tuple(hits)


def filter_rank(
    rank: str,
    *,
    catalog: Optional[Mapping[str, Any]] = None,
) -> tuple[Analog, ...]:
    wanted = rank.strip().lower()
    if wanted not in RANKS:
        raise ValueError(f"rank {rank!r} is not in {sorted(RANKS)}")
    return tuple(row for row in analogs(catalog) if row.rank == wanted)


def analog_payload(row: Analog) -> dict[str, str]:
    return {
        "aws": row.aws,
        "discord": row.discord,
        "module": row.module,
        "rank": row.rank,
        "note": row.note,
        "source": row.source,
    }


def lift_payload(row: Lift) -> dict[str, str]:
    return {
        "id": row.id,
        "title": row.title,
        "rank": row.rank,
        "adapt": row.adapt,
        "source": row.source,
    }


def format_analog(row: Analog) -> str:
    lines = [
        f"{row.aws} -> {row.discord}",
        f"rank: {row.rank}",
    ]
    if row.module:
        lines.append(f"module: {row.module}")
    if row.note:
        lines.append(row.note)
    return "\n".join(lines)


def format_table(rows: Sequence[Analog]) -> str:
    if not rows:
        return "no analogs matched"
    return "\n\n".join(format_analog(row) for row in rows)


def format_lift(row: Lift) -> str:
    lines = [
        f"{row.id}: {row.title}",
        f"rank: {row.rank}",
        row.adapt,
    ]
    if row.source:
        lines.append(row.source)
    return "\n".join(lines)


def format_lifts(rows: Sequence[Lift]) -> str:
    if not rows:
        return "no lifts matched"
    return "\n\n".join(format_lift(row) for row in rows)
