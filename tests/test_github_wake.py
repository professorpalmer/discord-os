"""PR/CI wake into the owning job thread. Fakes only. No live GitHub."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.layout import iter_component_text
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.panel import _job_select_options, _panel_last_job
from agent_discord.orchestration.github_wake import (
    CheckItem,
    PullSnapshot,
    ReviewNote,
    parse_pull_url,
    wake_github_jobs,
)
from agent_discord.orchestration.job_briefing import is_job_code
from agent_discord.orchestration.lineage import resolve_run_id
from agent_discord.orchestration.listen import drain_inbound
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def thread_message_blob(message) -> str:
    parts = [str(getattr(message, "content", "") or "")]
    meta = getattr(message, "metadata", None) or {}
    if isinstance(meta, dict):
        parts.extend(iter_component_text(meta.get("components")))
    return "\n".join(parts)


def _job(store: SQLiteStore, *, task_id: str, thread_id: str, summary: str = "opened a PR") -> None:
    store.create_task(
        task_id=task_id,
        workspace_id="ws",
        channel_id="ch",
        intake_text="ship the patch",
        thread_id=thread_id,
    )
    store.create_run(
        run_id=f"{task_id}-run",
        task_id=task_id,
        model="cursor/grok-4-5",
        adapter_name="grok-4.5",
        status=TaskStatus.COMPLETED,
    )
    store.update_run(f"{task_id}-run", status=TaskStatus.COMPLETED, summary=summary)


def _failing_snapshot(_repo: str, _number: int) -> PullSnapshot:
    return PullSnapshot(
        repo="professorpalmer/discord-os",
        number=12,
        checks=(
            CheckItem(name="tests", status="completed", conclusion="failure"),
        ),
    )


def _green_snapshot(_repo: str, _number: int) -> PullSnapshot:
    return PullSnapshot(
        repo="professorpalmer/discord-os",
        number=12,
        checks=(
            CheckItem(name="tests", status="completed", conclusion="success"),
            CheckItem(name="lint", status="completed", conclusion="success"),
        ),
    )


def _waiting_snapshot(_repo: str, _number: int) -> PullSnapshot:
    return PullSnapshot(
        repo="professorpalmer/discord-os",
        number=12,
        checks=(
            CheckItem(name="tests", status="in_progress"),
            CheckItem(name="lint", status="queued"),
        ),
    )


def _review_snapshot(*, author: str, is_bot: bool, comment_id: str) -> PullSnapshot:
    return PullSnapshot(
        repo="professorpalmer/discord-os",
        number=12,
        checks=(
            CheckItem(name="tests", status="completed", conclusion="success"),
        ),
        reviews=(
            ReviewNote(
                comment_id=comment_id,
                author=author,
                body="please rename this",
                is_bot=is_bot,
            ),
        ),
    )


def test_parse_pull_url():
    assert parse_pull_url("see https://github.com/professorpalmer/discord-os/pull/12") == (
        "professorpalmer/discord-os",
        12,
    )
    assert parse_pull_url("no pr here") is None


def test_failing_check_wakes_job_thread_not_parent(tmp_path: Path):
    store = SQLiteStore(tmp_path / "wake.sqlite3")
    store.initialize()
    _job(store, task_id="t1", thread_id="thread-job")
    store.bind_job_pull_request("t1", repo="professorpalmer/discord-os", number=12)
    fake = FakeDiscordMCPProvider()
    parent_before = [m for m in fake.sent if not m.thread_id]

    delivered = wake_github_jobs(
        store,
        fake,
        snapshotter=_failing_snapshot,
        refresh_host=False,
    )
    assert delivered
    assert any(item["posted"] for item in delivered)
    thread_msgs = [m for m in fake.sent if m.thread_id == "thread-job"]
    parent_after = [m for m in fake.sent if not m.thread_id]
    assert len(thread_msgs) == 1
    assert parent_after == parent_before
    blob = thread_message_blob(thread_msgs[0])
    assert "failed" in blob.lower()
    line = _panel_last_job(store, "ch")
    assert line.startswith("Need:")
    assert "failed" in line.lower()
    store.close()


def test_all_green_clears_need_without_parent_spam(tmp_path: Path):
    store = SQLiteStore(tmp_path / "green.sqlite3")
    store.initialize()
    _job(store, task_id="t1", thread_id="thread-job")
    store.bind_job_pull_request("t1", repo="professorpalmer/discord-os", number=12)
    fake = FakeDiscordMCPProvider()
    wake_github_jobs(store, fake, snapshotter=_failing_snapshot, refresh_host=False)
    fake.sent.clear()
    wake_github_jobs(store, fake, snapshotter=_green_snapshot, refresh_host=False)
    assert _panel_last_job(store, "ch").startswith("Last:")
    assert "Need:" not in _panel_last_job(store, "ch")
    thread_msgs = [m for m in fake.sent if m.thread_id == "thread-job"]
    assert thread_msgs == []
    assert [m for m in fake.sent if not m.thread_id] == []
    store.close()


def test_waiting_checks_are_not_failed(tmp_path: Path):
    store = SQLiteStore(tmp_path / "wait.sqlite3")
    store.initialize()
    _job(store, task_id="t1", thread_id="thread-job")
    store.bind_job_pull_request("t1", repo="professorpalmer/discord-os", number=12)
    fake = FakeDiscordMCPProvider()
    wake_github_jobs(store, fake, snapshotter=_waiting_snapshot, refresh_host=False)
    jobs = store.list_recent_jobs("ch")
    assert jobs[0]["attention"] == "waiting"
    assert jobs[0]["status"] == "completed"
    line = _panel_last_job(store, "ch")
    assert line.startswith("Waiting:")
    assert not line.startswith("Need:")
    assert "failed" not in line
    store.close()


def test_waiting_then_failure_becomes_need(tmp_path: Path):
    store = SQLiteStore(tmp_path / "wait-fail.sqlite3")
    store.initialize()
    _job(store, task_id="t1", thread_id="thread-job")
    store.bind_job_pull_request("t1", repo="professorpalmer/discord-os", number=12)
    fake = FakeDiscordMCPProvider()
    wake_github_jobs(store, fake, snapshotter=_waiting_snapshot, refresh_host=False)
    assert _panel_last_job(store, "ch").startswith("Waiting:")
    wake_github_jobs(store, fake, snapshotter=_failing_snapshot, refresh_host=False)
    assert _panel_last_job(store, "ch").startswith("Need:")
    store.close()


def test_human_review_wakes_bot_does_not(tmp_path: Path):
    store = SQLiteStore(tmp_path / "review.sqlite3")
    store.initialize()
    _job(store, task_id="t1", thread_id="thread-job")
    store.bind_job_pull_request("t1", repo="professorpalmer/discord-os", number=12)
    fake = FakeDiscordMCPProvider()
    wake_github_jobs(
        store,
        fake,
        snapshotter=lambda repo, number: _review_snapshot(
            author="copilot-pull-request-reviewer[bot]",
            is_bot=True,
            comment_id="bot-1",
        ),
        refresh_host=False,
    )
    assert [m for m in fake.sent if m.thread_id == "thread-job"] == []
    assert _panel_last_job(store, "ch").startswith("Last:")
    wake_github_jobs(
        store,
        fake,
        snapshotter=lambda repo, number: _review_snapshot(
            author="cary",
            is_bot=False,
            comment_id="human-1",
        ),
        refresh_host=False,
    )
    thread_msgs = [m for m in fake.sent if m.thread_id == "thread-job"]
    assert len(thread_msgs) == 1
    assert "cary" in thread_message_blob(thread_msgs[0])
    assert _panel_last_job(store, "ch").startswith("Need:")
    store.close()


def test_merged_leaves_waiting(tmp_path: Path):
    store = SQLiteStore(tmp_path / "merge.sqlite3")
    store.initialize()
    _job(store, task_id="t1", thread_id="thread-job")
    store.bind_job_pull_request("t1", repo="professorpalmer/discord-os", number=12)
    fake = FakeDiscordMCPProvider()
    wake_github_jobs(store, fake, snapshotter=_waiting_snapshot, refresh_host=False)
    assert _panel_last_job(store, "ch").startswith("Waiting:")

    def merged(_repo: str, _number: int) -> PullSnapshot:
        return PullSnapshot(
            repo="professorpalmer/discord-os",
            number=12,
            merged=True,
            checks=(CheckItem(name="tests", status="completed", conclusion="success"),),
        )

    wake_github_jobs(store, fake, snapshotter=merged, refresh_host=False)
    line = _panel_last_job(store, "ch")
    assert line.startswith("Last:")
    store.close()


def test_job_codes_are_unique_and_lookupable(tmp_path: Path):
    store = SQLiteStore(tmp_path / "codes.sqlite3")
    store.initialize()
    _job(store, task_id="a", thread_id="thread-a")
    _job(store, task_id="b", thread_id="thread-b")
    code_a = store.task_job_code("a")
    code_b = store.task_job_code("b")
    assert is_job_code(code_a)
    assert is_job_code(code_b)
    assert code_a != code_b
    assert store.get_task_by_job_code(code_a)["task_id"] == "a"
    assert store.get_task_by_job_code(code_a.lower())["thread_id"] == "thread-a"
    run_id = resolve_run_id(store, code_a)
    assert run_id == "a-run"
    line = _panel_last_job(store, "ch")
    assert code_a in line or code_b in line
    options = _job_select_options(store.list_recent_jobs("ch"))
    labels = " ".join(opt["label"] for opt in options)
    assert code_a in labels
    assert code_b in labels
    store.close()


def test_discover_pr_from_summary(tmp_path: Path):
    store = SQLiteStore(tmp_path / "discover.sqlite3")
    store.initialize()
    _job(
        store,
        task_id="t1",
        thread_id="thread-job",
        summary="opened https://github.com/professorpalmer/discord-os/pull/99",
    )
    fake = FakeDiscordMCPProvider()

    def snap(repo: str, number: int) -> PullSnapshot:
        assert repo == "professorpalmer/discord-os"
        assert number == 99
        return PullSnapshot(
            repo=repo,
            number=number,
            checks=(CheckItem(name="tests", status="completed", conclusion="failure"),),
        )

    wake_github_jobs(store, fake, snapshotter=snap, refresh_host=False)
    owner = store.job_for_pull_request("professorpalmer/discord-os", 99)
    assert owner is not None
    assert owner["task_id"] == "t1"
    assert [m for m in fake.sent if m.thread_id == "thread-job"]
    store.close()


def test_drain_inbound_wakes_bound_pr(tmp_path: Path):
    store = SQLiteStore(tmp_path / "drain-wake.sqlite3")
    store.initialize()
    _job(store, task_id="t1", thread_id="thread-job")
    store.bind_job_pull_request("t1", repo="professorpalmer/discord-os", number=12)
    fake = FakeDiscordMCPProvider()
    orch = AgentOrchestrator(
        store=store,
        backend=FakePuppetmasterBackend(),
        discord=DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test"),
        post_progress_to_discord=False,
        host_repos=(),
    )
    orch.github_snapshotter = _failing_snapshot
    drain_inbound(orch, orch.discord, channel_id="ch", workspace_id="ws", since_ms=0)
    thread_msgs = [m for m in fake.sent if m.thread_id == "thread-job"]
    assert len(thread_msgs) == 1
    assert "failed" in thread_message_blob(thread_msgs[0]).lower()
    parent = [m for m in fake.sent if not m.thread_id]
    assert all("Checks failed" not in thread_message_blob(m) for m in parent)
    assert _panel_last_job(store, "ch").startswith("Need:")
    store.close()
