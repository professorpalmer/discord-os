"""Band B — Mac Rich Presence via optional pypresence (no Discord desktop)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_discord.contracts import TaskStatus
from agent_discord.host.presence import (
    IDLE_DETAILS,
    STATE_HALT,
    STATE_OFF,
    STATE_ON,
    RichPresence,
    cheap_job_title,
    close_rich_presence,
    host_power_state,
    job_details,
    presence_enabled,
    presence_payload,
    pypresence_available,
    reset_rich_presence_for_tests,
    resolve_application_id,
    snapshot_presence,
    tick_rich_presence,
)
from agent_discord.orchestration.service import set_spend_halted
from agent_discord.persistence.sqlite import SQLiteStore


class _FakeRPC:
    def __init__(self, *, fail_connect: bool = False, fail_update: bool = False) -> None:
        self.connected = False
        self.closed = False
        self.updates: list[dict[str, Any]] = []
        self.fail_connect = fail_connect
        self.fail_update = fail_update

    def connect(self) -> None:
        if self.fail_connect:
            raise OSError("Discord IPC pipe missing")
        self.connected = True

    def update(self, **kwargs: Any) -> None:
        if self.fail_update:
            raise ConnectionError("IPC closed")
        self.updates.append(dict(kwargs))

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_presence():
    reset_rich_presence_for_tests()
    yield
    reset_rich_presence_for_tests()


def test_presence_flag_default_on(monkeypatch):
    monkeypatch.delenv("DISCORD_OS_PRESENCE", raising=False)
    assert presence_enabled() is True
    monkeypatch.setenv("DISCORD_OS_PRESENCE", "0")
    assert presence_enabled() is False
    monkeypatch.setenv("DISCORD_OS_PRESENCE", "off")
    assert presence_enabled() is False
    monkeypatch.setenv("DISCORD_OS_PRESENCE", "1")
    assert presence_enabled() is True


def test_presence_flag_respects_env_mapping():
    assert presence_enabled({"DISCORD_OS_PRESENCE": "0"}) is False
    assert presence_enabled({"DISCORD_OS_PRESENCE": ""}) is True
    assert presence_enabled({}) is True


def test_payload_mapping_idle_on_off_halt():
    idle_on = presence_payload(details="", state=host_power_state(armed=True, halted=False))
    assert idle_on == {"details": IDLE_DETAILS, "state": STATE_ON}
    idle_off = presence_payload(details="   ", state=host_power_state(armed=False, halted=False))
    assert idle_off == {"details": IDLE_DETAILS, "state": STATE_OFF}
    halted = presence_payload(
        details="ship Band B",
        state=host_power_state(armed=True, halted=True),
    )
    assert halted["details"] == "ship Band B"
    assert halted["state"] == STATE_HALT


def test_job_details_clips_and_collapses_ws():
    assert job_details("  fix   the  card  ") == "fix the card"
    long = "x" * 200
    assert len(job_details(long)) == 128


def test_cheap_job_title_prefers_live_over_need(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t-need",
        workspace_id="default",
        channel_id="ch",
        intake_text="failed earlier",
    )
    store.create_run(
        run_id="r-need",
        task_id="t-need",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.FAILED,
    )
    store.create_task(
        task_id="t-live",
        workspace_id="default",
        channel_id="ch",
        intake_text="ship Band B presence",
    )
    store.create_run(
        run_id="r-live",
        task_id="t-live",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.RUNNING,
    )
    title = cheap_job_title(store, "ch")
    assert "ship Band B presence" in title
    assert "DOS-" in title
    assert "failed earlier" not in title
    store.close()


def test_cheap_job_title_idle_when_no_live(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t-done",
        workspace_id="default",
        channel_id="ch",
        intake_text="already done",
    )
    store.create_run(
        run_id="r-done",
        task_id="t-done",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.COMPLETED,
    )
    assert cheap_job_title(store, "ch") == ""
    store.close()


def test_snapshot_presence_halt_and_job(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True)
    store.create_task(
        task_id="t1",
        workspace_id="default",
        channel_id="ch",
        intake_text="cook the haul",
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.PROGRESS,
    )
    set_spend_halted(store, True)
    snap = snapshot_presence(store, channel_id="ch")
    assert snap["state"] == STATE_HALT
    assert "cook the haul" in snap["details"]
    store.close()


def test_soft_fail_missing_pypresence(monkeypatch):
    session = RichPresence(application_id="123", retry_s=0.0)
    monkeypatch.setattr(
        "agent_discord.host.presence.pypresence_available",
        lambda: False,
    )
    assert session.tick({"details": "idle", "state": "On"}) is False


def test_soft_fail_missing_application_id(monkeypatch):
    monkeypatch.delenv("DISCORD_APPLICATION_ID", raising=False)
    session = RichPresence(application_id="", env={})
    assert resolve_application_id({}) == ""
    assert session.tick({"details": "idle", "state": "On"}) is False


def test_soft_fail_ipc_missing_does_not_raise():
    rpc = _FakeRPC(fail_connect=True)
    session = RichPresence(client=rpc, application_id="99", retry_s=30.0)
    assert session.tick({"details": "idle", "state": "On"}) is False
    assert session.tick({"details": "idle", "state": "On"}) is False
    session.close()
    assert rpc.closed is True


def test_soft_fail_ipc_update_then_retry():
    rpc = _FakeRPC(fail_update=True)
    session = RichPresence(client=rpc, application_id="99", retry_s=0.0)
    assert session.tick({"details": "idle", "state": "Off"}) is False
    rpc.fail_update = False
    assert session.tick({"details": "idle", "state": "Off"}) is True
    assert rpc.updates[-1] == {"details": "idle", "state": "Off"}


def test_tick_uses_injected_client_and_dedupes():
    rpc = _FakeRPC()
    session = RichPresence(client=rpc, application_id="99")
    assert session.tick({"details": "DOS-1 · haul", "state": "On"}) is True
    assert session.tick({"details": "DOS-1 · haul", "state": "On"}) is True
    assert len(rpc.updates) == 1
    assert rpc.updates[0] == {"details": "DOS-1 · haul", "state": "On"}
    assert session.tick({"details": "idle", "state": "Off"}) is True
    assert rpc.updates[-1] == {"details": "idle", "state": "Off"}


def test_tick_rich_presence_honors_disable(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DISCORD_OS_PRESENCE", "0")
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.initialize()
    rpc = _FakeRPC()
    assert tick_rich_presence(store, channel_id="ch", client=rpc) is False
    assert rpc.updates == []
    store.close()


def test_tick_rich_presence_process_session(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=False)
    rpc = _FakeRPC()
    assert tick_rich_presence(store, channel_id="ch", client=rpc) is True
    assert rpc.updates[-1]["state"] == STATE_OFF
    assert rpc.updates[-1]["details"] == IDLE_DETAILS
    close_rich_presence()
    assert rpc.closed is True
    store.close()


def test_listen_tick_swallows_errors():
    from agent_discord.orchestration.listen import _tick_rich_presence_best_effort

    class _Boom:
        def host_is_armed(self, *_a, **_k):
            raise RuntimeError("store down")

        def list_recent_jobs(self, *_a, **_k):
            raise RuntimeError("store down")

    _tick_rich_presence_best_effort(_Boom(), channel_id="ch")


def test_pypresence_available_is_bool():
    assert pypresence_available() in {True, False}


def test_band_b_doc_records_flag_and_parks():
    text = (
        Path(__file__).resolve().parents[1] / "docs/co-work/band-b-pypresence.md"
    ).read_text()
    lowered = text.lower()
    assert "discord_os_presence=0" in lowered
    assert "pypresence" in lowered
    assert "fail soft" in lowered or "fail-soft" in lowered
    assert "graham" not in lowered or "never graham" in lowered
    assert "webhook" not in lowered or "band c" in lowered


def test_tick_resolves_application_id_from_config(monkeypatch, tmp_path):
    """LaunchAgent may omit DISCORD_APPLICATION_ID in process env; .env/config must win."""

    from agent_discord.host import presence as rp

    monkeypatch.delenv("DISCORD_APPLICATION_ID", raising=False)
    monkeypatch.setenv("DISCORD_OS_PRESENCE", "1")
    rp.reset_rich_presence_for_tests()

    class _Cfg:
        discord_application_id = "123456789012345678"

    class _Store:
        def host_is_armed(self, channel_id: str) -> bool:
            return True

        def list_recent_jobs(self, channel_id: str, limit: int = 8):
            return []

    seen: dict[str, str] = {}

    class _Client:
        def __init__(self, app_id: str) -> None:
            seen["app_id"] = str(app_id)

        def connect(self) -> None:
            return None

        def update(self, **kwargs) -> None:
            seen["update"] = "1"

    def _load():
        return _Cfg()

    def _apply(cfg):
        return cfg

    monkeypatch.setattr("agent_discord.config.load_config", _load)
    monkeypatch.setattr("agent_discord.config.apply_runtime_secrets", _apply)

    # Force Presence() path to use our client factory via injecting after resolve
    real_ensure = rp.RichPresence._ensure_client

    def _ensure(self) -> bool:
        app_id = self._application_id or rp.resolve_application_id(self._env)
        if not app_id:
            # mimic production: resolve via config inside tick already set _application_id
            return False
        self._client = _Client(app_id)
        return True

    monkeypatch.setattr(rp.RichPresence, "_ensure_client", _ensure)
    ok = rp.tick_rich_presence(_Store(), channel_id="ch", armed=True)
    assert ok is True
    assert seen.get("app_id") == "123456789012345678"
