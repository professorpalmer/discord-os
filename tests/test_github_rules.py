"""Unbound GitHub events as job threads. Fakes only. No live GitHub."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.layout import iter_component_text
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.panel import _panel_last_job
from agent_discord.orchestration.github_rules import admit_github_rules
from agent_discord.orchestration.github_wake import CheckItem, PullSnapshot
from agent_discord.orchestration.listen import drain_inbound
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend
from agent_discord.puppetmaster.models import ADAPTER_NAME


REPO = "professorpalmer/discord-os"


def thread_message_blob(message) -> str:
    parts = [str(getattr(message, "content", "") or "")]
    meta = getattr(message, "metadata", None) or {}
    if isinstance(meta, dict):
        parts.extend(iter_component_text(meta.get("components")))
    return "\n".join(parts)


def _orch(store: SQLiteStore, fake: FakeDiscordMCPProvider):
    backend = FakePuppetmasterBackend()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test"),
        post_progress_to_discord=False,
        host_repos=(),
    )
    return orch, backend


def _failing_main() -> PullSnapshot:
    return PullSnapshot(
        repo=REPO,
        number=88,
        branch="main",
        base="main",
        checks=(CheckItem(name="tests", status="completed", conclusion="failure"),),
    )


def _green_main() -> PullSnapshot:
    return PullSnapshot(
        repo=REPO,
        number=88,
        branch="main",
        base="main",
        checks=(CheckItem(name="tests", status="completed", conclusion="success"),),
    )


def _merged_main() -> PullSnapshot:
    return PullSnapshot(
        repo=REPO,
        number=88,
        branch="feat",
        base="main",
        merged=True,
        checks=(CheckItem(name="tests", status="completed", conclusion="success"),),
    )


def _rule(
    store: SQLiteStore,
    *,
    conclusion: str = "failure",
    destination: str = "new",
    prompt: str = "fix the failed check",
) -> str:
    return store.add_github_rule(
        prompt=prompt,
        destination=destination,
        repo=REPO,
        branch="main",
        conclusion=conclusion,
        channel_id="ch",
        workspace_id="ws",
    )


def test_unbound_main_failure_mints_job_thread(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-new.sqlite3")
    store.initialize()
    _rule(store)
    fake = FakeDiscordMCPProvider()
    orch, backend = _orch(store, fake)
    parent_before = [m for m in fake.sent if not m.thread_id]
    delivered = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(_failing_main(),),
        refresh_host=False,
    )
    assert len(delivered) == 1
    job = delivered[0]
    assert job["job_code"].startswith("DOS-")
    assert job["thread_id"]
    owner = store.job_for_pull_request(REPO, 88)
    assert owner is not None
    assert owner["task_id"] == job["task_id"]
    run = store.get_run(job["run_id"])
    assert run is not None
    assert run["adapter_name"] == ADAPTER_NAME
    assert backend.dispatch_count == 1
    assert "fix the failed check" in (backend.last_request.prompt if backend.last_request else "")
    thread_msgs = [m for m in fake.sent if m.thread_id == job["thread_id"]]
    parent_after = [m for m in fake.sent if not m.thread_id]
    assert thread_msgs
    assert "failed" in thread_message_blob(thread_msgs[0]).lower()
    assert not any("Checks failed" in thread_message_blob(m) for m in parent_after)
    assert len(parent_after) > len(parent_before)
    line = _panel_last_job(store, "ch")
    assert line.startswith("Need:")
    assert job["job_code"] in line
    store.close()


def test_same_event_id_mints_one_job(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-once.sqlite3")
    store.initialize()
    _rule(store)
    fake = FakeDiscordMCPProvider()
    orch, backend = _orch(store, fake)
    snap = _failing_main()
    first = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(snap,),
        refresh_host=False,
    )
    second = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(snap,),
        refresh_host=False,
    )
    assert len(first) == 1
    assert second == []
    assert backend.dispatch_count == 1
    assert len(store.list_job_pull_requests()) == 1
    store.close()


def test_bound_pr_does_not_mint_second_job(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-bound.sqlite3")
    store.initialize()
    _rule(store, destination="new")
    store.create_task(
        task_id="t1",
        workspace_id="ws",
        channel_id="ch",
        intake_text="already cooking",
        thread_id="thread-job",
    )
    store.create_run(
        run_id="t1-run",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.COMPLETED,
    )
    store.bind_job_pull_request("t1", repo=REPO, number=88, branch="main")
    fake = FakeDiscordMCPProvider()
    orch, backend = _orch(store, fake)
    delivered = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(_failing_main(),),
        refresh_host=False,
    )
    assert delivered == []
    assert backend.dispatch_count == 0
    assert len(store.list_job_pull_requests()) == 1
    assert store.job_for_pull_request(REPO, 88)["task_id"] == "t1"
    store.close()


def test_single_unbound_is_silent(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-single-unbound.sqlite3")
    store.initialize()
    _rule(store, destination="single")
    fake = FakeDiscordMCPProvider()
    orch, backend = _orch(store, fake)
    delivered = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(_failing_main(),),
        refresh_host=False,
    )
    assert delivered == []
    assert backend.dispatch_count == 0
    assert store.list_job_pull_requests() == []
    store.close()


def test_single_enqueues_prompt_on_bound_job(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-single.sqlite3")
    store.initialize()
    _rule(store, destination="single")
    store.create_task(
        task_id="t1",
        workspace_id="ws",
        channel_id="ch",
        intake_text="already cooking",
        thread_id="thread-job",
    )
    store.create_run(
        run_id="t1-run",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.COMPLETED,
    )
    store.bind_job_pull_request("t1", repo=REPO, number=88, branch="main")
    fake = FakeDiscordMCPProvider()
    orch, backend = _orch(store, fake)
    delivered = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(_failing_main(),),
        refresh_host=False,
    )
    assert len(delivered) == 1
    assert delivered[0]["steered"] is False
    assert backend.dispatch_count == 1
    assert "fix the failed check" in (backend.last_request.prompt if backend.last_request else "")
    assert store.job_for_pull_request(REPO, 88)["task_id"] == "t1"
    follow = store.get_run(delivered[0]["run_id"])
    assert follow is not None
    assert follow["adapter_name"] == ADAPTER_NAME
    store.close()


def test_single_steers_live_bound_job(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-steer.sqlite3")
    store.initialize()
    _rule(store, destination="single")
    store.create_task(
        task_id="t1",
        workspace_id="ws",
        channel_id="ch",
        intake_text="already cooking",
        thread_id="thread-job",
    )
    store.create_run(
        run_id="t1-run",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.RUNNING,
    )
    store.bind_job_pull_request("t1", repo=REPO, number=88, branch="main")
    fake = FakeDiscordMCPProvider()
    orch, backend = _orch(store, fake)
    orch._run_status["t1-run"] = TaskStatus.RUNNING
    orch._live_threads["thread-job"] = "t1-run"
    delivered = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(_failing_main(),),
        refresh_host=False,
    )
    assert len(delivered) == 1
    assert delivered[0]["steered"] is True
    assert backend.dispatch_count == 0
    assert orch.steer_count == 1
    store.close()


def test_single_merge_enqueues_follow_up(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-merge.sqlite3")
    store.initialize()
    _rule(store, destination="single", conclusion="merged", prompt="follow up after merge")
    store.create_task(
        task_id="t1",
        workspace_id="ws",
        channel_id="ch",
        intake_text="shipped the patch",
        thread_id="thread-job",
    )
    store.create_run(
        run_id="t1-run",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.COMPLETED,
    )
    store.bind_job_pull_request("t1", repo=REPO, number=88, branch="feat", base="main")
    fake = FakeDiscordMCPProvider()
    orch, backend = _orch(store, fake)
    first = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(_merged_main(),),
        refresh_host=False,
    )
    second = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(_merged_main(),),
        refresh_host=False,
    )
    assert len(first) == 1
    assert second == []
    assert backend.dispatch_count == 1
    assert "follow up after merge" in (backend.last_request.prompt if backend.last_request else "")
    store.close()


def test_green_on_main_with_failure_rule_mints_nothing(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-green.sqlite3")
    store.initialize()
    _rule(store, conclusion="failure")
    fake = FakeDiscordMCPProvider()
    orch, backend = _orch(store, fake)
    delivered = admit_github_rules(
        store,
        orch.discord,
        orchestrator=orch,
        snapshots=(_green_main(),),
        refresh_host=False,
    )
    assert delivered == []
    assert backend.dispatch_count == 0
    assert store.list_job_pull_requests() == []
    store.close()


def test_drain_inbound_admits_unbound_rule(tmp_path: Path):
    store = SQLiteStore(tmp_path / "drain-rule.sqlite3")
    store.initialize()
    _rule(store)
    fake = FakeDiscordMCPProvider()
    orch, backend = _orch(store, fake)
    orch.github_unbound_snapshots = (_failing_main(),)
    drain_inbound(orch, orch.discord, channel_id="ch", workspace_id="ws", since_ms=0)
    owner = store.job_for_pull_request(REPO, 88)
    assert owner is not None
    code = store.task_job_code(owner["task_id"])
    assert code.startswith("DOS-")
    assert backend.dispatch_count == 1
    run = store.get_run(store.latest_run_id_for_task(owner["task_id"]))
    assert run is not None
    assert run["adapter_name"] == ADAPTER_NAME
    assert _panel_last_job(store, "ch").startswith("Need:")
    thread_id = owner.get("thread_id") or ""
    assert thread_id
    thread_msgs = [m for m in fake.sent if m.thread_id == thread_id]
    parent_wake = [
        m
        for m in fake.sent
        if not m.thread_id and "Checks failed" in thread_message_blob(m)
    ]
    assert thread_msgs
    assert parent_wake == []
    store.close()
