"""Gateway WS ACK liveness."""

from __future__ import annotations

from pathlib import Path

from agent_discord.discord.gateway_health import (
    gateway_need_fragment,
    load_gateway_health,
    note_closed,
    note_gateway_expected,
    note_heartbeat_ack,
    note_ready,
    persist_gateway_health,
    reset_gateway_health_for_tests,
    snapshot_gateway_health,
)
from agent_discord.host.liveness import GATEWAY_BAD, HostDigest, host_need_line


def setup_function() -> None:
    reset_gateway_health_for_tests()


def test_cold_start_not_ready_is_ok_low_fp() -> None:
    health = snapshot_gateway_health()
    assert health.ready is False
    assert health.ok is True
    assert gateway_need_fragment(health) is None


def test_ready_then_stale_ack_fails() -> None:
    note_ready(now=1000.0)
    note_heartbeat_ack(now=1000.0)
    health = snapshot_gateway_health(now=1000.0 + 300.0, ack_stale_s=120.0)
    assert health.ready is True
    assert health.ok is False
    assert health.ack_age_s is not None and health.ack_age_s >= 299
    frag = gateway_need_fragment(health)
    assert frag is not None
    assert "gateway" in frag


def test_ready_fresh_ack_ok() -> None:
    note_ready(now=1000.0)
    note_heartbeat_ack(now=1050.0)
    health = snapshot_gateway_health(now=1060.0, ack_stale_s=120.0)
    assert health.ok is True


def test_socket_closed_after_ready_fails() -> None:
    note_ready(now=1000.0)
    note_heartbeat_ack(now=1000.0)
    note_closed("boom", now=1010.0)
    health = snapshot_gateway_health(now=1015.0)
    assert health.ok is False
    assert "closed" in health.reason or not health.connected


def test_persist_and_need_line(tmp_path: Path) -> None:
    note_ready(now=1.0)
    note_heartbeat_ack(now=1.0)
    note_closed("gone", now=2.0)
    health = snapshot_gateway_health(now=3.0)
    persist_gateway_health(tmp_path, health)
    loaded = load_gateway_health(tmp_path)
    assert loaded is not None
    assert loaded.ok is False
    digest = HostDigest(
        power="OK",
        pid="OK",
        doctor="FAIL",
        fail_summary="gateway WS unhealthy",
        gateway=GATEWAY_BAD,
    )
    line = host_need_line(digest)
    assert line is not None
    assert "gateway BAD" in line


def test_never_ready_after_expected_is_need() -> None:
    """Gateway quiet forever after panel start → spoken Need (not cold-start quiet)."""

    note_gateway_expected(now=1000.0)
    still_grace = snapshot_gateway_health(now=1050.0, never_ready_grace_s=90.0)
    assert still_grace.ready is False
    assert still_grace.ok is True
    late = snapshot_gateway_health(now=1000.0 + 120.0, never_ready_grace_s=90.0)
    assert late.ready is False
    assert late.ok is False
    assert "never READY" in late.reason
    frag = gateway_need_fragment(late)
    assert frag is not None
    assert "gateway" in frag


def test_cold_start_without_expected_stays_quiet() -> None:
    health = snapshot_gateway_health(now=10_000.0, never_ready_grace_s=1.0)
    assert health.ok is True
    assert gateway_need_fragment(health) is None
