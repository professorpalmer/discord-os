"""P0.4: Bulk clear stale failed Needs (Dismiss semantics + HOST refresh)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request

from agent_discord.cli import main
from agent_discord.contracts import TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.panel import (
    CLEAR_NEEDS_CANCEL_ID,
    CLEAR_NEEDS_CONFIRM_ID,
    CLEAR_NEEDS_ID,
    MORE_ID,
    handle_gateway_interaction,
    host_panel_components,
    panel_action_from_custom_id,
    panel_action_from_interaction,
)
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def _orch(tmp_path: Path) -> AgentOrchestrator:
    store = SQLiteStore(tmp_path / "clear-needs.sqlite3")
    store.initialize()
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    return AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        discord=facade,
        post_progress_to_discord=True,
    )


def _seed_failed(
    store: SQLiteStore,
    *,
    task_id: str,
    run_id: str,
    channel_id: str = "ch",
    attention: str = "",
) -> None:
    store.create_task(
        task_id=task_id,
        workspace_id="ws",
        channel_id=channel_id,
        intake_text=f"task {task_id}",
    )
    store.create_run(
        run_id=run_id,
        task_id=task_id,
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.FAILED,
    )
    store.update_run(run_id, status=TaskStatus.FAILED, summary="boom", error="boom")
    if attention:
        store.set_job_github_attention(task_id, attention, summary="need")


def test_clear_needs_refuses_without_failed_flag(tmp_path: Path):
    orch = _orch(tmp_path)
    _seed_failed(orch.store, task_id="t1", run_id="r1")
    result = orch.clear_failed_needs(failed=False)
    assert result["status"] == "refused"
    assert result["cleared"] == 0
    assert orch.store.get_run("r1")["status"] == "failed"


def test_clear_needs_dry_run_lists_without_mutating(tmp_path: Path):
    orch = _orch(tmp_path)
    _seed_failed(orch.store, task_id="t1", run_id="r1")
    result = orch.clear_failed_needs(failed=True, dry_run=True)
    assert result["status"] == "dry-run"
    assert result["matched"] == 1
    assert result["cleared"] == 0
    assert orch.store.get_run("r1")["status"] == "failed"


def test_clear_needs_dismisses_failed_and_attention_need(tmp_path: Path):
    orch = _orch(tmp_path)
    store = orch.store
    _seed_failed(store, task_id="fail", run_id="fail-run")
    store.create_task(
        task_id="done",
        workspace_id="ws",
        channel_id="ch",
        intake_text="done",
    )
    store.create_run(
        run_id="done-run",
        task_id="done",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.COMPLETED,
    )
    store.set_job_github_attention("done", "need", summary="checks failed")
    store.create_task(
        task_id="ok",
        workspace_id="ws",
        channel_id="ch",
        intake_text="ok",
    )
    store.create_run(
        run_id="ok-run",
        task_id="ok",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.COMPLETED,
    )

    result = orch.clear_failed_needs(failed=True, channel_id="ch")
    assert result["status"] == "ok"
    assert result["matched"] == 2
    assert result["cleared"] == 2
    assert store.get_run("fail-run")["status"] == "cancelled"
    assert store.get_run("fail-run")["summary"] == "dismissed"
    assert store.get_run("done-run")["status"] == "completed"
    assert not (store.task_metadata("done").get("github") or {}).get("attention")
    assert store.get_run("ok-run")["status"] == "completed"


def test_clear_needs_older_than_filter(tmp_path: Path):
    orch = _orch(tmp_path)
    store = orch.store
    _seed_failed(store, task_id="old", run_id="old-run")
    _seed_failed(store, task_id="new", run_id="new-run")
    # Backdate the old task so --older-than 2 matches only it.
    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    store._connection().execute(
        "UPDATE tasks SET updated_at=? WHERE task_id=?",
        (old_ts, "old"),
    )
    store._connection().commit()

    dry = orch.clear_failed_needs(failed=True, older_than_days=2, dry_run=True)
    assert dry["matched"] == 1
    assert dry["runs"][0]["run_id"] == "old-run"

    result = orch.clear_failed_needs(failed=True, older_than_days=2)
    assert result["cleared"] == 1
    assert store.get_run("old-run")["status"] == "cancelled"
    assert store.get_run("new-run")["status"] == "failed"


def test_clear_needs_channel_filter(tmp_path: Path):
    orch = _orch(tmp_path)
    _seed_failed(orch.store, task_id="a", run_id="ra", channel_id="ch-a")
    _seed_failed(orch.store, task_id="b", run_id="rb", channel_id="ch-b")
    result = orch.clear_failed_needs(failed=True, channel_id="ch-a")
    assert result["cleared"] == 1
    assert orch.store.get_run("ra")["status"] == "cancelled"
    assert orch.store.get_run("rb")["status"] == "failed"


def test_more_menu_includes_clear_failed_needs():
    assert panel_action_from_custom_id(CLEAR_NEEDS_ID) == "clear-needs"
    assert panel_action_from_custom_id(CLEAR_NEEDS_CONFIRM_ID) == "clear-needs-confirm"
    assert panel_action_from_custom_id(CLEAR_NEEDS_CANCEL_ID) == "clear-needs-cancel"
    more = host_panel_components(False)[1]["components"][0]
    values = [item["value"] for item in more["options"]]
    assert CLEAR_NEEDS_ID in values
    labels = [item["label"] for item in more["options"]]
    assert "Clear failed Needs" in labels
    assert panel_action_from_interaction(
        {"type": 3, "data": {"custom_id": MORE_ID, "values": [CLEAR_NEEDS_ID]}}
    ) == "clear-needs"


def test_panel_clear_needs_confirm_flow(tmp_path: Path):
    store = SQLiteStore(tmp_path / "panel-clear.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True, card_message_id="panel-1")
    _seed_failed(store, task_id="t1", run_id="r1", channel_id="ch")
    paints: list[dict] = []

    class _Resp:
        def __init__(self, body: bytes = b"{}"):
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def opener(request: Request, timeout=10):
        raw = request.data or b""
        if isinstance(raw, bytes) and raw:
            try:
                paints.append(json.loads(raw.decode("utf-8")))
            except Exception:
                paints.append({"raw": raw[:80]})
        return _Resp(b'{"id":"panel-1"}')

    payload = {
        "type": 3,
        "id": "ix1",
        "token": "tok",
        "application_id": "app",
        "channel_id": "ch",
        "data": {"custom_id": MORE_ID, "values": [CLEAR_NEEDS_ID]},
        "member": {"user": {"id": "u1"}},
    }
    assert handle_gateway_interaction(
        store, "ch", payload, token="bot", opener=opener
    ) == "clear-needs"
    # Confirm row should mention Clear
    confirm_payload = {
        "type": 3,
        "id": "ix2",
        "token": "tok2",
        "application_id": "app",
        "channel_id": "ch",
        "data": {"custom_id": CLEAR_NEEDS_CONFIRM_ID},
        "member": {"user": {"id": "u1"}},
    }
    cleared: list[dict] = []

    def on_clear_needs(**kwargs):
        orch = AgentOrchestrator(
            store=store,
            backend=FakePuppetmasterBackend(),
            discord=DiscordFacade(
                FakeDiscordMCPProvider(), bot_token_fingerprint="fp", owner_id="t"
            ),
            post_progress_to_discord=False,
        )
        result = orch.clear_failed_needs(**kwargs)
        cleared.append(result)
        return result

    assert (
        handle_gateway_interaction(
            store,
            "ch",
            confirm_payload,
            token="bot",
            opener=opener,
            on_clear_needs=on_clear_needs,
        )
        == "clear-needs-confirm"
    )
    assert cleared and cleared[0]["cleared"] == 1
    assert store.get_run("r1")["status"] == "cancelled"


def test_cli_jobs_clear_needs_dry_run(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "")
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    _seed_failed(store, task_id="t1", run_id="r1")
    store.close()

    assert (
        main(
            [
                "jobs",
                "clear-needs",
                "--failed",
                "--dry-run",
                "--fake",
                "--json",
            ]
        )
        == 0
    )
