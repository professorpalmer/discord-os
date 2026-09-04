"""Host surfaces: Discord is the remote; this process opens Terminal/files/browser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_discord.cli import main
from agent_discord.contracts import DiscordMessage
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.actions import (
    DEST_HOST,
    DEST_REMOTE,
    HostActionError,
    OpenIntent,
    allow_browser_url,
    confine_host_path,
    dest_hint_from_interaction,
    host_browser_argv,
    interaction_client_platform,
    job_action_from_custom_id,
    job_custom_id,
    list_remote_files,
    open_custom_id,
    open_intent_from_custom_id,
    run_host_action,
    run_open_intent,
)
from agent_discord.host.panel import (
    ASK_ID,
    BROWSER_ID,
    JOBS_ID,
    MORE_ID,
    OFF_ID,
    ON_ID,
    handle_gateway_interaction,
    panel_action_from_custom_id,
)
from agent_discord.host.verbs import handle_open_message, is_open_command, parse_open_command
from agent_discord.orchestration.cards import CARD_PREFIX
from agent_discord.orchestration.listen import drain_inbound, should_dispatch_inbound
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def test_job_custom_ids_parse_without_host_power():
    approve = job_custom_id("approve", "run-9")
    cancel = job_custom_id("cancel", "run-9")
    retry = job_custom_id("retry", "run-9")
    assert approve == "discord-os:job:approve:run-9"
    assert job_action_from_custom_id(approve) == job_action_from_custom_id(
        "discord-os:job:approve:run-9"
    )
    parsed = job_action_from_custom_id(approve)
    assert parsed is not None
    assert parsed.action == "approve"
    assert parsed.run_id == "run-9"
    assert job_action_from_custom_id(cancel).action == "cancel"
    assert job_action_from_custom_id(retry).action == "retry"
    assert job_action_from_custom_id(ON_ID) is None
    assert job_action_from_custom_id(OFF_ID) is None
    assert job_action_from_custom_id(ASK_ID) is None
    assert job_action_from_custom_id(JOBS_ID) is None
    assert panel_action_from_custom_id(approve) is None
    assert panel_action_from_custom_id(cancel) is None
    assert panel_action_from_custom_id(retry) is None
    for custom_id in (approve, cancel, retry):
        assert custom_id not in {
            ON_ID,
            OFF_ID,
            ASK_ID,
            JOBS_ID,
            "discord-os:pair",
            "discord-os:halt",
            "discord-os:roles",
            "discord-os:files",
            "discord-os:terminal",
            "discord-os:browser",
        }


def test_confine_host_path_stays_inside_roots(tmp_path: Path):
    nested = tmp_path / "src"
    nested.mkdir()
    resolved = confine_host_path("src", [tmp_path])
    assert resolved == nested.resolve()
    assert confine_host_path(str(nested), [tmp_path]) == nested.resolve()


def test_confine_host_path_rejects_home_and_escape(tmp_path: Path):
    with pytest.raises(HostActionError, match="home-relative"):
        confine_host_path("~/.ssh", [tmp_path])
    outside = tmp_path.parent / "outside-host-root"
    with pytest.raises(HostActionError, match="outside host roots"):
        confine_host_path(str(outside), [tmp_path])
    with pytest.raises(HostActionError, match="no host roots"):
        confine_host_path(".", [])


def test_allow_browser_url_allowlist():
    assert allow_browser_url("http://127.0.0.1:8743/health") == "http://127.0.0.1:8743/health"
    assert allow_browser_url("https://localhost/ok") == "https://localhost/ok"
    jump = "https://discord.com/channels/1/2/3"
    assert allow_browser_url(jump) == jump
    with pytest.raises(HostActionError, match="allowlist"):
        allow_browser_url("https://example.com/")
    with pytest.raises(HostActionError, match="http"):
        allow_browser_url("javascript:alert(1)")
    with pytest.raises(HostActionError, match="jump"):
        allow_browser_url("https://discord.com/app")


def test_run_host_action_uses_injected_runner(tmp_path: Path):
    calls: list[tuple[list[str], str | None]] = []

    def runner(argv, *, cwd=None):
        calls.append((list(argv), cwd))

    opened_urls: list[str] = []
    files = run_host_action("files", ".", roots=[tmp_path], runner=runner)
    assert files.opened
    assert calls
    assert Path(files.target) == tmp_path.resolve()
    term = run_host_action("terminal", ".", roots=[tmp_path], runner=runner)
    assert term.opened
    assert term.argv
    browser = run_host_action(
        "browser",
        "http://127.0.0.1:9/health",
        roots=[tmp_path],
        browser_open=opened_urls.append,
    )
    assert browser.opened
    assert opened_urls == ["http://127.0.0.1:9/health"]
    with pytest.raises(HostActionError, match="unknown surface"):
        run_host_action("camera", ".", roots=[tmp_path], runner=runner)


def test_browser_button_launches_local_browser(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DISCORD_OS_BROWSER", "/opt/harness-chromium")
    calls: list[list[str]] = []

    def runner(argv, *, cwd=None):
        calls.append(list(argv))

    launched = run_host_action("browser", "", roots=[tmp_path], runner=runner)
    assert launched.opened
    assert launched.target == "harness chromium"
    assert calls == [["/opt/harness-chromium"]]
    argv = host_browser_argv("http://127.0.0.1:9/health")
    assert argv == ["/opt/harness-chromium", "http://127.0.0.1:9/health"]


def test_parse_open_command_surfaces():
    assert is_open_command("/open terminal")
    assert is_open_command("!open files src")
    parsed = parse_open_command("/open terminal src")
    assert parsed.surface == "terminal"
    assert parsed.target == "src"
    jump = parse_open_command("/open https://discord.com/channels/1/2/3")
    assert jump.surface == "browser"
    assert jump.dest == DEST_REMOTE
    assert parse_open_command("/open browser").target == ""
    assert parse_open_command("/open browser").dest == DEST_HOST
    assert parse_open_command("/open").surface == "files"
    assert parse_open_command("/open here files").dest == DEST_REMOTE
    assert parse_open_command("/open host browser http://127.0.0.1/health").dest == DEST_HOST


def test_listen_open_does_not_dispatch_implement(tmp_path: Path):
    store = SQLiteStore(tmp_path / "open.sqlite3")
    store.initialize()
    fake = FakeDiscordMCPProvider()
    fake.inbox.append(
        DiscordMessage(
            channel_id="ch",
            content="/open terminal .",
            message_id="open-1",
            author_id="phone",
        )
    )
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    backend = FakePuppetmasterBackend()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=facade,
        workspace=tmp_path,
    )
    calls: list[tuple[list[str], str | None]] = []

    def runner(argv, *, cwd=None):
        calls.append((list(argv), cwd))

    receipts = drain_inbound(
        orch,
        facade,
        channel_id="ch",
        workspace_id="ws",
        workspace=tmp_path,
        host_roots=[tmp_path],
        host_runner=runner,
    )
    assert receipts == []
    assert backend.dispatch_count == 0
    assert calls
    texts = "\n".join(
        item.get("content") or ""
        for m in fake.sent
        for row in ((m.metadata or {}).get("components") or [])
        for item in row.get("components") or []
        if item.get("type") == 10
    )
    assert "### Opened" in texts
    store.close()


def test_should_dispatch_skips_open_cards():
    assert not should_dispatch_inbound(
        DiscordMessage(channel_id="ch", content=f"{CARD_PREFIX} OPEN\nSurface: `files`")
    )


def test_cli_open_json_uses_injected_handler(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ws = tmp_path / ".agent-discord"
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("PUPPETMASTER_MODEL", "cursor/grok-4-5")

    def fake_handle(text, *, roots, runner=None, browser_open=None):
        from agent_discord.host.verbs import OpenPublicResult

        return OpenPublicResult(
            surface="files",
            target=str(tmp_path),
            card=f"{CARD_PREFIX} OPEN\nSurface: `files`",
            opened=True,
        )

    monkeypatch.setattr("agent_discord.host.verbs.handle_open_message", fake_handle)
    assert main(["open", "files", ".", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["opened"] is True
    assert payload["surface"] == "files"


def test_handle_open_message_rejects_escape(tmp_path: Path):
    result = handle_open_message(
        "/open files /etc/passwd",
        roots=[tmp_path],
        runner=lambda *a, **k: None,
    )
    assert result.opened is False
    assert "outside" in result.error
    assert result.card.startswith("Could not open")


def test_browser_button_acks_update_not_url_modal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DISCORD_OS_BROWSER", "/opt/harness-chromium")
    store = SQLiteStore(tmp_path / "browser.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True)
    opened: list[list[str]] = []
    captured: list[dict] = []

    def runner(argv, *, cwd=None):
        opened.append(list(argv))

    class _Resp:
        def read(self) -> bytes:
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def opener(request, timeout=10):
        captured.append(
            json.loads(request.data.decode("utf-8")) if request.data else {}
        )
        return _Resp()

    result = handle_gateway_interaction(
        store,
        "ch",
        {
            "type": 3,
            "id": "ix",
            "token": "tok",
            "application_id": "app-1",
            "user": {"id": "owner-1"},
            "data": {"custom_id": BROWSER_ID},
            "message": {"id": "panel-1"},
        },
        opener=opener,
        host_roots=[tmp_path],
        host_runner=runner,
    )
    assert result == "browser"
    assert captured[0]["type"] == 6
    assert opened == [["/opt/harness-chromium"]]
    store.close()


def test_dest_hint_empty_on_todays_interaction_shape():
    payload = {
        "type": 3,
        "id": "ix",
        "token": "tok",
        "locale": "en-US",
        "context": 0,
        "member": {"user": {"id": "1"}, "roles": []},
        "data": {"custom_id": "discord-os:more", "values": ["discord-os:open:browser:remote"]},
    }
    assert interaction_client_platform(payload) == ""
    assert dest_hint_from_interaction(payload) == ""
    hinted = dict(payload)
    hinted["used_client"] = "mobile"
    assert dest_hint_from_interaction(hinted) == DEST_REMOTE
    hinted["used_client"] = "desktop"
    assert dest_hint_from_interaction(hinted) == DEST_HOST


def test_open_intent_legacy_ids_stay_host():
    files = open_intent_from_custom_id("discord-os:files")
    assert files is not None
    assert files.surface == "files"
    assert files.dest == DEST_HOST
    browser = open_intent_from_custom_id(BROWSER_ID)
    assert browser is not None
    assert browser.dest == DEST_HOST
    remote = open_intent_from_custom_id(open_custom_id("browser", DEST_REMOTE))
    assert remote == OpenIntent(surface="browser", target="", dest=DEST_REMOTE)
    assert open_intent_from_custom_id(ON_ID) is None


def test_run_open_intent_remote_does_not_launch_gui(tmp_path: Path):
    (tmp_path / "readme.txt").write_text("hi", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(argv, *, cwd=None):
        calls.append(list(argv))

    listed = run_open_intent(
        OpenIntent(surface="files", target=".", dest=DEST_REMOTE),
        roots=[tmp_path],
        runner=runner,
    )
    assert listed.opened
    assert listed.dest == DEST_REMOTE
    assert "readme.txt" in listed.listing
    assert calls == []
    assert "readme.txt" in list_remote_files(".", [tmp_path])

    opened_urls: list[str] = []
    link = run_open_intent(
        OpenIntent(
            surface="browser",
            target="http://127.0.0.1:9/health",
            dest=DEST_REMOTE,
        ),
        roots=[tmp_path],
        runner=runner,
        browser_open=opened_urls.append,
    )
    assert link.opened
    assert link.link_url == "http://127.0.0.1:9/health"
    assert opened_urls == []
    assert calls == []
    with pytest.raises(HostActionError, match="dest is host"):
        run_open_intent(
            OpenIntent(surface="terminal", target=".", dest=DEST_REMOTE),
            roots=[tmp_path],
            runner=runner,
        )


def test_open_card_remote_browser_is_a_link():
    from agent_discord.orchestration.cards import open_card

    card = open_card(
        surface="browser",
        target="http://127.0.0.1:9/health",
        dest=DEST_REMOTE,
        link_url="http://127.0.0.1:9/health",
    )
    assert card.title == "Open here"
    assert card.link_url == "http://127.0.0.1:9/health"
    dumped = json.dumps(card.v2_components())
    assert "http://127.0.0.1:9/health" in dumped
    assert dumped.count('"style": 5') == 1


def test_remote_browser_more_opens_url_modal(tmp_path: Path):
    store = SQLiteStore(tmp_path / "remote-browser.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True)
    opened: list[list[str]] = []
    captured: list[dict] = []

    def runner(argv, *, cwd=None):
        opened.append(list(argv))

    class _Resp:
        def read(self) -> bytes:
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def opener(request, timeout=10):
        captured.append(
            json.loads(request.data.decode("utf-8")) if request.data else {}
        )
        return _Resp()

    result = handle_gateway_interaction(
        store,
        "ch",
        {
            "type": 3,
            "id": "ix",
            "token": "tok",
            "application_id": "app-1",
            "user": {"id": "owner-1"},
            "data": {
                "custom_id": MORE_ID,
                "values": [open_custom_id("browser", DEST_REMOTE)],
            },
            "message": {"id": "panel-1"},
        },
        opener=opener,
        host_roots=[tmp_path],
        host_runner=runner,
    )
    assert result == "browser"
    assert captured[0]["type"] == 9
    assert captured[0]["data"]["custom_id"] == "discord-os:browser-modal:remote"
    assert opened == []
    store.close()


def test_remote_files_more_lists_in_followup(tmp_path: Path):
    (tmp_path / "notes.md").write_text("list me", encoding="utf-8")
    store = SQLiteStore(tmp_path / "remote-files.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True)
    opened: list[list[str]] = []
    captured: list[dict] = []

    def runner(argv, *, cwd=None):
        opened.append(list(argv))

    class _Resp:
        def read(self) -> bytes:
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def opener(request, timeout=10):
        captured.append(
            json.loads(request.data.decode("utf-8")) if request.data else {}
        )
        return _Resp()

    result = handle_gateway_interaction(
        store,
        "ch",
        {
            "type": 3,
            "id": "ix",
            "token": "tok",
            "application_id": "app-1",
            "user": {"id": "owner-1"},
            "data": {
                "custom_id": MORE_ID,
                "values": [open_custom_id("files", DEST_REMOTE)],
            },
            "message": {"id": "panel-1"},
        },
        opener=opener,
        host_roots=[tmp_path],
        host_runner=runner,
    )
    assert result == "files"
    assert opened == []
    dumped = json.dumps(captured)
    assert "notes.md" in dumped
    assert "Files here" in dumped
    store.close()
