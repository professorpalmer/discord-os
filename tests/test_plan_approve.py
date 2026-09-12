"""P2.8 Plan-mode Approve / Cancel park seam."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskIntake, TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.actions import job_custom_id
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.orchestration.plan_approve import (
    APPROVED_PLAN_SPOKEN,
    DENIED_PLAN_SPOKEN,
    EXPIRED_PLAN_SPOKEN,
    GATE_KIND_PLAN,
    normalize_plan_status,
    parse_spoken_plan_verb,
    plan_approve_card,
    plan_ready_decision,
)
from agent_discord.orchestration.reactive import (
    ACTIONS_PLAN,
    PLAN_BUTTONS,
    action_labels,
    reactive_paint,
)
from agent_discord.orchestration.service import expire_parked_approvals
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def _orch(tmp_path: Path):
    store = SQLiteStore(tmp_path / "plan-approve.sqlite3")
    store.initialize()
    fake = FakeDiscordMCPProvider()
    facade = DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test")
    backend = FakePuppetmasterBackend()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=facade,
        post_progress_to_discord=True,
    )
    return orch, store, fake, backend


def test_plan_ready_decision_fail_closed():
    denied = plan_ready_decision("")
    assert denied.decision == "deny"
    assert denied.reason == "unknown plan"
    denied_status = plan_ready_decision("do the thing", plan_status="totally-novel")
    assert denied_status.decision == "deny"
    assert denied_status.reason == "unknown plan status"
    ok = plan_ready_decision("1. edit cards\n2. flush", plan_status="ready")
    assert ok.decision == "ask"
    assert "edit cards" in ok.plan_text
    assert normalize_plan_status("plan-ready") == "plan_ready"
    assert normalize_plan_status("bogus") is None


def test_plan_approve_card_is_approve_cancel_not_always():
    card = plan_approve_card(
        "run-p1",
        plan_text="Edit backend.py then flush the Discord card.",
        summary="Plan",
    )
    assert card.kind == "PLAN"
    assert card.title == "Approve plan"
    row = card.rows[0]
    labels = [c["label"] for c in row["components"]]
    assert labels == ["Approve", "Cancel"]
    assert "Always allow" not in labels
    ids = [c["custom_id"] for c in row["components"]]
    assert ids == [
        job_custom_id("approve", "run-p1"),
        job_custom_id("cancel", "run-p1"),
    ]
    paint = reactive_paint(awaiting_plan=True)
    assert paint.actions == ACTIONS_PLAN
    assert action_labels(paint.actions) == PLAN_BUTTONS
    assert paint.stage == "Approve plan"


def test_spoken_plan_verbs_no_always():
    assert parse_spoken_plan_verb("Approve") == "approve"
    assert parse_spoken_plan_verb("Allow") == "approve"
    assert parse_spoken_plan_verb("Deny") == "deny"
    assert parse_spoken_plan_verb("Cancel") == "deny"
    assert parse_spoken_plan_verb("always allow") is None
    assert parse_spoken_plan_verb("please approve the plan later") is None


def test_raise_plan_approve_approve_and_cancel(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="review the billing module",
            channel_id="ch",
            workspace_id="ws",
            message_id="plan-1",
        )
    )
    assert receipt.status == TaskStatus.COMPLETED
    denied = orch.raise_plan_approve(receipt.run_id, plan_text="", plan_status="ready")
    assert denied["status"] == "denied"

    parked = orch.raise_plan_approve(
        receipt.run_id,
        plan_text="1. patch routing\n2. add tests",
        summary="Ship plan",
        plan_status="ready",
    )
    assert parked["status"] == "parked"
    assert parked["gate_kind"] == GATE_KIND_PLAN
    meta = store.task_metadata(receipt.task_id)
    assert meta.get("awaiting_gate") is True
    assert meta.get("awaiting_plan") is True
    assert meta.get("gate_kind") == GATE_KIND_PLAN

    # Always is ignored on plan park
    ignored = orch.apply_job_action("always", receipt.run_id)
    assert ignored["status"] == "ignored"
    assert store.task_metadata(receipt.task_id).get("awaiting_gate") is True

    approved = orch.apply_job_action("approve", receipt.run_id)
    assert approved["gate_result"] == "allow"
    assert APPROVED_PLAN_SPOKEN in approved["summary"]
    assert orch.gate_result_for(receipt.run_id)["gate_result"] == "allow"
    meta2 = store.task_metadata(receipt.task_id)
    assert meta2.get("awaiting_gate") is False
    assert meta2.get("plan_approved") is True

    # Fresh park then Cancel → deny
    second = orch.run_task(
        TaskIntake(
            text="review invoices again",
            channel_id="ch",
            workspace_id="ws",
            message_id="plan-2",
        )
    )
    parked2 = orch.raise_plan_approve(
        second.run_id,
        plan_text="Retry with Cancel path.",
        plan_status="ready",
    )
    assert parked2["status"] == "parked"
    cancelled = orch.apply_job_action("cancel", second.run_id)
    assert cancelled["gate_result"] == "deny"
    assert DENIED_PLAN_SPOKEN in cancelled["summary"]
    assert backend.dispatch_count >= 1
    store.close()


def test_raise_plan_approve_unknown_status_fails_closed(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="review something",
            channel_id="ch",
            workspace_id="ws",
            message_id="plan-unk",
        )
    )
    result = orch.raise_plan_approve(
        receipt.run_id,
        plan_text="a real plan",
        plan_status="not-a-real-status",
    )
    assert result["status"] == "denied"
    store.close()


def test_approval_timeout_expires_plan_gate(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="review timeout plan",
            channel_id="ch",
            workspace_id="ws",
            message_id="plan-exp",
        )
    )
    parked = orch.raise_plan_approve(
        receipt.run_id,
        plan_text="Expire me.",
        plan_status="ready",
    )
    assert parked["status"] == "parked"
    store.merge_task_metadata(receipt.task_id, {"parked_at_ms": 1})
    expired = expire_parked_approvals(
        orch,
        now_ms=1 + 21 * 60 * 1000,
        env={"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "20"},
    )
    assert len(expired) == 1
    assert expired[0]["action"] == "expire"
    assert EXPIRED_PLAN_SPOKEN in expired[0]["summary"]
    run = store.get_run(receipt.run_id)
    assert run["status"] == TaskStatus.FAILED.value
    assert EXPIRED_PLAN_SPOKEN in (run.get("summary") or "")
    store.close()


def test_exit_plan_tool_detection():
    from agent_discord.orchestration.plan_approve import (
        is_exit_plan_tool,
        plan_text_from_tool_input,
    )

    assert is_exit_plan_tool("ExitPlanMode")
    assert is_exit_plan_tool("exit_plan_mode")
    assert is_exit_plan_tool("mcp__agent__ExitPlanMode")
    assert not is_exit_plan_tool("Write")
    assert (
        plan_text_from_tool_input({"plan": "1. edit\n2. test"})
        == "1. edit\n2. test"
    )


def test_request_plan_hold_blocks_until_approve(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="plan the billing change",
            channel_id="ch",
            workspace_id="ws",
            message_id="plan-hold-1",
        )
    )
    assert receipt.status == TaskStatus.COMPLETED

    ticks = {"n": 0}

    def sleeper(_s: float) -> None:
        ticks["n"] += 1
        if ticks["n"] == 2:
            orch.apply_job_action("approve", receipt.run_id)

    held = orch.request_plan_hold(
        receipt.run_id,
        plan_text="1. patch routing\n2. add tests",
        summary="Ship",
        timeout_seconds=2.0,
        poll_seconds=0.01,
        sleeper=sleeper,
    )
    assert held["decision"] == "allow"
    assert held["gate_kind"] == GATE_KIND_PLAN
    meta = store.task_metadata(receipt.task_id)
    assert meta.get("plan_approved") is True or meta.get("gate_result") == "allow"


def test_gate_hook_exit_plan_enqueues_plan_kind(tmp_path: Path, monkeypatch):
    from agent_discord.orchestration.gate_hook import (
        build_request,
        list_pending,
        run_hook,
        ensure_run_gate_dir,
        resolve_run_gate_dir,
        complete_request,
        GateHoldResult,
    )

    monkeypatch.setenv("DISCORD_OS_GATE_ROOT", str(tmp_path / "gates"))
    monkeypatch.setenv("DISCORD_OS_RUN_ID", "run-plan-1")
    monkeypatch.setenv("DISCORD_OS_GATE_TIMEOUT_SECONDS", "0.2")
    req = build_request(
        run_id="run-plan-1",
        tool_name="ExitPlanMode",
        tool_input={"plan": "do the thing carefully"},
    )
    assert req.kind == GATE_KIND_PLAN
    assert "do the thing" in req.detail

    run_dir = ensure_run_gate_dir(
        resolve_run_gate_dir(run_id="run-plan-1", env=dict(**__import__("os").environ))
    )

    # Simulate listen draining: write allow so hook unblocks.
    import json
    import io
    import threading

    def resolver():
        import time

        time.sleep(0.05)
        pending = list_pending(run_dir)
        assert pending, "expected plan pending"
        complete_request(
            run_dir,
            GateHoldResult(
                request_id=pending[0].request_id,
                decision="allow",
                reason="allow",
                tool_class="plan",
            ),
        )

    threading.Thread(target=resolver, daemon=True).start()
    stdin = io.StringIO(
        json.dumps(
            {
                "tool_name": "ExitPlanMode",
                "tool_input": {"plan": "do the thing carefully"},
                "run_id": "run-plan-1",
            }
        )
    )
    stdout = io.StringIO()
    code = run_hook(argv=[], stdin=stdin, stdout=stdout, env=dict(**__import__("os").environ))
    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload.get("permissionDecision") in {"allow", "deny"} or payload.get(
        "decision"
    ) in {"allow", "deny"}


def test_plan_ready_without_exit_plan_mode():
    """Plan Approve parks on plan_status / PresentPlan — not ExitPlanMode-only."""

    from agent_discord.orchestration.gate_hook import build_request
    from agent_discord.orchestration.plan_approve import (
        GATE_KIND_PLAN,
        is_exit_plan_tool,
        is_plan_ready_signal,
    )

    assert is_exit_plan_tool("PresentPlan")
    assert is_plan_ready_signal("PresentPlan", {"plan": "1. a\n2. b"})
    assert is_plan_ready_signal(
        "SomeOtherTool",
        {"plan": "1. a\n2. b", "plan_status": "ready"},
    )
    assert not is_plan_ready_signal("Write", {"path": "x"})
    assert not is_plan_ready_signal(
        "Write",
        {"plan": "1. a", "plan_status": "totally-novel"},
    )
    req = build_request(
        run_id="r1",
        tool_name="helper",
        tool_input={"plan": "1. edit cards\n2. flush", "plan_status": "ready"},
    )
    assert req.kind == GATE_KIND_PLAN
    assert "edit cards" in req.detail
