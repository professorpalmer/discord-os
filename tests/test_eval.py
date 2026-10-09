"""discord-os eval: replay labeled runs read-only and score win/loss/same."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_discord.contracts import ModelNotAllowedError, RunReceipt, TaskStatus
from agent_discord.orchestration.evaluate import (
    EVAL_META_KEY,
    VERDICT_LOSS,
    VERDICT_SAME,
    VERDICT_WIN,
    assert_pin_allowed,
    eval_intake,
    is_eval_metadata,
    plan_eval,
    replay_passes,
    run_eval,
    verdict,
)
from agent_discord.orchestration.outcomes import LABEL_BAD, LABEL_GOOD, LABEL_PARTIAL
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend

ANSWER = "Discord OS runs the worker on this Mac and cards the result in the thread."
# Long enough that the fake backend's echo clears the rubric's summary floor.
LONG_ASK = "explain how Discord OS runs one job end to end on this Mac"


def _labeled(
    store: SQLiteStore,
    *,
    run_id: str,
    label: str,
    text: str = "what is Discord OS?",
) -> None:
    task_id = f"t-{run_id}"
    store.create_task(
        task_id=task_id,
        workspace_id="ws",
        channel_id="ch",
        intake_text=text,
    )
    store.create_run(
        run_id=run_id,
        task_id=task_id,
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.RUNNING,
    )
    store.update_run(run_id, status=TaskStatus.COMPLETED, summary="old answer")
    store.record_run_outcome(run_id=run_id, operator_id="op-1", label=label)


def _receipt(status: TaskStatus = TaskStatus.COMPLETED, summary: str = ANSWER) -> RunReceipt:
    return RunReceipt(task_id="t", run_id="replay-1", status=status, summary=summary)


def test_rubric_pass_needs_completed_and_a_real_summary():
    assert replay_passes(_receipt()) is True
    assert replay_passes(_receipt(status=TaskStatus.FAILED)) is False
    assert replay_passes(_receipt(summary="short")) is False
    assert replay_passes(_receipt(summary="Need: I could not reach the checkout here")) is False
    assert replay_passes(None) is False


def test_verdict_table():
    assert verdict(LABEL_GOOD, passed=True) == VERDICT_SAME
    assert verdict(LABEL_GOOD, passed=False) == VERDICT_LOSS
    assert verdict(LABEL_BAD, passed=True) == VERDICT_WIN
    assert verdict(LABEL_BAD, passed=False) == VERDICT_SAME
    assert verdict(LABEL_PARTIAL, passed=True) == VERDICT_WIN
    assert verdict(LABEL_PARTIAL, passed=False) == VERDICT_LOSS


def test_disallowed_pin_fails_closed():
    assert assert_pin_allowed("") == "openrouter/auto"
    assert assert_pin_allowed("openrouter/auto") == "openrouter/auto"
    try:
        assert_pin_allowed("anthropic/claude-opus-5")
    except ModelNotAllowedError as exc:
        assert "allowlist" in str(exc)
    else:
        raise AssertionError("pin outside the allowlist must fail closed")


def test_report_shape_and_totals(tmp_path: Path):
    store = SQLiteStore(tmp_path / "eval.sqlite3")
    store.initialize()
    _labeled(store, run_id="r-good", label=LABEL_GOOD)
    _labeled(store, run_id="r-bad", label=LABEL_BAD)

    seen = []

    def dispatch(intake):
        seen.append(intake)
        return _receipt()

    report = run_eval(store, dispatch=dispatch, limit=5)
    assert report["pin"] == "openrouter/auto"
    assert report["replayed"] == 2
    assert report["totals"] == {VERDICT_WIN: 1, VERDICT_LOSS: 0, VERDICT_SAME: 1}
    assert "No LLM judge" in report["rubric"]
    by_label = {row["label"]: row for row in report["results"]}
    assert by_label[LABEL_BAD]["verdict"] == VERDICT_WIN
    assert by_label[LABEL_GOOD]["verdict"] == VERDICT_SAME
    assert by_label[LABEL_GOOD]["replay_summary_chars"] == len(ANSWER)
    assert all(row["error"] is None for row in report["results"])
    # Every replay carried eval metadata and asked the labeled run's text again.
    assert [is_eval_metadata(intake.metadata) for intake in seen] == [True, True]
    assert {intake.text for intake in seen} == {"what is Discord OS?"}
    store.close()


def test_eval_intake_is_marked_and_has_no_thread():
    intake = eval_intake(
        {"run_id": "r1", "label": LABEL_BAD, "intake_text": "ask", "channel_id": "ch"},
        pin="openrouter/auto",
    )
    assert intake.metadata[EVAL_META_KEY] is True
    assert intake.metadata["eval_of"] == "r1"
    assert intake.thread_id is None
    assert intake.message_id is None


def test_eval_replay_is_analyze_even_when_the_ask_said_implement(tmp_path: Path):
    from agent_discord.orchestration.jobs import _needs_write_lock
    from agent_discord.orchestration.orchestrator import AgentOrchestrator
    from agent_discord.orchestration.routing import MODE_ANALYZE

    store = SQLiteStore(tmp_path / "analyze.sqlite3")
    store.initialize()
    backend = FakePuppetmasterBackend()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=None,
        post_progress_to_discord=False,
    )
    intake = eval_intake(
        {
            "run_id": "r1",
            "label": LABEL_BAD,
            "intake_text": "implement the retry button and add tests",
            "channel_id": "ch",
        },
        pin="openrouter/auto",
    )
    assert _needs_write_lock(intake) is False
    receipt = orch.run_task(intake)
    assert receipt.status == TaskStatus.COMPLETED
    assert backend.last_request is not None
    assert backend.last_request.metadata["compute_mode"] == MODE_ANALYZE
    assert backend.last_request.metadata["workers"] == 0
    store.close()


def _cli(monkeypatch, tmp_path: Path):
    from agent_discord import cli as cli_mod

    config = cli_mod.load_config()
    object.__setattr__(config, "database_path", tmp_path / "cli.sqlite3")
    object.__setattr__(config, "workspace", tmp_path / "ws")
    monkeypatch.setattr(cli_mod, "load_config", lambda: config)
    monkeypatch.setattr(cli_mod, "apply_runtime_secrets", lambda cfg: cfg)
    return cli_mod


def _args(**kwargs) -> argparse.Namespace:
    base = {
        "limit": 0,
        "yes": False,
        "pin": "",
        "out": None,
        "json": False,
        "fake": True,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


def test_dry_run_prints_the_plan_and_dispatches_nothing(tmp_path: Path, monkeypatch, capsys):
    cli_mod = _cli(monkeypatch, tmp_path)
    store = SQLiteStore(tmp_path / "cli.sqlite3")
    store.initialize()
    _labeled(store, run_id="r-bad", label=LABEL_BAD)
    store.close()

    assert cli_mod.cmd_eval(_args()) == 0
    text = capsys.readouterr().out
    assert "eval plan: 1 labeled run(s)" in text
    assert "ANALYZE mode" in text
    assert "--limit N --yes" in text

    # --limit without --yes is still a plan.
    assert cli_mod.cmd_eval(_args(limit=5)) == 0
    assert "eval plan:" in capsys.readouterr().out

    store = SQLiteStore(tmp_path / "cli.sqlite3")
    store.initialize()
    assert store.list_labeled_runs() and len(store.list_labeled_runs()) == 1
    # No replay run was created.
    assert len(plan_eval(store)) == 1
    assert store.get_run("r-bad")["status"] == TaskStatus.COMPLETED.value
    store.close()


def test_yes_runs_analyze_only_with_no_discord_posts(tmp_path: Path, monkeypatch, capsys):
    cli_mod = _cli(monkeypatch, tmp_path)
    store = SQLiteStore(tmp_path / "cli.sqlite3")
    store.initialize()
    _labeled(store, run_id="r-bad", label=LABEL_BAD, text=LONG_ASK)
    store.close()

    built = {}
    real = cli_mod.AgentOrchestrator

    def spy(**kwargs):
        built.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(cli_mod, "AgentOrchestrator", spy)
    out_path = tmp_path / "report" / "eval.json"
    assert cli_mod.cmd_eval(_args(limit=2, yes=True, out=out_path)) == 0
    text = capsys.readouterr().out
    assert "win 1" in text
    assert built["discord"] is None
    assert built["post_progress_to_discord"] is False

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["replayed"] == 1
    assert report["results"][0]["verdict"] == VERDICT_WIN
    assert report["results"][0]["replay_run_id"]

    store = SQLiteStore(tmp_path / "cli.sqlite3")
    store.initialize()
    replay_run = store.get_run(report["results"][0]["replay_run_id"])
    meta = store.task_metadata(str(replay_run["task_id"]))
    assert meta[EVAL_META_KEY] is True
    assert meta["eval_of"] == "r-bad"
    assert meta["workers"] == 0
    store.close()


def test_pin_outside_the_allowlist_is_refused_before_any_spend(
    tmp_path: Path, monkeypatch, capsys
):
    cli_mod = _cli(monkeypatch, tmp_path)
    code = cli_mod.cmd_eval(_args(limit=2, yes=True, pin="anthropic/claude-opus-5"))
    captured = capsys.readouterr()
    assert code == 2
    assert "not in the model allowlist" in captured.err
    assert captured.out == ""
