"""A crash inside run_task settles the run instead of leaving it RUNNING."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskIntake, TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.layout import iter_component_text
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.orchestration import jobs
from agent_discord.orchestration.jobs import JobPool
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


class _ExplodingBackend(FakePuppetmasterBackend):
    def stream(self, request):
        self.last_request = request
        yield from ()
        raise RuntimeError("worker pipe broke")

    def dispatch(self, request):  # pragma: no cover - stream path is used
        raise RuntimeError("worker pipe broke")


def _text(message) -> str:
    parts = [str(getattr(message, "content", "") or "")]
    meta = getattr(message, "metadata", None) or {}
    if isinstance(meta, dict):
        parts.extend(iter_component_text(meta.get("components")))
    return "\n".join(parts)


def _orch(tmp_path: Path) -> tuple[AgentOrchestrator, SQLiteStore, FakeDiscordMCPProvider]:
    store = SQLiteStore(tmp_path / "crash.sqlite3")
    store.initialize()
    fake = FakeDiscordMCPProvider()
    orch = AgentOrchestrator(
        store=store,
        backend=_ExplodingBackend(),
        discord=DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test"),
        post_progress_to_discord=True,
        host_repos=(),
    )
    return orch, store, fake


def _intake(text: str = "summarize the repo") -> TaskIntake:
    return TaskIntake(
        text=text,
        channel_id="ch",
        workspace_id="ws",
        metadata={"compute_mode": "analyze"},
    )


def test_crash_settles_run_card_and_thread(tmp_path: Path) -> None:
    """Audit A2: no frozen RUNNING row, no falsely live thread."""

    orch, store, fake = _orch(tmp_path)
    receipt = orch.run_task(_intake())
    assert receipt.status == TaskStatus.FAILED
    assert receipt.run_id and receipt.task_id
    assert "worker pipe broke" in (receipt.error or "")
    row = store.get_run(receipt.run_id)
    assert row["status"] == TaskStatus.FAILED.value
    assert "internal error" in (row["error"] or "")
    assert orch._live_threads == {}
    task = store.get_task(receipt.task_id) or {}
    thread_id = str(task.get("thread_id") or "")
    if thread_id:
        assert thread_id not in jobs._ORIGIN_THREADS
        # A follow-up in that thread is no longer swallowed as a steer.
        assert orch.steer(receipt.run_id, "are you there?") is False
    blob = " ".join(_text(m) for m in fake.sent)
    assert "internal error" in blob, blob
    store.close()


def test_jobpool_receipt_carries_real_run_id(tmp_path: Path) -> None:
    orch, store, _fake = _orch(tmp_path)
    pool = JobPool(max_live=2)
    pool.submit(orch.run_task, _intake(), write_key="")
    (receipt,) = pool.wait()
    assert receipt.status == TaskStatus.FAILED
    assert not receipt.run_id.startswith("job-")
    assert store.get_run(receipt.run_id)["status"] == TaskStatus.FAILED.value
    store.close()


def test_crash_before_run_exists_still_raises(tmp_path: Path) -> None:
    orch, store, _fake = _orch(tmp_path)

    def broken(_requested):
        raise RuntimeError("no model")

    orch.backend.resolve_model = broken  # type: ignore[method-assign]
    try:
        orch.run_task(_intake())
    except RuntimeError as exc:
        assert "no model" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected the pre-run error to propagate")
    store.close()


def test_status_only_update_keeps_usage_and_error(tmp_path: Path) -> None:
    """Audit C2: a later status-only update_run nulled usage_json and error."""

    import json

    store = SQLiteStore(tmp_path / "usage.sqlite3")
    store.initialize()
    store.create_task(task_id="t1", workspace_id="ws", channel_id="ch", intake_text="x")
    store.create_run(run_id="r1", task_id="t1", model="m", adapter_name="a", status=TaskStatus.RUNNING)
    store.update_run(
        "r1",
        status=TaskStatus.FAILED,
        summary="boom",
        error="swarm exited with incomplete tasks",
        usage={"cost_usd": 0.0123, "tokens_in": 900},
    )
    store.update_run("r1", status=TaskStatus.CANCELLED)
    row = store.get_run("r1")
    assert row["status"] == TaskStatus.CANCELLED.value
    assert row["error"] == "swarm exited with incomplete tasks"
    assert json.loads(row["usage_json"])["cost_usd"] == 0.0123
    store.close()
