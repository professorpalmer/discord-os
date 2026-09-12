"""P0.3: HOST Jobs panel refresh after dismiss/cancel; harden missing card id."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request

from agent_discord.contracts import TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.actions import job_custom_id
from agent_discord.host.panel import (
    JOBS_PANEL_RANK_ACTIONS,
    ON_ID,
    JOBS_ID,
    _PANEL_STALE_NEED_SPOKEN,
    handle_gateway_interaction,
    refresh_host_jobs_panel,
)
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        return None


def _orch(tmp_path: Path) -> AgentOrchestrator:
    store = SQLiteStore(tmp_path / "jobs-refresh.sqlite3")
    store.initialize()
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    return AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        discord=facade,
        post_progress_to_discord=True,
    )


def test_jobs_panel_rank_actions_include_dismiss_and_cancel():
    assert "dismiss" in JOBS_PANEL_RANK_ACTIONS
    assert "ack" in JOBS_PANEL_RANK_ACTIONS
    assert "cancel" in JOBS_PANEL_RANK_ACTIONS


def test_refresh_edits_when_card_message_id_known(tmp_path: Path):
    store = SQLiteStore(tmp_path / "known.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True, card_message_id="panel-42")
    store.create_task(
        task_id="t1",
        workspace_id="ws",
        channel_id="ch",
        intake_text="failed need",
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.FAILED,
    )
    patches: list[str] = []

    def opener(request: Request, timeout=10):
        url = str(request.full_url)
        if request.get_method() == "PATCH" and "messages/panel-42" in url:
            patches.append(url)
            body = json.loads(request.data.decode("utf-8"))
            assert body.get("components")
            return _FakeResponse(b"{}")
        return _FakeResponse(b"{}")

    ok = refresh_host_jobs_panel(store, "ch", token="bot-token", opener=opener)
    assert ok is True
    assert patches
    assert store.get_preference("_host", "jobs_panel_stale_need:ch") in {None, ""}
    store.close()


def test_refresh_recovers_missing_card_message_id(tmp_path: Path):
    store = SQLiteStore(tmp_path / "recover.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True, card_message_id="")
    calls: list[str] = []

    def opener(request: Request, timeout=10):
        url = str(request.full_url)
        method = request.get_method()
        calls.append(f"{method} {url}")
        if method == "GET" and "/messages" in url:
            payload = [
                {
                    "id": "noise-1",
                    "channel_id": "ch",
                    "content": "hi",
                    "author": {"id": "u"},
                    "components": [],
                },
                {
                    "id": "recovered-panel",
                    "channel_id": "ch",
                    "content": "",
                    "author": {"id": "bot"},
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 2,
                                    "custom_id": ON_ID,
                                    "label": "On",
                                    "style": 3,
                                }
                            ],
                        },
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 3,
                                    "custom_id": JOBS_ID,
                                    "options": [
                                        {
                                            "label": "x",
                                            "value": "r1",
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                },
            ]
            return _FakeResponse(json.dumps(payload).encode("utf-8"))
        if method == "PATCH" and "messages/recovered-panel" in url:
            return _FakeResponse(b"{}")
        return _FakeResponse(b"{}")

    ok = refresh_host_jobs_panel(store, "ch", token="bot-token", opener=opener)
    assert ok is True
    assert store.get_host_control("ch")["card_message_id"] == "recovered-panel"
    assert any("PATCH" in c and "recovered-panel" in c for c in calls)
    store.close()


def test_refresh_repaints_when_recover_finds_nothing(tmp_path: Path):
    store = SQLiteStore(tmp_path / "repaint.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True, card_message_id="")

    def opener(request: Request, timeout=10):
        method = request.get_method()
        url = str(request.full_url)
        if method == "GET" and "/messages" in url:
            return _FakeResponse(b"[]")
        if method == "POST" and url.endswith("/messages"):
            return _FakeResponse(
                json.dumps(
                    {
                        "id": "fresh-panel",
                        "channel_id": "ch",
                        "content": "",
                        "author": {"id": "bot"},
                        "components": [],
                    }
                ).encode("utf-8")
            )
        return _FakeResponse(b"{}")

    ok = refresh_host_jobs_panel(store, "ch", token="bot-token", opener=opener)
    assert ok is True
    assert store.get_host_control("ch")["card_message_id"] == "fresh-panel"
    store.close()


def test_refresh_speaks_need_once_when_impossible(tmp_path: Path):
    store = SQLiteStore(tmp_path / "need.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True, card_message_id="")
    spoken: list[str] = []

    def opener(request: Request, timeout=10):
        method = request.get_method()
        url = str(request.full_url)
        if method == "GET" and "/messages" in url:
            raise RuntimeError("list failed")
        if method == "POST" and url.endswith("/messages"):
            body = json.loads(request.data.decode("utf-8")) if request.data else {}
            content = str(body.get("content") or "")
            if content:
                spoken.append(content)
                return _FakeResponse(
                    json.dumps(
                        {
                            "id": "need-msg",
                            "channel_id": "ch",
                            "content": content,
                            "author": {"id": "bot"},
                        }
                    ).encode("utf-8")
                )
            raise RuntimeError("repaint failed")
        return _FakeResponse(b"{}")

    assert refresh_host_jobs_panel(store, "ch", token="bot-token", opener=opener) is False
    assert spoken == [_PANEL_STALE_NEED_SPOKEN]
    assert store.get_preference("_host", "jobs_panel_stale_need:ch") == "1"
    spoken.clear()
    assert refresh_host_jobs_panel(store, "ch", token="bot-token", opener=opener) is False
    assert spoken == []
    store.close()


def test_dismiss_interaction_refreshes_jobs_panel(tmp_path: Path):
    store = SQLiteStore(tmp_path / "dismiss-ix.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True, card_message_id="panel-1")
    store.create_task(
        task_id="fail-task",
        workspace_id="ws",
        channel_id="ch",
        intake_text="boom",
        thread_id="th-1",
    )
    store.create_run(
        run_id="fail-run",
        task_id="fail-task",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.FAILED,
    )
    orch = _orch(tmp_path / "orch-dismiss")
    # Reuse same store pattern via on_job → apply on dedicated orch store:
    # exercise panel refresh path with a local on_job that mutates this store.
    from agent_discord.host.panel import _panel_last_job

    applied: list[tuple[str, str]] = []

    def on_job(action: str, run_id: str) -> None:
        applied.append((action, run_id))
        store.update_run(
            run_id,
            status=TaskStatus.CANCELLED,
            summary="dismissed",
            error="dismissed",
        )

    patches: list[str] = []

    def opener(request: Request, timeout=10):
        url = str(request.full_url)
        if request.get_method() == "POST" and "callback" in url:
            return _FakeResponse(b"")
        if request.get_method() == "PATCH" and "messages/panel-1" in url:
            patches.append(url)
            return _FakeResponse(b"{}")
        return _FakeResponse(b"{}")

    action = handle_gateway_interaction(
        store,
        "ch",
        {
            "type": 3,
            "id": "ix-d",
            "token": "tok",
            "application_id": "app",
            "channel_id": "ch",
            "data": {"custom_id": job_custom_id("dismiss", "fail-run")},
            "message": {"id": "job-card-9"},
        },
        token="bot-token",
        opener=opener,
        on_job=on_job,
    )
    assert action == "dismiss"
    assert applied == [("dismiss", "fail-run")]
    assert patches
    assert store.get_run("fail-run")["status"] == "cancelled"
    _ = orch
    _ = _panel_last_job
    store.close()


def test_cancel_interaction_triggers_jobs_panel_refresh(tmp_path: Path):
    store = SQLiteStore(tmp_path / "cancel-ix.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True, card_message_id="panel-7")
    patches: list[str] = []

    def opener(request: Request, timeout=10):
        url = str(request.full_url)
        if request.get_method() == "POST" and "callback" in url:
            return _FakeResponse(b"")
        if request.get_method() == "PATCH" and "messages/panel-7" in url:
            patches.append(url)
            return _FakeResponse(b"{}")
        return _FakeResponse(b"{}")

    action = handle_gateway_interaction(
        store,
        "ch",
        {
            "type": 3,
            "id": "ix-c",
            "token": "tok",
            "application_id": "app",
            "channel_id": "ch",
            "data": {"custom_id": job_custom_id("cancel", "live-run")},
            "message": {"id": "live-card"},
        },
        token="bot-token",
        opener=opener,
        on_job=lambda a, r: None,
    )
    assert action == "cancel"
    assert patches
    store.close()
