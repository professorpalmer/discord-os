"""Parallel job pool: two asks cook at once."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from agent_discord.contracts import DiscordMessage, RunReceipt, TaskIntake, TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.repos import HostRepo
from agent_discord.orchestration.jobs import JobPool
from agent_discord.orchestration.listen import drain_inbound
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


class _SlowBackend(FakePuppetmasterBackend):
    def __init__(self, hold: float = 0.15) -> None:
        super().__init__()
        self.hold = hold
        self.started: list[float] = []
        self.ended: list[float] = []
        self._gate = threading.Lock()

    def dispatch(self, request):  # type: ignore[override]
        with self._gate:
            self.started.append(time.monotonic())
        time.sleep(self.hold)
        with self._gate:
            self.ended.append(time.monotonic())
        return super().dispatch(request)


def assert_dispatches_overlapped(backend: _SlowBackend) -> None:
    assert len(backend.started) == 2
    assert len(backend.ended) == 2
    assert max(backend.started) < min(backend.ended)


def test_job_pool_runs_two_asks_in_parallel(tmp_path: Path):
    store = SQLiteStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    backend = _SlowBackend(hold=0.25)
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        post_progress_to_discord=False,
        host_repos=(),
    )
    pool = JobPool()
    started = time.monotonic()
    pool.submit(
        orch.run_task,
        TaskIntake(text="what is Discord OS?", channel_id="pm", workspace_id="ws"),
    )
    pool.submit(
        orch.run_task,
        TaskIntake(text="what is dugout?", channel_id="dugout", workspace_id="ws"),
    )
    receipts = pool.wait(timeout=3.0)
    elapsed = time.monotonic() - started
    assert len(receipts) == 2
    assert all(item.status == TaskStatus.COMPLETED for item in receipts)
    assert len(backend.started) == 2
    assert elapsed < backend.hold * 1.8
    store.close()


def test_implement_on_same_realm_serializes(tmp_path: Path):
    store = SQLiteStore(tmp_path / "write.sqlite3")
    store.initialize()
    backend = _SlowBackend(hold=0.08)
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        post_progress_to_discord=False,
        host_repos=(),
    )
    pool = JobPool()
    pool.submit(
        orch.run_task,
        TaskIntake(text="implement login timeout", channel_id="pm", workspace_id="ws"),
        write_key="/repo/puppetmaster",
    )
    pool.submit(
        orch.run_task,
        TaskIntake(text="implement second patch", channel_id="pm", workspace_id="ws"),
        write_key="/repo/puppetmaster",
    )
    receipts = pool.wait(timeout=3.0)
    assert len(receipts) == 2
    assert abs(backend.started[1] - backend.started[0]) >= 0.07
    store.close()


def test_drain_with_pool_returns_while_jobs_run(tmp_path: Path):
    store = SQLiteStore(tmp_path / "drain.sqlite3")
    store.initialize()
    backend = _SlowBackend(hold=0.2)
    fake = FakeDiscordMCPProvider()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test"),
        post_progress_to_discord=False,
        host_repos=(),
    )
    store.set_host_control("ch", armed=True)
    fake.inbox.extend(
        [
            DiscordMessage(
                channel_id="ch",
                content="what is Discord OS?",
                message_id="101",
                author_id="human-1",
            ),
            DiscordMessage(
                channel_id="ch",
                content="what is a receipt?",
                message_id="102",
                author_id="human-1",
            ),
        ]
    )
    pool = JobPool()
    started = time.monotonic()
    immediate = list(
        drain_inbound(
            orch,
            orch.discord,
            channel_id="ch",
            workspace_id="ws",
            since_ms=0,
            job_pool=pool,
        )
    )
    assert immediate == []
    assert pool.live_count() == 2
    assert time.monotonic() - started < 0.15
    receipts = pool.wait(timeout=3.0)
    assert len(receipts) == 2
    store.close()


def test_job_pool_surfaces_a_crashed_runner():
    pool = JobPool()

    def boom(intake: TaskIntake):
        raise RuntimeError("backend died")

    pool.submit(boom, TaskIntake(text="x", channel_id="ch", workspace_id="ws"))
    receipts = pool.wait(timeout=2.0)
    assert len(receipts) == 1
    assert receipts[0].status == TaskStatus.FAILED
    assert "backend died" in (receipts[0].error or "")


def test_fail_stale_runs(tmp_path: Path):
    store = SQLiteStore(tmp_path / "stale.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t1",
        workspace_id="ws",
        channel_id="ch",
        intake_text="left hanging",
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.RUNNING,
    )
    assert store.fail_stale_runs() == 1
    assert store.get_run("r1")["status"] == "failed"
    store.close()


def test_drain_serializes_implement_on_shared_cwd(tmp_path: Path):
    repo = tmp_path / "shared"
    repo.mkdir()
    (repo / ".git").mkdir()
    store = SQLiteStore(tmp_path / "shared-cwd.sqlite3")
    store.initialize()
    store.merge_binding_metadata("ws", "ch-a", {"repo": "shared", "cwd": str(repo)})
    store.merge_binding_metadata("ws", "ch-b", {"repo": "shared", "cwd": str(repo)})
    store.set_host_control("ch-a", armed=True)
    store.set_host_control("ch-b", armed=True)
    backend = _SlowBackend(hold=0.08)
    fake = FakeDiscordMCPProvider()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test"),
        post_progress_to_discord=False,
        host_repos=(HostRepo(name="shared", path=repo, aliases=("shared",)),),
    )
    fake.inbox.extend(
        [
            DiscordMessage(
                channel_id="ch-a",
                content="implement login timeout",
                message_id="401",
                author_id="human-1",
            ),
            DiscordMessage(
                channel_id="ch-b",
                content="implement logout path",
                message_id="402",
                author_id="human-1",
            ),
        ]
    )
    pool = JobPool()
    drain_inbound(
        orch, orch.discord, channel_id="ch-a", workspace_id="ws", since_ms=0, job_pool=pool
    )
    drain_inbound(
        orch, orch.discord, channel_id="ch-b", workspace_id="ws", since_ms=0, job_pool=pool
    )
    receipts = pool.wait(timeout=3.0)
    assert len(receipts) == 2
    assert abs(backend.started[1] - backend.started[0]) >= 0.07
    store.close()


def test_job_pool_exposes_live_thread_ids():
    pool = JobPool()
    gate = threading.Event()

    def runner(intake: TaskIntake) -> RunReceipt:
        gate.wait(timeout=2.0)
        return RunReceipt(
            task_id="t",
            run_id="r",
            status=TaskStatus.COMPLETED,
            summary="ok",
        )

    pool.submit(
        runner,
        TaskIntake(
            text="what is Discord OS?",
            channel_id="ch",
            workspace_id="ws",
            thread_id="job-thread",
        ),
    )
    assert pool.live_thread_ids() == ("job-thread",)
    gate.set()
    receipts = pool.wait(timeout=2.0)
    assert len(receipts) == 1
    assert pool.live_thread_ids() == ()
