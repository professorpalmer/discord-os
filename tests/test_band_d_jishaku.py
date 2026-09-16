"""Band D — optional jishaku tip-debug gate (mocked load; no live Discord)."""

from __future__ import annotations

from pathlib import Path

from agent_discord import __version__
from agent_discord.contracts import DiscordMessage
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.jishaku import (
    ENV_JISHAKU,
    STATUS_BLOCKED,
    STATUS_DENIED,
    STATUS_LOADED,
    STATUS_MISSING,
    STATUS_OFF,
    absorb_jishaku_command,
    format_jishaku_line,
    is_jishaku_command,
    jishaku_available,
    jishaku_enabled,
    jishaku_flag_on,
    jishaku_may_invoke,
    jishaku_may_load,
    maybe_load_jishaku,
)
from agent_discord.orchestration.listen import drain_inbound
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def _store(tmp_path: Path) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "jsk.sqlite3")
    store.initialize()
    return store


def _orch(tmp_path: Path):
    store = _store(tmp_path)
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    backend = FakePuppetmasterBackend()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=facade,
        post_progress_to_discord=True,
    )
    return orch, store, fake, backend


def test_jishaku_default_off(tmp_path: Path):
    store = _store(tmp_path)
    store.add_operator("cary", role="owner")
    assert jishaku_flag_on({}) is False
    assert jishaku_flag_on({ENV_JISHAKU: ""}) is False
    assert jishaku_flag_on({ENV_JISHAKU: "0"}) is False
    assert jishaku_flag_on({ENV_JISHAKU: "off"}) is False
    assert jishaku_flag_on({ENV_JISHAKU: "false"}) is False
    assert jishaku_enabled({}, store) is False
    result = maybe_load_jishaku(env={}, store=store)
    assert result.status == STATUS_OFF
    assert result.loaded is False
    store.close()


def test_flag_alone_insufficient_without_owner(tmp_path: Path):
    store = _store(tmp_path)
    env = {ENV_JISHAKU: "1"}
    assert jishaku_flag_on(env) is True
    assert jishaku_may_load(env, store) is False
    result = maybe_load_jishaku(env=env, store=store)
    assert result.status == STATUS_BLOCKED
    assert result.loaded is False
    assert result.reason == "owner"
    assert "operator" in format_jishaku_line(result).lower()
    store.close()


def test_shared_require_operators_demo_stays_off(tmp_path: Path):
    store = _store(tmp_path)
    store.add_operator("cary", role="owner")
    env = {"DISCORD_OS_REQUIRE_OPERATORS": "1"}
    assert jishaku_may_load(env, store) is False
    assert maybe_load_jishaku(env=env, store=store).status == STATUS_OFF
    store.close()


def test_non_operator_denied_even_with_flag(tmp_path: Path):
    store = _store(tmp_path)
    store.add_operator("cary", role="owner")
    env = {ENV_JISHAKU: "1"}
    assert jishaku_may_invoke(env, store, "stranger") is False
    result = maybe_load_jishaku(env=env, store=store, user_id="stranger")
    assert result.status == STATUS_DENIED
    assert result.loaded is False
    store.close()


def test_owner_or_allowlisted_operator_may_invoke(tmp_path: Path):
    store = _store(tmp_path)
    store.add_operator("cary", role="owner")
    store.add_operator("op-1", role="operator")
    env = {ENV_JISHAKU: "1"}
    assert jishaku_may_invoke(env, store, "cary") is True
    assert jishaku_may_invoke(env, store, "op-1") is True
    assert jishaku_enabled(env, store, "cary") is True
    store.close()


def test_optional_load_path_mocked(tmp_path: Path):
    store = _store(tmp_path)
    store.add_operator("cary", role="owner")
    called: dict[str, bool] = {}

    def loader() -> dict[str, str]:
        called["ok"] = True
        return {"session": "mock"}

    result = maybe_load_jishaku(
        env={ENV_JISHAKU: "1"},
        store=store,
        user_id="cary",
        loader=loader,
    )
    assert called.get("ok") is True
    assert result.status == STATUS_LOADED
    assert result.loaded is True
    store.close()


def test_mocked_load_does_not_run_without_gates(tmp_path: Path):
    store = _store(tmp_path)
    called = {"n": 0}

    def loader() -> None:
        called["n"] += 1

    blocked = maybe_load_jishaku(
        env={ENV_JISHAKU: "1"}, store=store, loader=loader
    )
    off = maybe_load_jishaku(env={}, store=store, loader=loader)
    assert blocked.status == STATUS_BLOCKED
    assert off.status == STATUS_OFF
    assert called["n"] == 0
    store.close()


def test_missing_extra_when_gates_pass(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    store.add_operator("cary", role="owner")
    monkeypatch.setattr(
        "agent_discord.host.jishaku.jishaku_available",
        lambda: False,
    )
    result = maybe_load_jishaku(env={ENV_JISHAKU: "1"}, store=store, user_id="cary")
    assert result.status == STATUS_MISSING
    assert result.loaded is False
    store.close()


def test_jishaku_available_is_bool():
    assert jishaku_available() in {True, False}


def test_is_jishaku_command():
    assert is_jishaku_command("jsk") is True
    assert is_jishaku_command("jishaku py") is True
    assert is_jishaku_command("JSK cat") is True
    assert is_jishaku_command("please jsk") is False
    assert is_jishaku_command("jskfoo") is False
    assert is_jishaku_command("hello") is False


def test_listen_flag_off_does_not_intercept_jsk(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    store.set_host_control("ch", armed=True)
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="jsk py",
            message_id="20",
            author_id="human-1",
        )
    )
    receipts = drain_inbound(
        orch, orch.discord, channel_id="ch", workspace_id="ws", since_ms=0, env={}
    )
    assert len(receipts) == 1
    assert backend.dispatch_count == 1
    store.close()


def test_listen_flag_on_without_owner_denies_no_cook(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    store.set_host_control("ch", armed=True)
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="jsk py",
            message_id="21",
            author_id="human-1",
        )
    )
    receipts = drain_inbound(
        orch,
        orch.discord,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        env={ENV_JISHAKU: "1"},
    )
    assert receipts == []
    assert backend.dispatch_count == 0
    assert any("Denied" in (msg.content or "") for msg in fake.sent)
    store.close()


def test_listen_owner_gets_parked_line_not_cook(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    store.add_operator("cary", role="owner")
    store.set_host_control("ch", armed=True)
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="jishaku",
            message_id="22",
            author_id="cary",
        )
    )
    receipts = drain_inbound(
        orch,
        orch.discord,
        channel_id="ch",
        workspace_id="ws",
        since_ms=0,
        env={ENV_JISHAKU: "1"},
    )
    assert receipts == []
    assert backend.dispatch_count == 0
    spoken = " ".join(msg.content or "" for msg in fake.sent).lower()
    assert "tip-debug" in spoken
    assert "parked" in spoken
    store.close()


def test_absorb_uses_mocked_loader(tmp_path: Path):
    store = _store(tmp_path)
    store.add_operator("cary", role="owner")
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    called = {"n": 0}

    def loader() -> None:
        called["n"] += 1

    result = absorb_jishaku_command(
        DiscordMessage(channel_id="ch", content="jsk", message_id="1", author_id="cary"),
        discord=facade,
        store=store,
        channel_id="ch",
        env={ENV_JISHAKU: "1"},
        loader=loader,
    )
    assert called["n"] == 1
    assert result.loaded is True
    assert any("tip-debug" in (msg.content or "") for msg in fake.sent)
    store.close()


def test_package_version_is_085():
    assert __version__ == "0.5.85"
    text = Path("pyproject.toml").read_text()
    assert 'version = "0.5.85"' in text
    assert 'debug = ["jishaku>=2.5"]' in text


def test_cli_wires_maybe_load():
    from agent_discord import cli as cli_mod

    src = Path(cli_mod.__file__).read_text()
    assert "maybe_load_jishaku" in src


def test_band_d_doc_records_flag_owner_and_parks():
    text = (
        Path(__file__).resolve().parents[1] / "docs/co-work/band-d-jishaku.md"
    ).read_text()
    lowered = text.lower()
    assert "discord_os_jishaku=1" in lowered
    assert "default" in lowered and "off" in lowered
    assert "owner" in lowered
    assert "tip" in lowered and "debug" in lowered
    assert "not a product feature" in lowered
    assert "loop" in lowered and "closed" in lowered
    assert "wave 7 p1" in lowered
    assert "graham" not in lowered or "never graham" in lowered
    assert "board + brain" in lowered
