"""HOST Update-available pill — PyPI vs installed (fail soft, no auto-upgrade)."""

from __future__ import annotations

import io
import json

from agent_discord.host.update_check import (
    UpdateCheckResult,
    check_update_available,
    update_available_pill,
    version_less,
)
from agent_discord.orchestration.cards import host_card


def test_version_less_numeric() -> None:
    assert version_less("0.5.53", "0.5.54")
    assert not version_less("0.5.54", "0.5.53")
    assert not version_less("0.5.54", "0.5.54")
    assert not version_less("", "1.0.0")


def test_check_update_available_with_explicit_latest() -> None:
    result = check_update_available(
        installed="0.5.53", latest="0.5.99", fetch=False
    )
    assert result.update_available is True
    assert result.pill.startswith("Update available")
    assert "0.5.99" in result.pill


def test_check_update_available_current_is_quiet() -> None:
    result = check_update_available(
        installed="0.5.99", latest="0.5.99", fetch=False
    )
    assert result.update_available is False
    assert result.pill == ""


def test_fetch_pypi_fail_soft(monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise TimeoutError("nope")

    result = check_update_available(
        installed="0.5.53",
        fetch=True,
        opener=_boom,
        force=True,
    )
    assert result.update_available is False
    assert result.checked is False
    assert "unreachable" in result.error


def test_fetch_pypi_parses_json() -> None:
    payload = json.dumps({"info": {"version": "9.9.9"}}).encode()

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _open(req, timeout=0):
        return _Resp(payload)

    result = check_update_available(
        installed="0.5.53", fetch=True, opener=_open, force=True
    )
    assert result.latest == "9.9.9"
    assert result.update_available is True


def test_host_card_shows_update_pill() -> None:
    card = host_card(
        armed=True,
        last_job="Need: something",
        update_pill="Update available · 0.5.99",
    )
    assert "Update available · 0.5.99" in card.description
    assert "Need: something" in card.description


def test_update_check_env_disable(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_OS_UPDATE_CHECK", "0")
    result = check_update_available(installed="0.5.0", latest="9.0.0", fetch=False)
    # latest explicit still works? disabled should skip entirely
    assert result.checked is False
    assert result.pill == ""
