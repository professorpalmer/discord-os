"""Audit 2026-10-02 F4: one PM resolver, and the resolved version is reported.

`dependencies = []` plus a resolver that prefers the venv sibling let production
cook on a stale 1.22.15 with nothing saying so.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from agent_discord.config import (
    PUPPETMASTER_REQUIREMENT,
    parse_puppetmaster_version,
    puppetmaster_cli_found,
    puppetmaster_cli_version,
    puppetmaster_version_in_range,
    resolve_puppetmaster_cli,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_cli(tmp_path: Path, version: str) -> str:
    path = tmp_path / "puppetmaster"
    path.write_text(
        "#!/bin/sh\n" f'echo "puppetmaster {version}"\n', encoding="utf-8"
    )
    path.chmod(0o755)
    return str(path)


def test_pyproject_declares_the_puppetmaster_dependency() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert PUPPETMASTER_REQUIREMENT in deps, deps


@pytest.mark.parametrize(
    "text,expected",
    [
        ("puppetmaster 1.27.39", (1, 27, 39)),
        ("1.22.15", (1, 22, 15)),
        ("puppetmaster-ai version 2.0.0 (build 7)", (2, 0, 0)),
        ("", ()),
        ("no digits here", ()),
    ],
)
def test_parse_puppetmaster_version(text: str, expected: tuple[int, ...]) -> None:
    assert parse_puppetmaster_version(text) == expected


@pytest.mark.parametrize(
    "version,ok",
    [
        ("1.27.24", True),
        ("1.27.39", True),
        ("1.99.0", True),
        ("1.22.15", False),
        ("1.27.23", False),
        ("2.0.0", False),
        ("", True),
    ],
)
def test_puppetmaster_version_in_range(version: str, ok: bool) -> None:
    assert puppetmaster_version_in_range(version) is ok


def test_cli_version_reads_the_resolved_executable(tmp_path: Path) -> None:
    cli = _fake_cli(tmp_path, "1.27.39")
    assert puppetmaster_cli_version(cli, refresh=True) == "1.27.39"
    assert puppetmaster_cli_found(cli) is True


def test_cli_found_is_false_for_a_missing_absolute_path(tmp_path: Path) -> None:
    assert puppetmaster_cli_found(str(tmp_path / "nope")) is False


def test_resolver_returns_the_configured_name_when_nothing_is_installed(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("agent_discord.config.shutil.which", lambda _: None)
    monkeypatch.setattr(
        "agent_discord.config.sys.executable", str(tmp_path / "bin" / "python")
    )
    assert resolve_puppetmaster_cli("puppetmaster") == "puppetmaster"


def test_usage_metadata_records_the_resolved_pm_version(monkeypatch, tmp_path: Path) -> None:
    from agent_discord.puppetmaster.backend import usage_from_cli_meta
    from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN

    cli = _fake_cli(tmp_path, "1.27.39")
    monkeypatch.setattr(
        "agent_discord.config.puppetmaster_cli_version",
        lambda target, **kw: "1.27.39" if target == cli else "",
    )
    usage = usage_from_cli_meta(AGENTIC_MODEL_PIN, cli, {"job_id": "j1"})
    assert usage.metadata["pm_version"] == "1.27.39"


def test_doctor_warns_when_the_resolved_cli_is_below_the_floor(
    monkeypatch, tmp_path: Path
) -> None:
    from agent_discord.host import doctor as doctor_mod

    cli = _fake_cli(tmp_path, "1.22.15")
    monkeypatch.setattr("agent_discord.config.resolve_puppetmaster_cli", lambda _=None: cli)
    monkeypatch.setattr("agent_discord.config.puppetmaster_cli_found", lambda _=None: True)
    monkeypatch.setattr(
        "agent_discord.config.puppetmaster_cli_version", lambda *a, **kw: "1.22.15"
    )

    class _Cfg:
        puppetmaster_cli = "puppetmaster"

    lines: list[str] = []
    doctor_mod._check_puppetmaster_cli(_Cfg(), lines)
    assert len(lines) == 1
    assert lines[0].startswith("WARN puppetmaster 1.22.15")
    assert PUPPETMASTER_REQUIREMENT in lines[0]


def test_doctor_is_ok_inside_the_declared_range(monkeypatch, tmp_path: Path) -> None:
    from agent_discord.host import doctor as doctor_mod

    cli = _fake_cli(tmp_path, "1.27.39")
    monkeypatch.setattr("agent_discord.config.resolve_puppetmaster_cli", lambda _=None: cli)
    monkeypatch.setattr("agent_discord.config.puppetmaster_cli_found", lambda _=None: True)
    monkeypatch.setattr(
        "agent_discord.config.puppetmaster_cli_version", lambda *a, **kw: "1.27.39"
    )

    class _Cfg:
        puppetmaster_cli = "puppetmaster"

    lines: list[str] = []
    doctor_mod._check_puppetmaster_cli(_Cfg(), lines)
    assert lines == [f"OK puppetmaster 1.27.39 at {cli}"]


def test_doctor_warns_when_the_cli_is_missing(monkeypatch) -> None:
    from agent_discord.host import doctor as doctor_mod

    monkeypatch.setattr(
        "agent_discord.config.resolve_puppetmaster_cli", lambda _=None: "puppetmaster"
    )
    monkeypatch.setattr("agent_discord.config.puppetmaster_cli_found", lambda _=None: False)

    class _Cfg:
        puppetmaster_cli = "puppetmaster"

    lines: list[str] = []
    doctor_mod._check_puppetmaster_cli(_Cfg(), lines)
    assert lines == [
        f"WARN puppetmaster CLI not found: puppetmaster (install {PUPPETMASTER_REQUIREMENT})"
    ]
