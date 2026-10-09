"""Suite-wide defaults."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_os_sandbox(monkeypatch):
    # Tests read the worker argv. Sandbox tests turn it back on explicitly.
    monkeypatch.setenv("DISCORD_OS_SANDBOX", "0")
