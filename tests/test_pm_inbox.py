"""Puppetmaster job inbox. Fakes only.

The Puppetmaster CLI is a shell script in tmp_path that prints canned JSON and
logs its argv. The real CLI is never run.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from agent_discord.contracts import DiscordMessage
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.layout import iter_component_text
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.add import add_pm_inbox
from agent_discord.orchestration import pm_inbox as pm
from agent_discord.persistence.sqlite import SQLiteStore

INBOX = "inbox-chan"


class _Fixture:
    """A fake PM CLI plus the state dirs it answers for."""

    def __init__(self, tmp_path: Path, *, broken: bool = False) -> None:
        self.root = tmp_path
        self.home = tmp_path / "home"
        self.fixtures = tmp_path / "pmjson"
        self.fixtures.mkdir(parents=True, exist_ok=True)
        self.log = tmp_path / "pm-calls.log"
        self.projects = (
            self.home
            / "Library"
            / "Application Support"
            / "puppetmaster"
            / "projects"
        )
        self.other = self.projects / "marionette-abc"
        self.mine = self.projects / "discord-os-own"
        for path in (self.other, self.mine):
            path.mkdir(parents=True, exist_ok=True)
        self.cli = tmp_path / "fake-puppetmaster"
        self.cli.write_text(
            _BROKEN_CLI if broken else _FAKE_CLI.format(
                log=self.log, fixtures=self.fixtures
            ),
            encoding="utf-8",
        )
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IEXEC)

    @property
    def env(self) -> dict[str, str]:
        return {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PUPPETMASTER_STATE_DIR": str(self.mine),
        }

    def summaries(self, state_dir: Path, items: list[dict]) -> None:
        payload = {"items": items, "outcome": "ok", "revision": 1}
        name = f"summaries-{state_dir.name}.json"
        (self.fixtures / name).write_text(json.dumps(payload), encoding="utf-8")

    def status(self, job_id: str, job: dict) -> None:
        (self.fixtures / f"status-{job_id}.json").write_text(
            json.dumps({"job": job, "tasks": []}), encoding="utf-8"
        )

    def calls(self) -> list[str]:
        if not self.log.is_file():
            return []
        return [
            line for line in self.log.read_text(encoding="utf-8").splitlines() if line
        ]


_FAKE_CLI = """#!/bin/sh
printf '%s\\n' "$*" >> "{log}"
STATE=""
if [ "$1" = "--state-dir" ]; then
  STATE="$2"
  shift 2
fi
case "$1" in
  job-summaries)
    F="{fixtures}/summaries-$(basename "$STATE").json"
    if [ -f "$F" ]; then cat "$F"; fi
    exit 0
    ;;
  status)
    F="{fixtures}/status-$2.json"
    if [ -f "$F" ]; then cat "$F"; fi
    exit 0
    ;;
esac
exit 0
"""

_BROKEN_CLI = """#!/bin/sh
echo 'not json at all'
exit 3
"""


def _summary(job_id: str, **over) -> dict:
    item = {
        "id": job_id,
        "kind": "job",
        "status": "running",
        "revision": 4,
        "task_count": 2,
        "goal_preview": "ship the agentic lane",
        "goal_preview_truncated": False,
        "delivery": "unverified",
    }
    item.update(over)
    return item


def _store(tmp_path: Path) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.initialize()
    return store


def _enable(store: SQLiteStore, *, now_ms: int = 1_000_000) -> None:
    pm.enable_pm_inbox(store, INBOX, now_ms=now_ms)


def _patch_cli(monkeypatch, fixture: _Fixture) -> None:
    monkeypatch.setattr(pm, "resolve_puppetmaster_cli", lambda *_a, **_k: str(fixture.cli))


def _card_text(message: DiscordMessage) -> str:
    parts = [str(getattr(message, "content", "") or "")]
    meta = getattr(message, "metadata", None) or {}
    if isinstance(meta, dict):
        parts.extend(iter_component_text(meta.get("components")))
    return "\n".join(parts)


def _custom_ids(message: DiscordMessage) -> list[str]:
    meta = getattr(message, "metadata", None) or {}
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("custom_id"):
                found.append(str(node["custom_id"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(meta.get("components"))
    return found


# --- opt-in ---------------------------------------------------------------


def test_inbox_is_off_until_a_channel_is_named(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    fixture.summaries(fixture.other, [_summary("job_a")])
    provider = FakeDiscordMCPProvider()
    discord = DiscordFacade(provider)

    assert pm.pm_inbox_enabled(store, env=fixture.env) is False
    assert pm.tick_pm_inbox(discord, store, env=fixture.env, force=True) == []
    assert provider.sent == []
    store.close()


def test_env_var_alone_turns_the_inbox_on(tmp_path: Path) -> None:
    store = _store(tmp_path)
    env = {pm.PM_INBOX_CHANNEL_ENV: "from-env"}
    assert pm.pm_inbox_channel_id(store, env=env) == "from-env"
    store.close()


def test_add_pm_inbox_writes_env_and_records_the_moment(tmp_path: Path) -> None:
    store = _store(tmp_path)
    env_file = tmp_path / ".env"
    payload = add_pm_inbox(store, channel_id=INBOX, env_file=env_file)

    assert payload["kind"] == "pm-inbox"
    assert payload["channel_id"] == INBOX
    assert f"{pm.PM_INBOX_CHANNEL_ENV}={INBOX}" in env_file.read_text(encoding="utf-8")
    assert pm.pm_inbox_channel_id(store, env={}) == INBOX
    assert pm.pm_inbox_enabled_ms(store) == payload["enabled_ms"]
    store.close()


# --- cards ----------------------------------------------------------------


def test_new_job_gets_one_card_in_its_own_thread(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    fixture.summaries(fixture.other, [_summary("job_a")])
    fixture.status(
        "job_a",
        {"id": "job_a", "label": "agentic lane", "status": "running",
         "created_at": "2030-01-01T00:00:00Z"},
    )
    provider = FakeDiscordMCPProvider()
    discord = DiscordFacade(provider)

    touched = pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)

    assert [row["action"] for row in touched if row["job_id"] == "job_a"] == ["posted"]
    cards = [m for m in provider.sent if m.channel_id == INBOX]
    assert len(cards) == 1
    body = _card_text(cards[0])
    assert "agentic lane" in body
    assert "job_a" in body
    row = store.get_pm_inbox_job("job_a")
    assert row["message_id"] == cards[0].message_id
    assert row["thread_id"]
    assert row["status"] == "running"
    store.close()


def test_status_change_edits_the_same_card(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    fixture.summaries(fixture.other, [_summary("job_a")])
    fixture.status(
        "job_a",
        {"id": "job_a", "label": "agentic lane", "created_at": "2030-01-01T00:00:00Z"},
    )
    provider = FakeDiscordMCPProvider()
    discord = DiscordFacade(provider)
    pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)
    message_id = store.get_pm_inbox_job("job_a")["message_id"]

    fixture.summaries(
        fixture.other, [_summary("job_a", status="failed", revision=9)]
    )
    touched = pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)

    assert {row["action"] for row in touched if row["job_id"] == "job_a"} == {"edited"}
    cards = [m for m in provider.sent if m.channel_id == INBOX]
    assert len(cards) == 1, "status change must edit, not post again"
    assert cards[0].message_id == message_id
    assert "failed" in _card_text(cards[0])
    row = store.get_pm_inbox_job("job_a")
    assert (row["status"], row["revision"]) == ("failed", 9)
    # The label survives a repaint without a second status call.
    assert "agentic lane" in _card_text(cards[0])
    store.close()


def test_restart_does_not_repost(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    fixture.summaries(fixture.other, [_summary("job_a")])
    fixture.status("job_a", {"id": "job_a", "created_at": "2030-01-01T00:00:00Z"})
    provider = FakeDiscordMCPProvider()
    pm.tick_pm_inbox(DiscordFacade(provider), store, env=fixture.env, force=True)
    store.close()

    # New process, same SQLite, same unchanged job.
    restarted = SQLiteStore(tmp_path / "db.sqlite3")
    restarted.initialize()
    touched = pm.tick_pm_inbox(
        DiscordFacade(provider), restarted, env=fixture.env, force=True
    )

    assert [row for row in touched if row["job_id"] == "job_a"] == []
    assert len([m for m in provider.sent if m.channel_id == INBOX]) == 1
    restarted.close()


def test_jobs_older_than_the_enable_moment_are_skipped(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store, now_ms=1_900_000_000_000)
    fixture.summaries(fixture.other, [_summary("job_old")])
    fixture.status(
        "job_old", {"id": "job_old", "created_at": "2020-05-05T00:00:00Z"}
    )
    provider = FakeDiscordMCPProvider()

    pm.tick_pm_inbox(DiscordFacade(provider), store, env=fixture.env, force=True)

    assert provider.sent == []
    assert store.get_pm_inbox_job("job_old") is None
    store.close()


def test_own_state_dir_jobs_are_skipped(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    # Only Discord OS's own state dir has jobs; those already have job cards.
    fixture.summaries(fixture.mine, [_summary("job_mine")])
    fixture.status("job_mine", {"id": "job_mine", "created_at": "2030-01-01T00:00:00Z"})
    provider = FakeDiscordMCPProvider()

    assert str(fixture.mine) not in pm.candidate_state_dirs(env=fixture.env)
    pm.tick_pm_inbox(DiscordFacade(provider), store, env=fixture.env, force=True)

    assert provider.sent == []
    assert store.get_pm_inbox_job("job_mine") is None
    store.close()


def test_parked_job_shows_approve_and_reject_but_never_cancel(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    fixture.summaries(fixture.other, [_summary("job_p", status="waiting_approval")])
    fixture.status("job_p", {"id": "job_p", "created_at": "2030-01-01T00:00:00Z"})
    provider = FakeDiscordMCPProvider()

    pm.tick_pm_inbox(DiscordFacade(provider), store, env=fixture.env, force=True)

    card = [m for m in provider.sent if m.channel_id == INBOX][0]
    ids = _custom_ids(card)
    assert pm.pm_inbox_custom_id("approve", "job_p") in ids
    assert pm.pm_inbox_custom_id("reject", "job_p") in ids
    assert not any("cancel" in cid for cid in ids)
    store.close()


def test_running_job_has_no_decision_buttons(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    fixture.summaries(fixture.other, [_summary("job_r", status="running")])
    fixture.status("job_r", {"id": "job_r", "created_at": "2030-01-01T00:00:00Z"})
    provider = FakeDiscordMCPProvider()

    pm.tick_pm_inbox(DiscordFacade(provider), store, env=fixture.env, force=True)

    card = [m for m in provider.sent if m.channel_id == INBOX][0]
    assert not any(cid.startswith(pm.PM_INBOX_ID_PREFIX) for cid in _custom_ids(card))
    store.close()


def test_tick_is_rate_limited(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    fixture.summaries(fixture.other, [])
    provider = FakeDiscordMCPProvider()
    discord = DiscordFacade(provider)

    pm.tick_pm_inbox(discord, store, env=fixture.env, now=1000.0)
    first = len(fixture.calls())
    pm.tick_pm_inbox(discord, store, env=fixture.env, now=1005.0)
    assert len(fixture.calls()) == first, "a second tick 5s later must not poll"

    pm.tick_pm_inbox(discord, store, env=fixture.env, now=1000.0 + 25.0)
    assert len(fixture.calls()) > first
    store.close()


# --- buttons --------------------------------------------------------------


def _click(job_id: str, verb: str, user_id: str) -> dict:
    return {
        "type": 3,
        "id": "ix-1",
        "token": "tok",
        "channel_id": INBOX,
        "data": {"custom_id": pm.pm_inbox_custom_id(verb, job_id)},
        "member": {"user": {"id": user_id}, "roles": []},
    }


def test_approve_button_runs_approve_for_an_operator(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    store.add_operator("op-1")
    store.record_pm_inbox_job(
        "job_p",
        state_dir=str(fixture.other),
        channel_id=INBOX,
        status="waiting_approval",
    )

    outcome = pm.handle_pm_inbox_click(
        store, _click("job_p", "approve", "op-1"), env=fixture.env
    )

    assert outcome == "pm-approve"
    assert any(
        line.startswith("--state-dir") and " approve job_p" in line
        for line in fixture.calls()
    ), fixture.calls()
    store.close()


def test_approve_button_denies_a_non_operator(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    store.add_operator("op-1")
    store.record_pm_inbox_job(
        "job_p", state_dir=str(fixture.other), channel_id=INBOX
    )

    outcome = pm.handle_pm_inbox_click(
        store, _click("job_p", "approve", "someone-else"), env=fixture.env
    )

    assert outcome == "denied"
    assert fixture.calls() == [], "a denied tap must not reach the CLI"
    store.close()


def test_reject_button_runs_reject(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    store.add_operator("op-1")
    store.record_pm_inbox_job(
        "job_p", state_dir=str(fixture.other), channel_id=INBOX
    )

    assert (
        pm.handle_pm_inbox_click(
            store, _click("job_p", "reject", "op-1"), env=fixture.env
        )
        == "pm-reject"
    )
    assert any(" reject job_p" in line for line in fixture.calls())
    store.close()


def test_custom_id_round_trip_and_foreign_ids() -> None:
    parsed = pm.pm_inbox_action_from_custom_id(
        pm.pm_inbox_custom_id("approve", "job_x")
    )
    assert parsed == pm.PmInboxAction(action="approve", job_id="job_x")
    assert pm.pm_inbox_action_from_custom_id("discord-os:job:approve:run-1") is None
    assert pm.pm_inbox_action_from_custom_id("dos:approve:DOS-10001:abcd1234") is None
    # Puppetmaster has no cancel verb, so the inbox refuses to mint one.
    assert pm.pm_inbox_action_from_custom_id(
        pm.pm_inbox_custom_id("cancel", "job_x")
    ) is None


def test_job_button_ids_still_parse_as_job_actions() -> None:
    from agent_discord.host.actions import job_action_from_custom_id

    assert job_action_from_custom_id(pm.pm_inbox_custom_id("approve", "job_x")) is None


# --- steer ----------------------------------------------------------------


def _reply(provider: FakeDiscordMCPProvider, thread_id: str, text: str, *, author: str,
           message_id: str) -> None:
    provider.inbox.append(
        DiscordMessage(
            channel_id=INBOX,
            content=text,
            message_id=message_id,
            thread_id=thread_id,
            author_id=author,
        )
    )


def test_thread_reply_from_an_operator_runs_steer(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    store.add_operator("op-1")
    fixture.summaries(fixture.other, [_summary("job_a")])
    fixture.status("job_a", {"id": "job_a", "created_at": "2030-01-01T00:00:00Z"})
    provider = FakeDiscordMCPProvider()
    discord = DiscordFacade(provider)
    pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)
    thread_id = store.get_pm_inbox_job("job_a")["thread_id"]

    _reply(provider, thread_id, "use the 3.9 floor", author="op-1", message_id="2000")
    pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)

    assert any(
        " steer job_a use the 3.9 floor" in line for line in fixture.calls()
    ), fixture.calls()
    assert store.get_pm_inbox_job("job_a")["steer_after"] == "2000"
    store.close()


def test_the_card_anchors_the_thread_at_creation(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    fixture.summaries(fixture.other, [_summary("job_a")])
    fixture.status("job_a", {"id": "job_a", "created_at": "2030-01-01T00:00:00Z"})
    provider = FakeDiscordMCPProvider()

    pm.tick_pm_inbox(DiscordFacade(provider), store, env=fixture.env, force=True)

    row = store.get_pm_inbox_job("job_a")
    assert row["steer_after"] == row["message_id"]
    store.close()


def test_a_row_without_an_anchor_seeds_instead_of_steering(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    store.add_operator("op-1")
    fixture.summaries(fixture.other, [])
    provider = FakeDiscordMCPProvider()
    # A row with a thread but no anchor: whatever is already in that thread is
    # not a steer queue.
    store.record_pm_inbox_job(
        "job_a",
        state_dir=str(fixture.other),
        channel_id=INBOX,
        thread_id="thread-x",
        message_id="500",
    )
    _reply(provider, "thread-x", "old chatter", author="op-1", message_id="1000")

    pm.tick_pm_inbox(DiscordFacade(provider), store, env=fixture.env, force=True)

    assert not any(" steer " in line for line in fixture.calls())
    assert store.get_pm_inbox_job("job_a")["steer_after"] == "1000"
    store.close()


def test_thread_reply_from_a_non_operator_does_not_steer(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    store.add_operator("op-1")
    fixture.summaries(fixture.other, [_summary("job_a")])
    fixture.status("job_a", {"id": "job_a", "created_at": "2030-01-01T00:00:00Z"})
    provider = FakeDiscordMCPProvider()
    discord = DiscordFacade(provider)
    pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)
    thread_id = store.get_pm_inbox_job("job_a")["thread_id"]

    _reply(provider, thread_id, "drop the tests", author="rando", message_id="2000")
    pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)

    assert not any(" steer " in line for line in fixture.calls())
    store.close()


def test_the_same_reply_steers_once(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    store.add_operator("op-1")
    fixture.summaries(fixture.other, [_summary("job_a")])
    fixture.status("job_a", {"id": "job_a", "created_at": "2030-01-01T00:00:00Z"})
    provider = FakeDiscordMCPProvider()
    discord = DiscordFacade(provider)
    pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)
    thread_id = store.get_pm_inbox_job("job_a")["thread_id"]
    _reply(provider, thread_id, "hold the floor", author="op-1", message_id="2000")

    pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)
    pm.tick_pm_inbox(discord, store, env=fixture.env, force=True)

    steers = [line for line in fixture.calls() if " steer job_a" in line]
    assert len(steers) == 1
    store.close()


# --- failure ---------------------------------------------------------------


def test_cli_failure_never_raises(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path, broken=True)
    _patch_cli(monkeypatch, fixture)
    _enable(store)
    provider = FakeDiscordMCPProvider()

    assert pm.tick_pm_inbox(
        DiscordFacade(provider), store, env=fixture.env, force=True
    ) == []
    assert provider.sent == []
    assert pm.read_pm_jobs(str(fixture.other), env=fixture.env) == ()
    assert (
        pm.run_pm_verb(
            "approve", "job_a", state_dir=str(fixture.other), env=fixture.env
        )
        is False
    )
    store.close()


def test_missing_cli_never_raises(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    fixture = _Fixture(tmp_path)
    monkeypatch.setattr(
        pm, "resolve_puppetmaster_cli", lambda *_a, **_k: str(tmp_path / "nope")
    )
    _enable(store)
    provider = FakeDiscordMCPProvider()

    assert pm.tick_pm_inbox(
        DiscordFacade(provider), store, env=fixture.env, force=True
    ) == []
    store.close()


def test_listen_tick_swallows_inbox_failure(tmp_path: Path, monkeypatch) -> None:
    from agent_discord.orchestration import listen

    def boom(*_a, **_k):
        raise RuntimeError("inbox exploded")

    monkeypatch.setattr(pm, "tick_pm_inbox", boom)
    listen._tick_pm_inbox_best_effort(None, None, env={})


# --- discovery -------------------------------------------------------------


def test_state_dir_override_is_honored(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    elsewhere = tmp_path / "elsewhere" / "pm-state"
    elsewhere.mkdir(parents=True)
    env = dict(fixture.env)
    env[pm.PM_INBOX_STATE_DIRS_ENV] = f"{elsewhere},  "

    dirs = pm.candidate_state_dirs(env=env)

    assert str(elsewhere) in dirs
    assert str(fixture.other) in dirs
    assert str(fixture.mine) not in dirs


def test_cli_parses_add_pm_inbox() -> None:
    from agent_discord.cli import build_parser

    args = build_parser().parse_args(["add", "pm-inbox", "--channel-id", INBOX])

    assert (args.command, args.add_command) == ("add", "pm-inbox")
    assert args.channel_id == INBOX


def test_doctor_reports_the_inbox(tmp_path: Path, monkeypatch) -> None:
    from agent_discord.host.doctor import _check_pm_inbox

    store = _store(tmp_path)
    db = tmp_path / "db.sqlite3"
    monkeypatch.delenv(pm.PM_INBOX_CHANNEL_ENV, raising=False)

    off: list[str] = []
    _check_pm_inbox(db, off)
    assert any(line.startswith("OK pm-inbox off") for line in off), off

    _enable(store)
    store.close()
    on: list[str] = []
    _check_pm_inbox(db, on)
    assert any(f"OK pm-inbox on channel={INBOX}" in line for line in on), on


def test_created_ms_from_detail_shapes() -> None:
    assert pm.created_ms_from_detail({}) is None
    assert pm.created_ms_from_detail({"created_at": "nonsense"}) is None
    naive = pm.created_ms_from_detail({"created_at": "2030-01-01T00:00:00"})
    aware = pm.created_ms_from_detail({"created_at": "2030-01-01T00:00:00Z"})
    assert naive == aware
