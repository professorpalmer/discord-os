"""G2-1: a gateway that never reached READY must read as FAIL / Need.

``snapshot_gateway_health`` already computes ready=False ok=False past the
never-READY grace. Doctor and liveness used to look at ``ready`` alone and
printed OK, and the ``doctor --notify`` process overwrote the host's health
file with its own never-READY-but-quiet snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_discord.discord.gateway_health import (
    DEFAULT_NEVER_READY_GRACE_S,
    GatewayHealth,
    gateway_health_path,
    gateway_is_expected,
    load_gateway_health,
    note_gateway_expected,
    note_ready,
    persist_gateway_health,
    reset_gateway_health_for_tests,
    snapshot_gateway_health,
)
from agent_discord.host.doctor import _check_gateway_ws
from agent_discord.host.liveness import (
    DOCTOR_FAIL,
    GATEWAY_BAD,
    GATEWAY_NA,
    compute_host_digest,
)


@pytest.fixture(autouse=True)
def _clean_health():
    reset_gateway_health_for_tests()
    yield
    reset_gateway_health_for_tests()


def _expect_a_gateway_that_never_came_up() -> None:
    """Mark a panel gateway expected long enough ago to be past grace."""

    import time

    note_gateway_expected(now=time.time() - (DEFAULT_NEVER_READY_GRACE_S + 10.0))


def test_snapshot_is_the_ground_truth(tmp_path: Path) -> None:
    _expect_a_gateway_that_never_came_up()
    health = snapshot_gateway_health()
    assert not health.ready
    assert not health.ok
    assert "never READY" in health.reason


def test_doctor_fails_on_a_gateway_that_never_reached_ready(tmp_path: Path) -> None:
    _expect_a_gateway_that_never_came_up()
    lines: list[str] = []
    assert _check_gateway_ws(tmp_path, lines) == 1
    assert any(line.startswith("FAIL gateway WS") for line in lines), lines
    assert any("never READY" in line for line in lines), lines


def test_doctor_stays_quiet_for_rest_only(tmp_path: Path) -> None:
    """No panel expected: REST-only is not a fault (low false positives)."""

    lines: list[str] = []
    assert _check_gateway_ws(tmp_path, lines) == 0
    assert lines == [
        "OK gateway WS not READY this process (REST intake OK; buttons need panel)"
    ]


def test_doctor_ok_once_ready(tmp_path: Path) -> None:
    _expect_a_gateway_that_never_came_up()
    note_ready()
    lines: list[str] = []
    assert _check_gateway_ws(tmp_path, lines) == 0
    assert any(line.startswith("OK gateway WS READY") for line in lines), lines


def test_liveness_digest_needs_a_gateway_that_never_reached_ready(
    tmp_path: Path,
) -> None:
    ws = tmp_path / ".agent-discord"
    ws.mkdir(parents=True)
    _expect_a_gateway_that_never_came_up()
    digest = compute_host_digest(
        workspace=ws,
        doctor_lines=["OK version 0.5.87"],
        doctor_code=0,
    )
    assert digest.gateway == GATEWAY_BAD
    assert digest.doctor == DOCTOR_FAIL
    assert not digest.ok
    assert "gateway" in digest.fail_summary


def test_liveness_rest_only_digest_stays_quiet(tmp_path: Path) -> None:
    ws = tmp_path / ".agent-discord"
    ws.mkdir(parents=True)
    digest = compute_host_digest(
        workspace=ws,
        doctor_lines=["OK version 0.5.87"],
        doctor_code=0,
    )
    assert digest.gateway == GATEWAY_NA
    assert digest.ok


def test_doctor_notify_process_does_not_overwrite_the_host_health_file(
    tmp_path: Path,
) -> None:
    """The separate --notify process never opens the socket. It must not write."""

    ws = tmp_path / ".agent-discord"
    ws.mkdir(parents=True)
    # What the host process wrote: expected, never READY, unhealthy.
    host_view = GatewayHealth(
        ready=False,
        connected=False,
        ack_age_s=None,
        ok=False,
        reason="gateway never READY",
        checked_at=1000.0,
    )
    _expect_a_gateway_that_never_came_up()
    persist_gateway_health(ws, host_view)
    before = gateway_health_path(ws).read_text(encoding="utf-8")

    # Now behave like the --notify process: fresh state, no gateway expected.
    reset_gateway_health_for_tests()
    assert not gateway_is_expected()
    assert snapshot_gateway_health().ok  # its own snapshot looks quiet

    digest = compute_host_digest(
        workspace=ws,
        doctor_lines=["OK version 0.5.87"],
        doctor_code=0,
    )
    after = gateway_health_path(ws).read_text(encoding="utf-8")
    assert json.loads(after) == json.loads(before)
    # And it reads the host's verdict instead of inventing a healthy one.
    assert load_gateway_health(ws) is not None
    assert not load_gateway_health(ws).ok
    assert digest.gateway == GATEWAY_BAD
    assert digest.doctor == DOCTOR_FAIL


def test_owning_process_still_persists(tmp_path: Path) -> None:
    ws = tmp_path / ".agent-discord"
    ws.mkdir(parents=True)
    _expect_a_gateway_that_never_came_up()
    assert gateway_is_expected()
    compute_host_digest(
        workspace=ws,
        doctor_lines=["OK version 0.5.87"],
        doctor_code=0,
    )
    written = load_gateway_health(ws)
    assert written is not None
    assert not written.ok
