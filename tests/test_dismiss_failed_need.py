"""P0.1: Dismiss / Ack a failed Need so briefing ranks Last."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.panel import _panel_last_job
from agent_discord.orchestration.job_briefing import briefing_line, briefing_prefix
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def _orch(tmp_path: Path) -> AgentOrchestrator:
    store = SQLiteStore(tmp_path / "dismiss.sqlite3")
    store.initialize()
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    backend = FakePuppetmasterBackend()
    return AgentOrchestrator(
        store=store,
        backend=backend,
        discord=facade,
        post_progress_to_discord=True,
    )


def test_briefing_failed_is_need_cancelled_is_last():
    assert briefing_prefix({"status": "failed"}) == "Need"
    assert briefing_line({"status": "failed", "job_code": "DOS-10036", "summary": "boom"}).startswith(
        "Need:"
    )
    assert briefing_prefix({"status": "cancelled", "summary": "dismissed"}) == "Last"
    assert briefing_prefix({"status": "failed", "attention": "need"}) == "Need"
    assert briefing_prefix({"status": "completed", "attention": "need"}) == "Need"
    assert briefing_prefix({"status": "completed", "attention": ""}) == "Last"


def test_dismiss_failed_need_marks_cancelled_and_leaves_need_rank(tmp_path: Path):
    orch = _orch(tmp_path)
    store = orch.store
    store.create_task(
        task_id="fail-task",
        workspace_id="ws",
        channel_id="ch",
        intake_text="do the thing",
        thread_id="th-1",
    )
    store.create_run(
        run_id="fail-run",
        task_id="fail-task",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.RUNNING,
    )
    store.update_run("fail-run", status=TaskStatus.FAILED, summary="boom", error="boom")
    store.set_job_github_attention("fail-task", "need", summary="checks failed")
    assert _panel_last_job(store, "ch").startswith("Need:")

    result = orch.apply_job_action("dismiss", "fail-run")
    assert result["action"] == "dismiss"
    assert result["status"] == "cancelled"
    run = store.get_run("fail-run")
    assert run is not None
    assert run["status"] == "cancelled"
    assert (run.get("summary") or "") == "dismissed"
    task = store.get_task("fail-task")
    assert task is not None
    assert task["status"] == "cancelled"
    meta = store.task_metadata("fail-task")
    github = meta.get("github") if isinstance(meta, dict) else {}
    assert not (github or {}).get("attention")
    line = _panel_last_job(store, "ch")
    assert line.startswith("Last:")
    assert "Need:" not in line


def test_ack_alias_dismisses_failed_need(tmp_path: Path):
    orch = _orch(tmp_path)
    store = orch.store
    store.create_task(
        task_id="fail-task",
        workspace_id="ws",
        channel_id="ch",
        intake_text="do the thing",
    )
    store.create_run(
        run_id="fail-run",
        task_id="fail-task",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.FAILED,
    )
    result = orch.apply_job_action("ack", "fail-run")
    assert result["status"] == "cancelled"
    assert store.get_run("fail-run")["status"] == "cancelled"


def test_dismiss_clears_attention_need_without_cancelling_completed(tmp_path: Path):
    orch = _orch(tmp_path)
    store = orch.store
    store.create_task(
        task_id="done-task",
        workspace_id="ws",
        channel_id="ch",
        intake_text="shipped",
    )
    store.create_run(
        run_id="done-run",
        task_id="done-task",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.COMPLETED,
    )
    store.set_job_github_attention("done-task", "need", summary="PR checks failed")
    assert _panel_last_job(store, "ch").startswith("Need:")
    result = orch.apply_job_action("dismiss", "done-run")
    assert result["status"] == "cleared"
    assert store.get_run("done-run")["status"] == "completed"
    assert not (store.task_metadata("done-task").get("github") or {}).get("attention")
    assert _panel_last_job(store, "ch").startswith("Last:")


def test_dismiss_ignores_non_need_jobs(tmp_path: Path):
    orch = _orch(tmp_path)
    store = orch.store
    store.create_task(
        task_id="ok-task",
        workspace_id="ws",
        channel_id="ch",
        intake_text="ok",
    )
    store.create_run(
        run_id="ok-run",
        task_id="ok-task",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.COMPLETED,
    )
    result = orch.apply_job_action("dismiss", "ok-run")
    assert result["status"] == "ignored"
    assert store.get_run("ok-run")["status"] == "completed"
