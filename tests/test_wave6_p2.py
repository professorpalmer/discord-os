"""Wave 6 P2 stretch — recovery beat, recipes, Spec Kit tags, ROE escalate, stall."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_discord.contracts import TaskStatus
from agent_discord.discord.errors import ToolInvocationError
from agent_discord.discord.rest import modify_channel
from agent_discord.host.forum_realm import (
    ForumTag,
    build_lifecycle_tag_id_map,
    cache_status_tags_from_forum_payload,
    refresh_status_tags_from_discord,
)
from agent_discord.orchestration.cards import progress_card
from agent_discord.orchestration.recovery_beat import (
    RECOVERY_ACTIONS,
    format_recovery_beat,
    maybe_post_recovery_beat,
)
from agent_discord.orchestration.roe_escalate import (
    escalate_for_deny,
    escalate_for_halt_receipt,
    format_deny_escalate,
    format_halt_escalate,
    is_escalate_copy,
)
from agent_discord.orchestration.stall_signal import (
    format_stall_oneliner,
    should_show_stall,
    stall_opt_in,
    stall_threshold,
)
from agent_discord.orchestration.reactive import (
    ACTIONS_FAILED_DONE,
    FAILED_DONE_BUTTONS,
    action_labels,
    reactive_for_job,
)
from agent_discord.persistence.sqlite import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]


def test_recovery_beat_format_and_post(tmp_path: Path):
    beat = format_recovery_beat(
        diagnostic="boom tool timeout",
        job_code="DOS-10001",
        status="failed",
        peer=True,
    )
    assert "Recovery" in beat
    assert "Diagnostic" in beat
    assert "Retry" in beat and "Dismiss" in beat
    assert "ParaRecover" in beat
    assert RECOVERY_ACTIONS == "failed_done"

    store = SQLiteStore(tmp_path / "r.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t1",
        workspace_id="default",
        channel_id="chan",
        intake_text="live work",
        metadata={"peer_task": True, "handoff_id": "h1", "parent_thread_id": "thr"},
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="openrouter/auto",
        adapter_name="test",
        status=TaskStatus.RUNNING,
    )

    class _Intake:
        channel_id = "chan"
        thread_id = "thr"
        metadata = {"peer_task": True, "handoff_id": "h1", "parent_thread_id": "thr"}

    class _Discord:
        def __init__(self):
            self.msgs = []

        def send_message(self, channel_id, text, thread_id=None):
            self.msgs.append((channel_id, text, thread_id))

    d = _Discord()
    out = maybe_post_recovery_beat(
        store=store,
        discord=d,
        intake=_Intake(),
        task_id="t1",
        run_id="r1",
        status=TaskStatus.FAILED,
        summary="boom",
        job_code="DOS-10001",
        error="timeout",
    )
    assert out and "Diagnostic" in out
    assert d.msgs and "Recovery" in d.msgs[0][1]
    store.close()


def test_failed_live_offers_retry_dismiss():
    paint = reactive_for_job({"status": "failed", "thread_id": "th"})
    assert paint.actions == ACTIONS_FAILED_DONE
    assert action_labels(paint.actions) == FAILED_DONE_BUTTONS
    assert "Retry" in FAILED_DONE_BUTTONS and "Dismiss" in FAILED_DONE_BUTTONS


def test_parameterized_recipe_docs_present():
    text = (ROOT / "docs" / "recipes" / "parameterized.md").read_text(encoding="utf-8")
    assert "inputs" in text.lower()
    assert "channel_id" in text
    assert "YAML" in text
    assert "graham" not in text.lower()
    index = (ROOT / "docs" / "recipes" / "README.md").read_text(encoding="utf-8")
    assert "parameterized.md" in index


def test_lifecycle_tag_map_manual_only_never_create(tmp_path: Path, monkeypatch):
    with pytest.raises(ToolInvocationError, match="available_tags"):
        modify_channel(
            token="x",
            channel_id="1",
            payload={"available_tags": [{"name": "specify"}]},
        )

    tags = (
        ForumTag(tag_id="a", name="specify"),
        ForumTag(tag_id="b", name="implement"),
        ForumTag(tag_id="c", name="running"),
    )
    life = build_lifecycle_tag_id_map(tags)
    assert life.get("specify") == "a"
    assert life.get("implement") == "b"
    assert "running" not in life  # status alias, not lifecycle phase

    store = SQLiteStore(tmp_path / "f.sqlite3")
    store.initialize()
    updates = cache_status_tags_from_forum_payload(
        store,
        workspace_id="default",
        channel_id="forum1",
        payload={
            "type": 15,
            "available_tags": [
                {"id": "t1", "name": "plan"},
                {"id": "t2", "name": "done"},
            ],
        },
    )
    assert updates["lifecycle_tag_ids"].get("plan") == "t1"
    assert updates["status_tag_ids"].get("completed") == "t2"
    assert updates.get("created_available_tags") is None  # cache path has no create flag

    def fake_fetch(*, token, channel_id, opener=None):
        return {
            "id": channel_id,
            "type": 15,
            "available_tags": [
                {"id": "s1", "name": "spec"},
                {"id": "d1", "name": "done"},
            ],
        }

    import agent_discord.discord.rest as rest

    monkeypatch.setattr(rest, "fetch_channel", fake_fetch)
    out = refresh_status_tags_from_discord(
        store, channel_id="forum1", token="tok"
    )
    assert out["created_available_tags"] is False
    assert out["lifecycle_tag_ids"].get("specify") == "s1"
    store.close()


def test_roe_escalate_halt_and_deny_copy():
    halt = format_halt_escalate()
    assert is_escalate_copy(halt)
    assert "Halt" in halt or "halt" in halt.lower()
    assert escalate_for_halt_receipt().startswith("Need:")

    deny = format_deny_escalate(tool="Write", reason="policy")
    assert is_escalate_copy(deny)
    assert "Write" in deny
    wrapped = escalate_for_deny(spoken="Denied. Write was not started.")
    assert wrapped.startswith("Need:")
    assert "ROE escalate" in wrapped
    # Preserve existing Need copy
    keep = escalate_for_deny(spoken="Need: already escalate shaped")
    assert keep.startswith("Need: already")


def test_stall_oneliner_opt_in():
    assert not stall_opt_in({})
    assert stall_opt_in({"DISCORD_OS_STALL_STEERS": "1"})
    assert stall_threshold({"DISCORD_OS_STALL_N": "5"}) == 5
    steers = [
        {"operator_id": "1", "ts": 10.0},
        {"operator_id": "1", "ts": 11.0},
        {"operator_id": "1", "ts": 12.0},
    ]
    assert not should_show_stall(steers, env={})
    assert should_show_stall(
        steers, env={"DISCORD_OS_STALL_STEERS": "1", "DISCORD_OS_STALL_N": "3"}
    )
    line = format_stall_oneliner(steer_count=3, job_code="DOS-9")
    assert "Stall?" in line and "DOS-9" in line
    card = progress_card(
        stage="running",
        message="working",
        run_id="r1",
        stall_line=line,
    )
    assert "Stall?" in card.description


def test_wave6_p2_docs_brand():
    for rel in (
        "docs/co-work/wave6-recovery-beat.md",
        "docs/co-work/wave6-roe-escalate.md",
        "docs/co-work/wave6-stall-signal.md",
        "docs/co-work/wave6-speckit-tags.md",
        "docs/recipes/parameterized.md",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert "graham" not in text
        assert "board" in text or "recipe" in text or "roe" in text or "stall" in text or "spec" in text
