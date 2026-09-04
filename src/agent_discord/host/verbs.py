"""Poverty-path host verbs: ``/open`` and ``!open`` in channel text."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from agent_discord.host.actions import (
    DEST_HOST,
    DEST_REMOTE,
    CommandRunner,
    HostActionError,
    HostActionResult,
    OpenIntent,
    default_dest,
    run_open_intent,
)


OPEN_PREFIXES = frozenset({"/open", "!open"})


_DEST_WORDS = {"here": DEST_REMOTE, "remote": DEST_REMOTE, "host": DEST_HOST}


@dataclass(frozen=True)
class ParsedOpen:
    surface: str
    target: str
    raw_command: str
    dest: str = DEST_HOST


@dataclass(frozen=True)
class OpenPublicResult:
    surface: str
    target: str
    card: str
    error: str = ""
    opened: bool = False
    dest: str = DEST_HOST
    link_url: str = ""


def is_open_command(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    first = stripped.split(None, 1)[0].lower()
    return first in OPEN_PREFIXES


def parse_open_command(text: str) -> ParsedOpen:
    stripped = (text or "").strip()
    parts = stripped.split()
    if not parts:
        return ParsedOpen(surface="files", target=".", raw_command=stripped)
    rest = parts[1:]
    dest = ""
    if rest and rest[0].lower() in _DEST_WORDS:
        dest = _DEST_WORDS[rest[0].lower()]
        rest = rest[1:]
    if not rest:
        return ParsedOpen(
            surface="files",
            target=".",
            raw_command=stripped,
            dest=dest or DEST_HOST,
        )
    head = rest[0].lower()
    if head in {"terminal", "term", "shell"}:
        target = rest[1] if len(rest) > 1 else "."
        surface = "terminal"
    elif head in {"files", "finder", "explorer", "folder"}:
        target = rest[1] if len(rest) > 1 else "."
        surface = "files"
    elif head in {"browser", "url"}:
        target = rest[1] if len(rest) > 1 else ""
        surface = "browser"
    elif head.startswith("http://") or head.startswith("https://"):
        surface = "browser"
        target = rest[0]
    else:
        surface = "files"
        target = rest[0]
    return ParsedOpen(
        surface=surface,
        target=target,
        raw_command=stripped,
        dest=dest or default_dest(surface, target),
    )


def handle_open_message(
    text: str,
    *,
    roots: Sequence[Path],
    runner: Optional[CommandRunner] = None,
    browser_open: Optional[Callable[[str], object]] = None,
) -> OpenPublicResult:
    from agent_discord.orchestration.cards import render_open_card

    parsed = parse_open_command(text)
    try:
        result = run_open_intent(
            OpenIntent(
                surface=parsed.surface,
                target=parsed.target,
                dest=parsed.dest,
            ),
            roots=roots,
            runner=runner,
            browser_open=browser_open,
        )
    except HostActionError as exc:
        card = render_open_card(
            surface=parsed.surface,
            target=parsed.target,
            dest=parsed.dest,
            error=str(exc),
        )
        return OpenPublicResult(
            surface=parsed.surface,
            target=parsed.target,
            card=card,
            error=str(exc),
            dest=parsed.dest,
            opened=False,
        )
    card = render_open_card(
        surface=result.surface,
        target=_public_target(result),
        dest=result.dest,
        link_url=result.link_url,
    )
    return OpenPublicResult(
        surface=result.surface,
        target=result.target,
        card=card,
        dest=result.dest,
        link_url=result.link_url,
        opened=result.opened,
    )


def _public_target(result: HostActionResult) -> str:
    if result.surface == "browser":
        return result.target
    return result.target
