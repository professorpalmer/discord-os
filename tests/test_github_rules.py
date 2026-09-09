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


REPO = "professorpalmer/discord-os"


def thread_message_blob(message) -> str:
    parts = [str(getattr(message, "content", "") or "")]
    meta = getattr(message, "metadata", None) or {}
    if isinstance(meta, dict):
        parts.extend(iter_component_text(meta.get("components")))
    return "\n".join(parts)


REPO = "professorpalmer/discord-os"


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


def _rule(store: SQLiteStore, *, conclusion: str = "failure", destination: str = "new") -> str:
    return store.add_github_rule(
        prompt="fix the failed check",
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
    parent_before = [m for m in fake.sent if not m.thread_id]
    delivered = admit_github_rules(
        store,
        fake,
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
    snap = _failing_main()
    first = admit_github_rules(store, fake, snapshots=(snap,), refresh_host=False)
    second = admit_github_rules(store, fake, snapshots=(snap,), refresh_host=False)
    assert len(first) == 1
    assert second == []
    jobs = [row for row in store.list_recent_jobs("ch") if row.get("status") == "completed"]
    assert len(store.list_job_pull_requests()) == 1
    assert jobs
    store.close()


def test_bound_pr_does_not_mint_second_job(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-bound.sqlite3")
    store.initialize()
    _rule(store)
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
        model="cursor/grok-4-5",
        adapter_name="grok-4.5",
        status=TaskStatus.COMPLETED,
    )
    store.bind_job_pull_request("t1", repo=REPO, number=88, branch="main")
    fake = FakeDiscordMCPProvider()
    delivered = admit_github_rules(
        store,
        fake,
        snapshots=(_failing_main(),),
        refresh_host=False,
    )
    assert delivered == []
    assert len(store.list_job_pull_requests()) == 1
    assert store.job_for_pull_request(REPO, 88)["task_id"] == "t1"
    store.close()


def test_green_on_main_with_failure_rule_mints_nothing(tmp_path: Path):
    store = SQLiteStore(tmp_path / "rule-green.sqlite3")
    store.initialize()
    _rule(store, conclusion="failure")
    fake = FakeDiscordMCPProvider()
    delivered = admit_github_rules(
        store,
        fake,
        snapshots=(_green_main(),),
        refresh_host=False,
    )
    assert delivered == []
    assert store.list_job_pull_requests() == []
    store.close()


def test_drain_inbound_admits_unbound_rule(tmp_path: Path):
    store = SQLiteStore(tmp_path / "drain-rule.sqlite3")
    store.initialize()
    _rule(store)
    fake = FakeDiscordMCPProvider()
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        discord=DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test"),
        post_progress_to_discord=False,
        host_repos=(),
    )
    orch.github_unbound_snapshots = (_failing_main(),)
    drain_inbound(orch, orch.discord, channel_id="ch", workspace_id="ws", since_ms=0)
    owner = store.job_for_pull_request(REPO, 88)
    assert owner is not None
    code = store.task_job_code(owner["task_id"])
    assert code.startswith("DOS-")
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
