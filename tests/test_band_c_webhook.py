"""Band C — optional discord-webhook ops side-channel (mocked HTTP)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_discord import PRODUCT_NAME
from agent_discord.contracts import TaskIntake, TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.webhook import (
    WEBHOOK_USERNAME,

    ENV_WEBHOOK,
    ENV_WEBHOOK_URL,
    KIND_HALT,
    KIND_HOST_START,
    KIND_JOB_FAIL,
    KIND_RATE_LIMIT,
    clear_halt_alert,
    discord_webhook_available,
    emit_ops_alert,
    format_ops_alert,
    notify_halt,
    notify_host_start,
    notify_job_fail,
    notify_rate_limit,
    reset_webhook_for_tests,
    webhook_enabled,
    webhook_username,
    WEBHOOK_USERNAME,
    webhook_flag_on,
    webhook_urls,
)
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.orchestration.service import set_spend_halted
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


class _FakeExecute:
    def __init__(self, *, boom: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.boom = boom

    def __call__(self, url: str, content: str) -> dict[str, str]:
        if self.boom:
            raise RuntimeError("webhook HTTP 500")
        self.calls.append((url, content))
        return {"ok": "1"}


@pytest.fixture(autouse=True)
def _reset_webhook():
    reset_webhook_for_tests()
    yield
    reset_webhook_for_tests()


def test_webhook_off_when_flag_zero_or_empty_url():
    assert webhook_flag_on({}) is True
    assert webhook_enabled({}) is False
    assert webhook_enabled({ENV_WEBHOOK_URL: ""}) is False
    assert webhook_enabled({ENV_WEBHOOK: "0", ENV_WEBHOOK_URL: "https://example.test/hook"}) is False
    assert webhook_enabled({ENV_WEBHOOK: "off", ENV_WEBHOOK_URL: "https://example.test/hook"}) is False
    assert webhook_enabled({ENV_WEBHOOK_URL: "https://example.test/hook"}) is True
    assert webhook_enabled({ENV_WEBHOOK: "1", ENV_WEBHOOK_URL: "https://example.test/hook"}) is True


def test_webhook_urls_comma_and_alias():
    urls = webhook_urls(
        {
            ENV_WEBHOOK_URL: "https://a.test/1, https://b.test/2",
            "DISCORD_OS_WEBHOOK_URLS": "https://b.test/2,https://c.test/3",
        }
    )
    assert urls == (
        "https://a.test/1",
        "https://b.test/2",
        "https://c.test/3",
    )
    assert webhook_urls({}) == ()


def test_format_ops_alert_brand_and_kinds():
    start = format_ops_alert(KIND_HOST_START, version="0.5.86")
    assert start.startswith(f"{PRODUCT_NAME} 0.5.86 · host start")
    assert "tip / version kick" in start
    fail = format_ops_alert(KIND_JOB_FAIL, detail="DOS-1 · boom")
    assert "job fail" in fail
    assert "DOS-1 · boom" in fail
    halt = format_ops_alert(KIND_HALT)
    assert "halt" in halt.lower()
    assert "JobPool" in halt
    storm = format_ops_alert(KIND_RATE_LIMIT, detail="429 rate limited")
    assert "rate-limit" in storm
    assert "graham" not in start.lower()
    assert "graham" not in fail.lower()


def test_emit_uses_injected_execute_and_honors_disable():
    exe = _FakeExecute()
    env = {ENV_WEBHOOK_URL: "https://example.test/hook"}
    assert emit_ops_alert(KIND_JOB_FAIL, detail="boom", env=env, execute=exe) is True
    assert exe.calls[0][0] == "https://example.test/hook"
    assert "job fail" in exe.calls[0][1]
    exe.calls.clear()
    off = {ENV_WEBHOOK: "0", ENV_WEBHOOK_URL: "https://example.test/hook"}
    assert emit_ops_alert(KIND_JOB_FAIL, detail="boom", env=off, execute=exe) is False
    assert exe.calls == []


def test_emit_fail_soft_on_http_error():
    exe = _FakeExecute(boom=True)
    env = {ENV_WEBHOOK_URL: "https://example.test/hook"}
    assert emit_ops_alert(KIND_HALT, env=env, execute=exe) is False


def test_emit_fail_soft_missing_library(monkeypatch):
    monkeypatch.setattr(
        "agent_discord.host.webhook.discord_webhook_available",
        lambda: False,
    )
    env = {ENV_WEBHOOK_URL: "https://example.test/hook"}
    assert emit_ops_alert(KIND_HOST_START, env=env) is False


def test_notify_host_start_once():
    exe = _FakeExecute()
    env = {ENV_WEBHOOK_URL: "https://example.test/hook"}
    assert notify_host_start(channel_id="ch-1", env=env, execute=exe) is True
    assert notify_host_start(channel_id="ch-1", env=env, execute=exe) is False
    assert len(exe.calls) == 1
    assert "host start" in exe.calls[0][1]
    assert "channel=ch-1" in exe.calls[0][1]


def test_notify_job_fail_and_halt_once_until_clear():
    exe = _FakeExecute()
    env = {ENV_WEBHOOK_URL: "https://example.test/hook"}
    assert notify_job_fail(job_code="DOS-9", summary="forced failure", env=env, execute=exe)
    assert "DOS-9" in exe.calls[-1][1]
    assert notify_halt(env=env, execute=exe) is True
    assert notify_halt(env=env, execute=exe) is False
    assert sum(1 for _u, body in exe.calls if "halt" in body.lower()) == 1
    clear_halt_alert()
    assert notify_halt(env=env, execute=exe) is True


def test_notify_rate_limit_debounces_storm():
    exe = _FakeExecute()
    env = {ENV_WEBHOOK_URL: "https://example.test/hook"}
    assert notify_rate_limit(detail="429", env=env, execute=exe, now=10.0, window_s=60.0)
    assert notify_rate_limit(detail="429 again", env=env, execute=exe, now=20.0, window_s=60.0) is False
    assert notify_rate_limit(detail="later", env=env, execute=exe, now=80.0, window_s=60.0) is True
    assert len(exe.calls) == 2


def test_discord_webhook_available_is_bool():
    assert discord_webhook_available() in {True, False}


def _orch(tmp_path: Path, **kwargs: Any):
    store = SQLiteStore(tmp_path / "c.sqlite3")
    store.initialize()
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    backend = FakePuppetmasterBackend()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=facade,
        post_progress_to_discord=True,
        **kwargs,
    )
    return orch, store, fake, backend


def test_orchestrator_job_fail_calls_webhook(tmp_path: Path, monkeypatch):
    seen: list[dict[str, str]] = []

    def _capture(**kwargs: Any) -> bool:
        seen.append({k: str(v or "") for k, v in kwargs.items() if k != "env"})
        return True

    monkeypatch.setattr("agent_discord.host.webhook.notify_job_fail", _capture)
    orch, store, _fake, backend = _orch(tmp_path)
    backend.fail_next = True
    receipt = orch.run_task(
        TaskIntake(text="what is Discord OS?", channel_id="ch", workspace_id="ws")
    )
    assert receipt.status == TaskStatus.FAILED
    assert seen
    assert "forced failure" in (seen[0].get("error") or seen[0].get("summary") or "")
    store.close()


def test_orchestrator_rate_limit_calls_storm_hook(tmp_path: Path, monkeypatch):
    seen: list[str] = []

    def _storm(**kwargs: Any) -> bool:
        seen.append(str(kwargs.get("detail") or ""))
        return True

    monkeypatch.setattr("agent_discord.host.webhook.notify_rate_limit", _storm)
    orch, store, _fake, backend = _orch(tmp_path, retry_backoff_s=0.0)
    backend.rate_limit_next = True
    receipt = orch.run_task(
        TaskIntake(text="what is Discord OS?", channel_id="ch", workspace_id="ws")
    )
    assert receipt.status == TaskStatus.COMPLETED
    assert seen
    assert "429" in seen[0]
    store.close()


def test_orchestrator_webhook_error_does_not_block_job(tmp_path: Path, monkeypatch):
    def _boom(**_kwargs: Any) -> bool:
        raise RuntimeError("side-channel down")

    monkeypatch.setattr("agent_discord.host.webhook.notify_job_fail", _boom)
    orch, store, _fake, backend = _orch(tmp_path)
    backend.fail_next = True
    receipt = orch.run_task(
        TaskIntake(text="what is Discord OS?", channel_id="ch", workspace_id="ws")
    )
    assert receipt.status == TaskStatus.FAILED
    store.close()


def test_set_spend_halted_notifies_once(tmp_path: Path, monkeypatch):
    hits = {"n": 0}

    def _halt(**_kwargs: Any) -> bool:
        hits["n"] += 1
        return True

    monkeypatch.setattr("agent_discord.host.webhook.notify_halt", _halt)
    store = SQLiteStore(tmp_path / "h.sqlite3")
    store.initialize()
    set_spend_halted(store, True)
    set_spend_halted(store, True)
    assert hits["n"] == 1
    set_spend_halted(store, False)
    set_spend_halted(store, True)
    assert hits["n"] == 2
    store.close()


def test_host_start_hook_is_wired_and_fail_soft():
    from agent_discord import cli as cli_mod

    src = Path(cli_mod.__file__).read_text()
    assert "notify_host_start" in src
    exe = _FakeExecute(boom=True)
    env = {ENV_WEBHOOK_URL: "https://example.test/hook"}
    assert notify_host_start(channel_id="ch", env=env, execute=exe) is False


def test_package_version_is_084():
    text = Path("CHANGELOG.md").read_text()
    assert "## 0.5.86" in text
    assert "Band C" in text


def test_band_c_doc_records_flag_and_parks():
    text = (
        Path(__file__).resolve().parents[1] / "docs/co-work/band-c-webhook.md"
    ).read_text()
    lowered = text.lower()
    assert "discord_os_webhook=0" in lowered
    assert "empty" in lowered and "url" in lowered
    assert "fail soft" in lowered or "fail-soft" in lowered
    assert "side-channel" in lowered
    assert "jobpool" in lowered
    assert "jishaku" in lowered
    assert "graham" not in lowered or "never graham" in lowered
    assert "board + brain" in lowered


def test_webhook_username_has_no_discord_substring():
    assert "discord" not in WEBHOOK_USERNAME.lower()
    assert "discord" not in webhook_username().lower()
    assert webhook_username("Discord OS") == WEBHOOK_USERNAME
    assert webhook_username("DOS Ops") == "DOS Ops"
    assert webhook_username("Board Brain") == "Board Brain"
    assert webhook_username("My Discord Bot") == WEBHOOK_USERNAME


def test_default_execute_uses_safe_username(monkeypatch):
    captured: dict[str, object] = {}

    class _Hook:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def execute(self):
            return "ok"

    import agent_discord.host.webhook as wh

    monkeypatch.setattr(wh, "discord_webhook_available", lambda: True)

    def fake_import(name, *args, **kwargs):
        if name == "discord_webhook":
            import types
            mod = types.ModuleType("discord_webhook")
            mod.DiscordWebhook = _Hook
            return mod
        return __import__(name, *args, **kwargs)

    # Patch the import inside _default_execute by injecting module
    import sys
    import types
    mod = types.ModuleType("discord_webhook")
    mod.DiscordWebhook = _Hook
    monkeypatch.setitem(sys.modules, "discord_webhook", mod)
    wh._default_execute("https://example.invalid/hook", "hi")
    assert captured.get("username") == WEBHOOK_USERNAME
    assert "discord" not in str(captured.get("username")).lower()
