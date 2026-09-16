"""Wave 4: board catch-up conflicts, lane relationships, brain lake, meat-proxy cut."""

from __future__ import annotations

from pathlib import Path

from agent_discord.host.add import add_brain
from agent_discord.host.brain import (
    format_brain_prompt_block,
    format_meat_proxy_handoff_preamble,
)
from agent_discord.orchestration.board_catchup import (
    collect_channel_conflicts,
    extract_adr_refs,
    extract_pr_refs,
    format_board_catchup,
    is_board_digest_prompt,
    scan_job_conflicts,
)
from agent_discord.orchestration.job_briefing import lane_relationships
from agent_discord.persistence.sqlite import SQLiteStore


def test_extract_adr_and_pr_refs():
    assert "ADR-003" in extract_adr_refs("see ADR-003 and docs/adr/0007-foo.md")
    assert "ADR-007" in extract_adr_refs("docs/adr/0007-foo.md")
    prs = extract_pr_refs("https://github.com/acme/widgets/pull/42 and acme/widgets#7")
    assert "acme/widgets#42" in prs
    assert "acme/widgets#7" in prs


def test_scan_job_conflicts_shared_adr():
    jobs = [
        {
            "job_code": "DOS-12",
            "status": "running",
            "intake_text": "implement auth per ADR-003",
        },
        {
            "job_code": "DOS-15",
            "status": "pending",
            "intake_text": "billing rewrite — conflicts with ADR-003",
        },
        {
            "job_code": "DOS-99",
            "status": "completed",
            "intake_text": "ADR-003 done already",
        },
    ]
    hits = scan_job_conflicts(jobs)
    assert any(h.shared == "ADR-003" and h.kind == "adr" for h in hits)
    lines = lane_relationships(jobs)
    assert any("ADR-003" in line for line in lines)


def test_is_board_digest_prompt():
    assert is_board_digest_prompt("board catch-up: scan ADR conflicts")
    assert is_board_digest_prompt("digest: overnight board")
    assert not is_board_digest_prompt("run the test suite")


def test_format_board_catchup_includes_conflicts():
    hits = scan_job_conflicts(
        [
            {"job_code": "DOS-1", "status": "running", "intake_text": "ADR-001 a"},
            {"job_code": "DOS-2", "status": "failed", "intake_text": "ADR-001 b"},
        ]
    )
    body = format_board_catchup(
        skipped_labels=["alpha task", "beta task"],
        conflicts=hits,
    )
    assert "skipped_while_disarmed" in body
    assert "ADR-001" in body
    assert "DOS-1" in body and "DOS-2" in body


def test_collect_channel_conflicts_from_store(tmp_path: Path):
    from agent_discord.contracts import TaskStatus

    store = SQLiteStore(tmp_path / "db.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t1",
        workspace_id="default",
        channel_id="ch",
        intake_text="ship feature citing ADR-009",
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="m",
        adapter_name="fake",
        status=TaskStatus.RUNNING,
    )
    store.create_task(
        task_id="t2",
        workspace_id="default",
        channel_id="ch",
        intake_text="other lane also ADR-009",
    )
    store.create_run(
        run_id="r2",
        task_id="t2",
        model="m",
        adapter_name="fake",
        status=TaskStatus.PENDING,
    )
    hits = collect_channel_conflicts(store, "ch")
    assert any(h.shared == "ADR-009" for h in hits)
    store.close()


def test_add_brain_and_prompt_block(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(tmp_path / "ws"))
    ws = tmp_path / "ws"
    ws.mkdir()
    docs = tmp_path / "strategy"
    docs.mkdir()
    (docs / "ADR-001.md").write_text("# ADR\n")
    store = SQLiteStore(ws / "db.sqlite3")
    store.initialize()
    payload = add_brain(
        store,
        channel_id="ch-brain",
        dri="alex",
        strategy_docs=str(docs),
        transcripts_channel="tr-1",
        journal=True,
    )
    assert payload["kind"] == "brain"
    assert payload["dri"] == "alex"
    store.set_preference("default", "journal:alex:1", "noted swim lanes", kind="journal")
    binding = store.get_binding("default", "ch-brain")
    block = format_brain_prompt_block(
        binding, store=store, workspace_id="default"
    )
    assert "[brain-lake]" in block
    assert "alex" in block
    assert "Strategy docs" in block
    assert "Durable Objects" in block
    preamble = format_meat_proxy_handoff_preamble(
        store,
        workspace_id="default",
        channel_id="ch-brain",
        from_id="111",
        to_id="222",
        peer_prompt="finish the tests",
    )
    assert "meat-proxy-cut" in preamble
    assert "finish the tests" in preamble
    assert "ROE" in preamble
    store.close()
