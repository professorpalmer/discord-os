"""Morning summary: once per local day, silent when empty. Fakes only."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agent_discord.contracts import TaskStatus
from agent_discord.discord.layout import iter_component_text
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.panel import handle_gateway_interaction
from agent_discord.host.repo_status import IssueRow, PullRow, RepoStatus
from agent_discord.host.repos import HostRepo
from agent_discord.orchestration.cook_button import cook_token
from agent_discord.orchestration.morning import (
    MorningLine,
    build_morning_lines,
    morning_at,
    morning_card,
    morning_due,
    morning_enabled,
    tick_morning_summary,
)
from agent_discord.persistence.sqlite import SQLiteStore

HOST = "host-ch"
REALM = "realm-ch"
MORNING = datetime(2026, 10, 2, 7, 30)
LATER = datetime(2026, 10, 2, 11, 5)
TOMORROW = datetime(2026, 10, 3, 7, 31)


def _store(tmp_path: Path) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "state.sqlite")
    store.initialize()
    store.set_host_control(HOST, armed=True)
    return store


def _repo(tmp_path: Path) -> HostRepo:
    path = tmp_path / "discord-os"
    (path / ".git").mkdir(parents=True, exist_ok=True)
    return HostRepo(name="discord-os", path=path)


def _red_status() -> RepoStatus:
    return RepoStatus(
        name="discord-os",
        slug="professorpalmer/discord-os",
        default_branch="master",
        default_ci="red",
        default_ci_label="tests",
        open_prs=(PullRow(number=68, title="lakes", author="cary", checks="red"),),
        open_issue_count=4,
        newest_issues=(IssueRow(number=41, title="status card"),),
    )


def _quiet_status() -> RepoStatus:
    return RepoStatus(name="discord-os", default_branch="master", default_ci="green")


def _blob(discord: FakeDiscordMCPProvider) -> str:
    parts = []
    for message in discord.sent:
        parts.append(str(getattr(message, "content", "") or ""))
        meta = getattr(message, "metadata", None) or {}
        if isinstance(meta, dict):
            parts.extend(iter_component_text(meta.get("components")))
            parts.append(json.dumps(meta.get("components") or []))
    return "\n".join(parts)


def _failed_job(store: SQLiteStore, task_id: str, status: TaskStatus) -> None:
    store.create_task(
        task_id=task_id,
        workspace_id="ws",
        channel_id=HOST,
        intake_text="overnight work",
    )
    store.create_run(
        run_id=f"{task_id}-run",
        task_id=task_id,
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=status,
    )
    store.update_run(f"{task_id}-run", status=status, summary="done")


def test_env_knobs():
    assert morning_enabled(env={})
    assert not morning_enabled(env={"DISCORD_OS_MORNING": "0"})
    assert morning_at(env={}) == (7, 30)
    assert morning_at(env={"DISCORD_OS_MORNING_AT": "06:05"}) == (6, 5)
    assert morning_at(env={"DISCORD_OS_MORNING_AT": "nonsense"}) == (7, 30)
    assert morning_at(env={"DISCORD_OS_MORNING_AT": "99:99"}) == (7, 30)


def test_not_due_before_the_hour(tmp_path: Path):
    store = _store(tmp_path)
    assert not morning_due(
        store,
        channel_id=HOST,
        workspace_id="ws",
        env={},
        now=datetime(2026, 10, 2, 6, 59),
    )
    assert morning_due(
        store, channel_id=HOST, workspace_id="ws", env={}, now=MORNING
    )
    store.close()


def test_posts_once_per_local_day(tmp_path: Path):
    store = _store(tmp_path)
    discord = FakeDiscordMCPProvider()
    _failed_job(store, "t-fail", TaskStatus.FAILED)
    kwargs = dict(
        channel_id=HOST,
        workspace_id="ws",
        repos=(_repo(tmp_path),),
        env={},
        repo_status=lambda path, name="": _red_status(),
    )
    first = tick_morning_summary(store, discord, now=MORNING, **kwargs)
    assert first == {"posted": True, "due": True, "lines": 2}

    second = tick_morning_summary(store, discord, now=LATER, **kwargs)
    assert second["posted"] is False
    assert second["due"] is False
    assert len([m for m in discord.sent]) == 1

    third = tick_morning_summary(store, discord, now=TOMORROW, **kwargs)
    assert third["posted"] is True
    assert len(discord.sent) == 2
    store.close()


def test_silent_when_there_is_nothing_to_report(tmp_path: Path):
    store = _store(tmp_path)
    discord = FakeDiscordMCPProvider()
    result = tick_morning_summary(
        store,
        discord,
        channel_id=HOST,
        workspace_id="ws",
        repos=(),
        env={},
        now=MORNING,
        repo_status=None,
    )
    assert result == {"posted": False, "due": True, "lines": 0}
    assert discord.sent == []
    # The quiet morning still burns the day's watermark.
    assert not morning_due(
        store, channel_id=HOST, workspace_id="ws", env={}, now=LATER
    )
    store.close()


def test_quiet_repo_contributes_only_counts(tmp_path: Path):
    store = _store(tmp_path)
    store.merge_binding_metadata("ws", REALM, {"repo": "discord-os"})
    lines = build_morning_lines(
        store,
        channel_id=HOST,
        workspace_id="ws",
        repos=(_repo(tmp_path),),
        repo_status=lambda path, name="": _quiet_status(),
    )
    assert lines == ()
    store.close()


def test_red_ci_line_carries_a_fix_ci_ask(tmp_path: Path):
    store = _store(tmp_path)
    store.merge_binding_metadata("ws", REALM, {"repo": "discord-os"})
    lines = build_morning_lines(
        store,
        channel_id=HOST,
        workspace_id="ws",
        repos=(_repo(tmp_path),),
        repo_status=lambda path, name="": _red_status(),
    )
    texts = [line.text for line in lines]
    assert texts[0] == "CI red on discord-os (master)"
    assert texts[1] == "discord-os: PR #68 checks red"
    assert texts[2] == "discord-os: 1 open PR(s), 4 open issue(s)"
    assert "Fix CI on discord-os" in lines[0].ask
    assert "the master branch is red" in lines[0].ask
    assert "PR #68 is red" in lines[1].ask
    assert lines[2].ask == ""
    store.close()


def test_card_is_capped_at_five_lines():
    lines = tuple(MorningLine(text=f"line {n}") for n in range(8))
    card = morning_card(lines[:5], workspace_id="ws")
    assert card.description.count("\n") == 4
    assert card.rows == ()


def test_morning_cook_button_is_operator_only_and_lands_in_jobpool(tmp_path: Path):
    store = _store(tmp_path)
    store.merge_binding_metadata("ws", REALM, {"repo": "discord-os"})
    discord = FakeDiscordMCPProvider()
    tick_morning_summary(
        store,
        discord,
        channel_id=HOST,
        workspace_id="ws",
        repos=(_repo(tmp_path),),
        env={},
        now=MORNING,
        repo_status=lambda path, name="": _red_status(),
    )
    blob = _blob(discord)
    assert "Morning · 2026-10-02" in blob
    assert "Cook: CI red on discord-os (master)" in blob

    ask = next(
        line.ask
        for line in build_morning_lines(
            store,
            channel_id=HOST,
            workspace_id="ws",
            repos=(_repo(tmp_path),),
            repo_status=lambda path, name="": _red_status(),
        )
        if line.ask
    )
    from agent_discord.orchestration.cook_button import cook_custom_id

    custom_id = cook_custom_id("ws", cook_token(ask))
    store.add_operator("owner-1", role="owner")
    asks: list[tuple[str, str]] = []

    denied = handle_gateway_interaction(
        store,
        HOST,
        {
            "id": "ix1",
            "token": "tok",
            "channel_id": HOST,
            "member": {"user": {"id": "stranger"}},
            "data": {"custom_id": custom_id},
        },
        on_ask=lambda text, uid: asks.append((text, uid)),
    )
    assert denied == "denied"
    assert asks == []

    taken = handle_gateway_interaction(
        store,
        HOST,
        {
            "id": "ix2",
            "token": "tok",
            "channel_id": HOST,
            "member": {"user": {"id": "owner-1"}},
            "data": {"custom_id": custom_id},
        },
        on_ask=lambda text, uid: asks.append((text, uid)),
    )
    assert taken == "cook"
    assert asks[0][1] == "owner-1"
    assert "Fix CI on discord-os" in asks[0][0]
    store.close()


def test_disabled_by_env(tmp_path: Path):
    store = _store(tmp_path)
    discord = FakeDiscordMCPProvider()
    result = tick_morning_summary(
        store,
        discord,
        channel_id=HOST,
        workspace_id="ws",
        env={"DISCORD_OS_MORNING": "0"},
        now=MORNING,
        repo_status=lambda path, name="": _red_status(),
    )
    assert result == {"posted": False, "due": False}
    assert discord.sent == []
    store.close()


def test_disarmed_host_posts_nothing(tmp_path: Path):
    store = _store(tmp_path)
    store.set_host_control(HOST, armed=False)
    discord = FakeDiscordMCPProvider()
    result = tick_morning_summary(
        store,
        discord,
        channel_id=HOST,
        workspace_id="ws",
        env={},
        now=MORNING,
        repo_status=lambda path, name="": _red_status(),
    )
    assert result == {"posted": False, "due": False}
    assert discord.sent == []
    store.close()


def test_listen_runs_the_summary_only_on_the_host_channel(tmp_path: Path):
    from agent_discord.orchestration import listen as listen_mod

    seen: list[str] = []
    original = listen_mod._tick_morning_summary_best_effort

    def spy(orchestrator, discord, store, *, channel_id, workspace_id, env):
        seen.append(channel_id)

    listen_mod._tick_morning_summary_best_effort = spy
    try:
        from agent_discord.discord.facade import DiscordFacade

        store = _store(tmp_path)
        discord = DiscordFacade(FakeDiscordMCPProvider())

        class _Orch:
            store = None
            host_repos = ()

        orch = _Orch()
        orch.store = store
        for channel in (REALM, HOST):
            listen_mod.drain_inbound(
                orch,
                discord,
                channel_id=channel,
                workspace_id="ws",
                workspace=tmp_path,
                host_channel_id=HOST,
            )
        assert seen == [HOST]
        store.close()
    finally:
        listen_mod._tick_morning_summary_best_effort = original


def test_settled_counts_come_from_the_window(tmp_path: Path):
    store = _store(tmp_path)
    _failed_job(store, "t-ok", TaskStatus.COMPLETED)
    _failed_job(store, "t-bad", TaskStatus.FAILED)
    counts = store.count_settled_since(hours=16.0)
    assert counts == {"completed": 1, "failed": 1}
    store.close()
