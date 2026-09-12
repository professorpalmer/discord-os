"""P1.4 Per-tool / AskUserQuestion gate seam."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskIntake, TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.actions import job_custom_id
from agent_discord.host.panel import handle_gateway_interaction
from agent_discord.orchestration.ask_gate import (
    AskOption,
    ask_action_from_custom_id,
    ask_custom_id,
    ask_user_question_card,
    normalize_tool_class,
    parse_spoken_gate_verb,
    tool_class_decision,
    tool_gate_card,
)
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.orchestration.service import (
    clear_write_session_allows,
    set_tool_class_session_allow,
    set_write_gate,
    tool_class_session_allows,
)
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def _orch(tmp_path: Path):
    store = SQLiteStore(tmp_path / "ask-gate.sqlite3")
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


def test_normalize_tool_class_aliases_and_unknown_fail_closed():
    assert normalize_tool_class("Bash") == "shell"
    assert normalize_tool_class("Write") == "write"
    assert normalize_tool_class("AskUserQuestion") == "ask"
    assert normalize_tool_class("mcp__fs__write") is None or normalize_tool_class(
        "mcp__fs__write"
    ) in {None, "write"}
    assert normalize_tool_class("totally-novel-tool") is None


def test_tool_class_decision_fail_closed_and_session_always(tmp_path: Path):
    store = SQLiteStore(tmp_path / "dec.sqlite3")
    store.initialize()
    set_write_gate(store, True)
    denied = tool_class_decision(store, "nope-tool", channel_id="ch", thread_id="th")
    assert denied.decision == "deny"
    assert denied.reason == "unknown tool class"
    ask = tool_class_decision(store, "shell", channel_id="ch", thread_id="th")
    assert ask.decision == "ask"
    set_tool_class_session_allow(store, "shell", "th", ttl_seconds=120)
    assert tool_class_session_allows(store, "shell", "th")
    allowed = tool_class_decision(store, "Bash", channel_id="ch", thread_id="th")
    assert allowed.decision == "allow"
    clear_write_session_allows(store)
    assert not tool_class_session_allows(store, "shell", "th")
    store.close()


def test_tool_gate_card_buttons_are_discode_style():
    card = tool_gate_card("run-g1", tool_class="shell", detail="rm -rf /tmp/x")
    assert card.kind == "GATE"
    assert "shell" in card.title.lower() or "shell" in card.description.lower()
    row = card.rows[0]
    labels = [c["label"] for c in row["components"]]
    assert labels == ["Allow", "Always allow", "Deny"]
    ids = [c["custom_id"] for c in row["components"]]
    assert ids[0] == job_custom_id("approve", "run-g1")


def test_ask_user_question_card_and_custom_ids():
    card = ask_user_question_card(
        "run-a1",
        question="Ship the patch?",
        options=[AskOption("Yes", "Ship now"), "Later", {"label": "No"}],
    )
    assert card.kind == "ASK"
    row = card.rows[0]
    ids = [c["custom_id"] for c in row["components"]]
    assert ask_custom_id("run-a1", 0) in ids
    assert job_custom_id("deny", "run-a1") in ids
    parsed = ask_action_from_custom_id(ask_custom_id("run-a1", 1))
    assert parsed is not None
    assert parsed.run_id == "run-a1"
    assert parsed.option_index == 1


def test_raise_tool_gate_allow_always_deny(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    # Analyze path so we have a live run without write-gate park
    set_write_gate(store, False)
    receipt = orch.run_task(
        TaskIntake(
            text="review the billing module",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-tool-1",
        )
    )
    assert receipt.status == TaskStatus.COMPLETED
    set_write_gate(store, True)
    parked = orch.raise_tool_gate(
        receipt.run_id, tool_class="shell", detail="pytest -q"
    )
    assert parked["status"] == "parked"
    assert parked["gate_class"] == "shell"
    meta = store.task_metadata(receipt.task_id)
    assert meta.get("awaiting_gate") is True
    assert meta.get("awaiting_approval") is True
    denied = orch.apply_job_action("deny", receipt.run_id)
    assert denied["gate_result"] == "deny"
    assert "Denied" in denied["summary"]
    assert orch.gate_result_for(receipt.run_id)["gate_result"] == "deny"

    # Always allow path
    second = orch.run_task(
        TaskIntake(
            text="review invoices again",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-tool-2",
            thread_id=next(iter(fake.threads)) if fake.threads else None,
        )
    )
    thread_id = str(store.get_task(second.task_id).get("thread_id") or "")
    parked2 = orch.raise_tool_gate(second.run_id, tool_class="git", detail="gh pr create")
    assert parked2["status"] == "parked"
    always = orch.apply_job_action("always", second.run_id)
    assert always["gate_result"] == "always"
    assert tool_class_session_allows(store, "git", thread_id) or tool_class_session_allows(
        store, "git", "ch"
    )
    decision = tool_class_decision(
        store, "git", channel_id="ch", thread_id=thread_id
    )
    assert decision.decision == "allow"
    store.close()


def test_raise_ask_user_option_and_spoken_verbs(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="review the auth flow",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-q-1",
        )
    )
    parked = orch.raise_ask_user(
        receipt.run_id,
        question="Which path?",
        options=["A", "B"],
    )
    assert parked["status"] == "parked"
    assert parse_spoken_gate_verb("Allow") == "approve"
    assert parse_spoken_gate_verb("always allow") == "always"
    assert parse_spoken_gate_verb("Deny") == "deny"
    assert parse_spoken_gate_verb("please allow writes") is None
    answered = orch.apply_job_action("ask", f"{receipt.run_id}#1")
    assert answered["gate_result"] == "allow"
    assert answered["gate_answer"] == "B"
    store.close()


def test_unknown_tool_class_raise_fails_closed(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="review something",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-unk",
        )
    )
    result = orch.raise_tool_gate(receipt.run_id, tool_class="totally-novel")
    assert result["status"] == "denied"
    store.close()


def test_gateway_ask_button_routes_to_on_job(tmp_path: Path):
    store = SQLiteStore(tmp_path / "gw-ask.sqlite3")
    store.initialize()
    seen: list[tuple[str, str]] = []

    def on_job(action: str, run_id: str) -> None:
        seen.append((action, run_id))

    class _Opener:
        def __call__(self, *args, **kwargs):
            class _Resp:
                status = 204

                def read(self):
                    return b""

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return _Resp()

    action = handle_gateway_interaction(
        store,
        "ch",
        {
            "type": 3,
            "id": "ix1",
            "token": "tok",
            "application_id": "app",
            "channel_id": "ch",
            "data": {"custom_id": ask_custom_id("run-ask", 0)},
            "member": {"user": {"id": "u1"}},
        },
        opener=_Opener(),
        on_job=on_job,
    )
    assert action == "ask"
    assert seen == [("ask", "run-ask#0")]
    store.close()


def test_approval_timeout_expires_tool_gate(tmp_path: Path):
    from agent_discord.orchestration.service import expire_parked_approvals

    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="review timeout gate",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-to",
        )
    )
    orch.raise_tool_gate(receipt.run_id, tool_class="shell", detail="ls")
    meta = store.task_metadata(receipt.task_id)
    # Force age past timeout
    store.merge_task_metadata(receipt.task_id, {"parked_at_ms": 1})
    expired = expire_parked_approvals(
        orch, now_ms=10_000_000, env={"DISCORD_OS_APPROVAL_TIMEOUT_MINUTES": "1"}
    )
    assert expired
    assert any(row.get("action") == "expire" for row in expired)
    assert "Expired" in (store.get_run(receipt.run_id).get("summary") or "")
    store.close()
