"""Audit 2026-10-02 F2: a shared platform lock cannot disable Discord OS cooks.

Marionette disabling adapters in the shared ``~/.puppetmaster/platform.json``
failed two production cooks with ``adapter(s) agentic are disabled``.
Puppetmaster honors ``PUPPETMASTER_ONLY_ADAPTERS`` ahead of that file.
"""

from __future__ import annotations

from pathlib import Path

from agent_discord.puppetmaster.backend import PM_ONLY_ADAPTERS_ENV, worker_env


def _host(tmp_path: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin",
        "HOME": str(tmp_path / "home"),
        "AGENT_DISCORD_WORKSPACE": str(tmp_path / ".agent-discord"),
    }


def test_worker_env_forces_the_agentic_allowlist(tmp_path: Path) -> None:
    assert worker_env(_host(tmp_path))[PM_ONLY_ADAPTERS_ENV] == "agentic"


def test_host_set_allowlist_cannot_widen_it(tmp_path: Path) -> None:
    host = _host(tmp_path)
    host[PM_ONLY_ADAPTERS_ENV] = "cursor,agentic"
    assert worker_env(host)[PM_ONLY_ADAPTERS_ENV] == "agentic"


def test_worker_env_leaves_the_shared_registry_alone(tmp_path: Path) -> None:
    env = worker_env(_host(tmp_path))
    assert "PUPPETMASTER_MODELS_PATH" not in env
