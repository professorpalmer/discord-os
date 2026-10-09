"""Operator checks on every Discord surface that changes host state.

Once an owner is paired, only operators may press job-card or ask-gate
buttons, submit the HOST Ask modal, connect a provider key, turn the host
On/Off by text, or run state-changing slash commands. With no operators and
DISCORD_OS_REQUIRE_OPERATORS unset, the desk default (HARD lock 8) still lets
the first human through.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_discord.contracts import DiscordMessage
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.interactions import handle_interaction_payload
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.actions import JOB_ID_PREFIX
from agent_discord.host.panel import ASK_MODAL_ID, handle_gateway_interaction
from agent_discord.keys.vault import KeyVault
from agent_discord.orchestration.ask_gate import ask_confirm_custom_id, ask_custom_id
from agent_discord.orchestration.listen import drain_inbound
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend

from tests.test_connect_os import _snowflake_at

INTERACTION_APPLICATION_COMMAND = 2
INTERACTION_MESSAGE_COMPONENT = 3
INTERACTION_MODAL_SUBMIT = 5


class _Recorder:
    """Fake urlopen that records interaction callback bodies."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request, timeout=10):
        data = getattr(request, "data", None)
        if data:
            self.bodies.append(json.loads(data.decode("utf-8")))

        class _Resp:
            def read(self) -> bytes:
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return _Resp()


def _store(tmp_path: Path, *, owner: str = "") -> SQLiteStore:
    store = SQLiteStore(tmp_path / "agent_discord.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True)
    if owner:
        store.add_operator(owner, role="owner")
    return store


def _click(custom_id: str, user: str) -> dict[str, Any]:
    return {
        "type": INTERACTION_MESSAGE_COMPONENT,
        "id": "ix",
        "token": "tok",
        "application_id": "app-1",
        "channel_id": "ch",
        "member": {"user": {"id": user}, "roles": []},
        "data": {"custom_id": custom_id},
        "message": {"id": "card-1"},
    }


def _ask_modal(text: str, user: str) -> dict[str, Any]:
    return {
        "type": INTERACTION_MODAL_SUBMIT,
        "id": "ix",
        "token": "tok",
        "application_id": "app-1",
        "channel_id": "ch",
        "member": {"user": {"id": user}, "roles": []},
        "data": {
            "custom_id": ASK_MODAL_ID,
            "components": [
                {"type": 1, "components": [{"type": 4, "custom_id": "q", "value": text}]}
            ],
        },
    }


def test_job_card_buttons_deny_non_operator(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    calls: list[tuple[str, str]] = []
    recorder = _Recorder()
    for custom_id in (
        f"{JOB_ID_PREFIX}approve:run-1",
        f"{JOB_ID_PREFIX}always:run-1",
        f"{JOB_ID_PREFIX}cancel:run-1",
        f"{JOB_ID_PREFIX}retry:run-1",
        ask_custom_id("run-1", 0),
        ask_confirm_custom_id("run-1"),
    ):
        action = handle_gateway_interaction(
            store,
            "ch",
            _click(custom_id, "stranger-9"),
            opener=recorder,
            on_job=lambda a, r: calls.append((a, r)),
        )
        assert action == "denied", custom_id
    assert calls == []
    assert recorder.bodies
    for body in recorder.bodies:
        assert body["data"]["content"].startswith("Denied.")
        assert body["data"]["flags"] == 64
    store.close()


def _more_click(value: str, user: str) -> dict[str, Any]:
    from agent_discord.host.panel import MORE_ID

    click = _click(MORE_ID, user)
    click["data"]["values"] = [value]
    return click


def test_panel_actions_deny_non_operator_out_loud(tmp_path: Path) -> None:
    """Audit 2026-10-02 G1-4: a stranger's panel tap was silently deferred."""

    from agent_discord.host.panel import (
        GITHUB_ID,
        HALT_ID,
        JOBS_ID,
        OFF_ID,
        ON_ID,
        PANEL_DENIED_SPOKEN,
        POLL_ID,
    )
    from agent_discord.orchestration.service import is_spend_halted

    store = _store(tmp_path, owner="owner-1")
    store.set_host_control("ch", armed=True)
    clicks = [
        _click(ON_ID, "stranger-9"),
        _click(OFF_ID, "stranger-9"),
        _more_click(HALT_ID, "stranger-9"),
        _more_click(POLL_ID, "stranger-9"),
        _more_click(GITHUB_ID, "stranger-9"),
    ]
    select = _click(JOBS_ID, "stranger-9")
    select["data"]["values"] = ["run-1"]
    clicks.append(select)
    for click in clicks:
        recorder = _Recorder()
        action = handle_gateway_interaction(store, "ch", click, opener=recorder)
        assert action == "denied", click["data"]
        assert recorder.bodies, click["data"]
        assert [body["type"] for body in recorder.bodies] == [4], click["data"]
        body = recorder.bodies[0]
        assert body["data"]["content"] == PANEL_DENIED_SPOKEN
        assert body["data"]["flags"] == 64
    assert store.host_is_armed("ch") is True
    assert is_spend_halted(store) is False
    store.close()


def test_job_card_buttons_allow_operator(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    calls: list[tuple[str, str]] = []
    action = handle_gateway_interaction(
        store,
        "ch",
        _click(f"{JOB_ID_PREFIX}approve:run-1", "owner-1"),
        opener=_Recorder(),
        on_job=lambda a, r: calls.append((a, r)),
    )
    assert action == "approve"
    assert calls == [("approve", "run-1")]
    store.close()


def test_job_card_buttons_open_on_unpaired_desk(tmp_path: Path, monkeypatch) -> None:
    """HARD lock 8: no operators and no require flag keeps the desk workable."""

    monkeypatch.delenv("DISCORD_OS_REQUIRE_OPERATORS", raising=False)
    monkeypatch.delenv("DISCORD_OS_REQUIRE_ALLOWLIST", raising=False)
    monkeypatch.delenv("AGENT_DISCORD_INTERACTIONS", raising=False)
    store = _store(tmp_path)
    calls: list[tuple[str, str]] = []
    action = handle_gateway_interaction(
        store,
        "ch",
        _click(f"{JOB_ID_PREFIX}deny:run-1", "anyone"),
        opener=_Recorder(),
        on_job=lambda a, r: calls.append((a, r)),
    )
    assert action == "deny"
    assert calls == [("deny", "run-1")]
    store.close()


def test_ask_modal_requires_operator_and_carries_requester(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    asks: list[tuple[str, str]] = []

    denied = handle_gateway_interaction(
        store,
        "ch",
        _ask_modal("rewrite the repo", "stranger-9"),
        opener=_Recorder(),
        on_ask=lambda text, who: asks.append((text, who)),
    )
    assert denied == "denied"
    assert asks == []

    allowed = handle_gateway_interaction(
        store,
        "ch",
        _ask_modal("summarize open PRs", "owner-1"),
        opener=_Recorder(),
        on_ask=lambda text, who: asks.append((text, who)),
    )
    assert allowed == "ask"
    assert asks == [("summarize open PRs", "owner-1")]
    store.close()


def _orch(tmp_path: Path, store: SQLiteStore) -> tuple[AgentOrchestrator, DiscordFacade, Any]:
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        discord=facade,
        workspace=tmp_path,
    )
    return orch, facade, fake


def test_text_connect_from_non_operator_shreds_and_refuses(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    orch, facade, fake = _orch(tmp_path, store)
    now_ms = 1_750_000_000_000
    msg_id = _snowflake_at(now_ms + 1_000)
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="/connect sk-or-v1-not-a-real-key-abcdef",
            message_id=msg_id,
            author_id="stranger-9",
        )
    )
    drain_inbound(
        orch, facade, channel_id="ch", workspace_id="ws", workspace=tmp_path, since_ms=now_ms
    )
    assert KeyVault(tmp_path / "keys").get("openrouter") is None
    assert msg_id not in [m.message_id for m in fake.inbox]
    assert any("only paired operators" in m.content for m in fake.sent)
    store.close()


def test_text_off_from_non_operator_keeps_host_armed(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    orch, facade, fake = _orch(tmp_path, store)
    now_ms = 1_750_000_000_000
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="/off",
            message_id=_snowflake_at(now_ms + 1_000),
            author_id="stranger-9",
        )
    )
    drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=now_ms)
    assert store.host_is_armed("ch") is True
    store.close()


def _slash(name: str, user: str, options: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "type": INTERACTION_APPLICATION_COMMAND,
        "channel_id": "ch",
        "member": {"user": {"id": user}, "roles": []},
        "data": {"name": name, "options": options or []},
    }


def test_slash_state_commands_deny_non_operator(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    store.close()
    for name in ("connect", "open", "on", "off", "stop", "bind", "job", "clear-needs"):
        reply = handle_interaction_payload(
            _slash(name, "stranger-9"), workspace=tmp_path, roots=[tmp_path]
        )
        assert reply["data"]["content"] == f"Denied: only paired operators can use /{name}.", name
    store = SQLiteStore(tmp_path / "agent_discord.sqlite3")
    store.initialize()
    assert store.host_is_armed("ch") is True
    store.close()


def test_slash_off_allows_operator(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    store.close()
    reply = handle_interaction_payload(
        _slash("off", "owner-1"), workspace=tmp_path, roots=[tmp_path]
    )
    assert reply["data"]["content"] == "Off"


def test_slash_on_with_public_interactions_refuses_unpaired_seed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.close()
    reply = handle_interaction_payload(
        _slash("on", "stranger-9"),
        workspace=tmp_path,
        roots=[tmp_path],
        env={"AGENT_DISCORD_INTERACTIONS": "http"},
    )
    assert reply["data"]["content"].startswith("Denied")
    store = SQLiteStore(tmp_path / "agent_discord.sqlite3")
    store.initialize()
    assert store.list_operators() == []
    store.close()


def test_slash_status_stays_open(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    store.close()
    reply = handle_interaction_payload(
        _slash("status", "stranger-9"), workspace=tmp_path, roots=[tmp_path]
    )
    assert not reply["data"]["content"].startswith("Denied")


def _grant_always(store: SQLiteStore) -> None:
    from agent_discord.orchestration.service import (
        set_tool_class_session_allow,
        set_write_session_allow,
    )

    set_write_session_allow(store, "ch")
    set_tool_class_session_allow(store, "shell", "ch")


def _grants_live(store: SQLiteStore) -> bool:
    from agent_discord.orchestration.service import (
        tool_class_session_allows,
        write_session_allows_writes,
    )

    return write_session_allows_writes(store, "ch") or tool_class_session_allows(
        store, "shell", "ch"
    )


def test_text_off_revokes_always_grants(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    _grant_always(store)
    assert _grants_live(store)
    orch, facade, fake = _orch(tmp_path, store)
    now_ms = 1_750_000_000_000
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="/off",
            message_id=_snowflake_at(now_ms + 1_000),
            author_id="owner-1",
        )
    )
    drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=now_ms)
    assert store.host_is_armed("ch") is False
    assert not _grants_live(store)
    store.close()


def test_slash_off_revokes_always_grants(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    _grant_always(store)
    store.close()
    handle_interaction_payload(_slash("stop", "owner-1"), workspace=tmp_path, roots=[tmp_path])
    store = SQLiteStore(tmp_path / "agent_discord.sqlite3")
    store.initialize()
    assert store.host_is_armed("ch") is False
    assert not _grants_live(store)
    store.close()


def test_key_files_are_owner_only(tmp_path: Path) -> None:
    import os
    import stat

    from agent_discord.keys.connect import mint_pairing_ticket

    old_umask = os.umask(0o022)
    try:
        mint_pairing_ticket(tmp_path)
        KeyVault(tmp_path / "keys").put("openrouter", "sk-or-v1-not-a-real-key", "test")
    finally:
        os.umask(old_umask)
    keys = tmp_path / "keys"
    assert stat.S_IMODE(keys.stat().st_mode) == 0o700
    for name in ("tickets.json", "vault.json", "master.key"):
        assert stat.S_IMODE((keys / name).stat().st_mode) == 0o600, name


def test_existing_world_readable_tickets_are_tightened(tmp_path: Path) -> None:
    import stat

    from agent_discord.keys.connect import mint_pairing_ticket

    keys = tmp_path / "keys"
    keys.mkdir(mode=0o755)
    (keys / "tickets.json").write_text("{}", encoding="utf-8")
    (keys / "tickets.json").chmod(0o644)
    mint_pairing_ticket(tmp_path)
    assert stat.S_IMODE((keys / "tickets.json").stat().st_mode) == 0o600


def _roles_modal(text: str, user: str, guild_id: str = "111111111111111111") -> dict[str, Any]:
    from agent_discord.host.panel import ROLES_MODAL_ID

    return {
        "type": INTERACTION_MODAL_SUBMIT,
        "id": "ix",
        "token": "tok",
        "application_id": "app-1",
        "channel_id": "ch",
        "guild_id": guild_id,
        "member": {"user": {"id": user}, "roles": []},
        "data": {
            "custom_id": ROLES_MODAL_ID,
            "components": [
                {"type": 1, "components": [{"type": 4, "custom_id": "r", "value": text}]}
            ],
        },
    }


def test_roles_modal_refuses_everyone_and_junk(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    for text in ("111111111111111111", "role-99", "12", "<@&222222222222222222>"):
        handle_gateway_interaction(store, "ch", _roles_modal(text, "owner-1"), opener=_Recorder())
    assert store.list_operator_roles() == []
    store.close()


def test_roles_modal_adds_then_removes(tmp_path: Path) -> None:
    store = _store(tmp_path, owner="owner-1")
    role = "222222222222222222"
    handle_gateway_interaction(store, "ch", _roles_modal(role, "owner-1"), opener=_Recorder())
    assert store.list_operator_roles() == [role]
    assert store.is_operator("member-5", role_ids=[role])
    handle_gateway_interaction(
        store, "ch", _roles_modal(f"-{role}", "owner-1"), opener=_Recorder()
    )
    assert store.list_operator_roles() == []
    assert not store.is_operator("member-5", role_ids=[role])
    store.close()


def _ask(fake, now_ms: int, offset: int, text: str = "summarize open PRs", author: str = "owner-1"):
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content=text,
            message_id=_snowflake_at(now_ms + offset),
            author_id=author,
        )
    )


def _notices(fake, needle: str) -> int:
    return sum(1 for m in fake.sent if needle in (m.content or ""))


def test_ask_while_off_replies_once_until_an_ask_runs(tmp_path: Path) -> None:
    """Audit B6: asks while Off were dropped with no reply."""

    store = _store(tmp_path, owner="owner-1")
    store.set_host_control("ch", armed=False)
    orch, facade, fake = _orch(tmp_path, store)
    now_ms = 1_750_000_000_000
    _ask(fake, now_ms, 1_000)
    _ask(fake, now_ms, 2_000)
    receipts = drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=now_ms)
    assert receipts == []
    assert _notices(fake, "Host is Off") == 1

    store.set_host_control("ch", armed=True)
    _ask(fake, now_ms, 3_000)
    assert len(drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=now_ms)) == 1

    store.set_host_control("ch", armed=False)
    _ask(fake, now_ms, 4_000)
    drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=now_ms)
    assert _notices(fake, "Host is Off") == 2
    store.close()


def test_ask_while_halted_replies_and_strangers_get_nothing(tmp_path: Path) -> None:
    from agent_discord.orchestration.service import set_spend_halted

    store = _store(tmp_path, owner="owner-1")
    set_spend_halted(store, True)
    orch, facade, fake = _orch(tmp_path, store)
    now_ms = 1_750_000_000_000
    _ask(fake, now_ms, 1_000, author="stranger-9")
    drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=now_ms)
    assert _notices(fake, "Spend is halted") == 0
    _ask(fake, now_ms, 2_000)
    drain_inbound(orch, facade, channel_id="ch", workspace_id="ws", since_ms=now_ms)
    assert _notices(fake, "Spend is halted") == 1
    store.close()
