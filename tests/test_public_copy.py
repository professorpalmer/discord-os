from __future__ import annotations

import tomllib
from pathlib import Path

from agent_discord.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_description_names_the_computer() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    desc = data["project"]["description"]
    assert "harness UI for local agent work" not in desc
    lower = desc.lower()
    assert "screen" in lower
    assert "computer" in lower or "mac" in lower
    assert "sqlite" in lower
    assert "snowflake" in lower


def test_readme_leads_with_the_computer() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert text.startswith("# Discord OS\n\nDiscord is the screen.")
    assert "SQLite is the database" in text
    assert "harness UI for local agent work" not in text


def test_cli_help_names_the_computer() -> None:
    help_text = build_parser().format_help()
    compact = " ".join(help_text.split())
    assert "harness UI" not in compact
    assert "This process is the computer" in compact
    assert "SQLite lineage" in compact
