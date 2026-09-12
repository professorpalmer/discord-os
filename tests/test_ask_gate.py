"""P1.4 Per-tool / AskUserQuestion gate seam."""

from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

from agent_discord.cli import main
from agent_discord.contracts import TaskIntake, TaskStatus
from agent_discord.orchestration.gate_hook import (
    build_request,
    complete_request,
    drain_gate_queue,
    enqueue_request,
    read_result,
    run_hook,
    wait_for_result,
)
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
        workspace=tmp_path,
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



def test_normalize_agentic_and_read_passthrough(tmp_path: Path):
    assert normalize_tool_class("run_terminal") == "shell"
    assert normalize_tool_class("write_file") == "write"
    assert normalize_tool_class("read_file") == "read"
    store = SQLiteStore(tmp_path / "read.sqlite3")
    store.initialize()
    set_write_gate(store, True)
    allowed = tool_class_decision(store, "read_file", channel_id="ch")
    assert allowed.decision == "allow"
    assert allowed.reason == "read passthrough"
    store.close()


def test_file_queue_timeout_self_denies(tmp_path: Path):
    from agent_discord.orchestration.gate_hook import ensure_run_gate_dir, run_gate_dir

    run_dir = ensure_run_gate_dir(run_gate_dir(tmp_path / "gates", "run-q1"))
    req = build_request(run_id="run-q1", tool_name="shell", tool_input="pytest -q")
    enqueue_request(run_dir, req)
    held = wait_for_result(
        run_dir,
        req.request_id,
        timeout_seconds=0.08,
        poll_seconds=0.01,
        tool_class="shell",
    )
    assert held.decision == "deny"
    assert held.reason == "timeout"
    assert read_result(run_dir, req.request_id).decision == "deny"


def test_hook_cli_always_exits_zero_on_timeout(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DISCORD_OS_GATE_DIR", str(tmp_path / "hook-run"))
    monkeypatch.setenv("DISCORD_OS_RUN_ID", "run-hook")
    monkeypatch.setenv("DISCORD_OS_GATE_TIMEOUT_SECONDS", "0.08")
    stdin = io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
    stdout = io.StringIO()
    code = run_hook([], stdin=stdin, stdout=stdout, env=dict(**{k: str(v) for k, v in {
        "DISCORD_OS_GATE_DIR": tmp_path / "hook-run",
        "DISCORD_OS_RUN_ID": "run-hook",
        "DISCORD_OS_GATE_TIMEOUT_SECONDS": "0.08",
    }.items()}))
    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["permissionDecision"] == "deny"
    assert payload["continue"] is False


def test_hook_cli_unknown_class_denies_exit_zero(tmp_path: Path):
    stdin = io.StringIO(json.dumps({"tool_name": "totally-novel", "run_id": "r1"}))
    stdout = io.StringIO()
    code = run_hook(
        [],
        stdin=stdin,
        stdout=stdout,
        env={"DISCORD_OS_GATE_DIR": str(tmp_path / "u"), "DISCORD_OS_RUN_ID": "r1"},
    )
    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["permissionDecision"] == "deny"


def test_cli_gate_hook_print_attach(capsys):
    assert main(["gate-hook", "--print-attach"]) == 0
    out = capsys.readouterr().out
    assert "DISCORD_OS_GATE_DIR" in out
    assert "discord-os gate-hook" in out
    assert "Cursor" not in out


def test_live_worker_blocks_until_allow(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    backend.tool_hold = lambda rid: orch.request_tool_hold(
        rid, "shell", detail="pytest -q", timeout_seconds=2.0, poll_seconds=0.02
    )
    box: dict = {}

    def cook() -> None:
        box["receipt"] = orch.run_task(
            TaskIntake(
                text="review the billing module",
                channel_id="ch",
                workspace_id="ws",
                message_id="live-hold-1",
            )
        )

    thread = threading.Thread(target=cook)
    thread.start()
    run_id = ""
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if backend.runs:
            run_id = next(iter(backend.runs))
            if orch.gate_result_for(run_id).get("awaiting_gate"):
                break
        time.sleep(0.02)
    assert run_id
    assert orch.gate_result_for(run_id)["awaiting_gate"] is True
    allowed = orch.apply_job_action("approve", run_id)
    assert allowed["gate_result"] == "allow"
    assert allowed.get("gate_live") is True
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert box["receipt"].status == TaskStatus.COMPLETED
    assert backend.last_hold is not None
    assert backend.last_hold["decision"] == "allow"
    store.close()


def test_live_worker_timeout_self_denies(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    backend.tool_hold = lambda rid: orch.request_tool_hold(
        rid, "shell", detail="ls", timeout_seconds=0.2, poll_seconds=0.02
    )
    box: dict = {}

    def cook() -> None:
        box["receipt"] = orch.run_task(
            TaskIntake(
                text="review timeout hold",
                channel_id="ch",
                workspace_id="ws",
                message_id="live-hold-to",
            )
        )

    thread = threading.Thread(target=cook)
    thread.start()
    thread.join(timeout=3.0)
    assert not thread.is_alive()
    assert box["receipt"].status == TaskStatus.FAILED
    assert backend.last_hold is not None
    assert backend.last_hold["decision"] == "deny"
    assert backend.last_hold["reason"] == "timeout"
    store.close()


def test_drain_parks_hook_request_then_writes_result(tmp_path: Path):
    from agent_discord.orchestration.gate_hook import ensure_run_gate_dir, resolve_run_gate_dir

    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="review drain hold",
            channel_id="ch",
            workspace_id="ws",
            message_id="live-drain-1",
        )
    )
    set_write_gate(store, True)
    run_dir = ensure_run_gate_dir(
        resolve_run_gate_dir(run_id=receipt.run_id, workspace=tmp_path, store=store)
    )
    req = build_request(
        run_id=receipt.run_id, tool_name="git", tool_input="gh pr create"
    )
    enqueue_request(run_dir, req)
    parked = drain_gate_queue(orch)
    assert any(row.get("action") == "park" for row in parked)
    assert orch.gate_result_for(receipt.run_id)["awaiting_gate"] is True
    always = orch.apply_job_action("always", receipt.run_id)
    assert always["gate_result"] == "always"
    # Live resolve writes results/ immediately so a blocked hook unblocks
    # without waiting for another listen drain.
    found = read_result(run_dir, req.request_id)
    assert found is not None
    assert found.decision == "always"
    assert drain_gate_queue(orch) == []
    store.close()



def test_drain_timeout_self_denies_unanswered(tmp_path: Path):
    from agent_discord.orchestration.gate_hook import ensure_run_gate_dir, resolve_run_gate_dir

    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="review drain timeout",
            channel_id="ch",
            workspace_id="ws",
            message_id="live-drain-to",
        )
    )
    run_dir = ensure_run_gate_dir(
        resolve_run_gate_dir(run_id=receipt.run_id, workspace=tmp_path, store=store)
    )
    req = build_request(
        run_id=receipt.run_id,
        tool_name="shell",
        tool_input="ls",
        created_at_ms=1,
    )
    enqueue_request(run_dir, req)
    acted = drain_gate_queue(orch, now_ms=10_000_000)
    assert any(row.get("action") == "timeout" for row in acted)
    found = read_result(run_dir, req.request_id)
    assert found is not None
    assert found.decision == "deny"
    store.close()


def test_drain_writes_result_from_gate_metadata(tmp_path: Path):
    from agent_discord.orchestration.gate_hook import ensure_run_gate_dir, resolve_run_gate_dir

    orch, store, fake, backend = _orch(tmp_path)
    receipt = orch.run_task(
        TaskIntake(
            text="review drain meta",
            channel_id="ch",
            workspace_id="ws",
            message_id="live-drain-meta",
        )
    )
    run_dir = ensure_run_gate_dir(
        resolve_run_gate_dir(run_id=receipt.run_id, workspace=tmp_path, store=store)
    )
    req = build_request(run_id=receipt.run_id, tool_name="shell", tool_input="pwd")
    enqueue_request(run_dir, req)
    store.merge_task_metadata(
        receipt.task_id,
        {"gate_result": "allow", "gate_answer": "", "awaiting_gate": False},
    )
    acted = drain_gate_queue(orch)
    assert any(row.get("action") == "resolve" for row in acted)
    found = read_result(run_dir, req.request_id)
    assert found is not None
    assert found.decision == "allow"
    store.close()


def test_attach_gate_env_stamps_inject_pythonpath(tmp_path: Path):
    from agent_discord.orchestration.gate_hook import (
        ENV_INJECT,
        attach_gate_env,
        gate_inject_dir,
    )

    env: dict[str, str] = {}
    run_dir = attach_gate_env(env, run_id="run-inject-1", workspace=tmp_path)
    assert run_dir.is_dir()
    inject = gate_inject_dir()
    assert (inject / "sitecustomize.py").is_file()
    assert env.get(ENV_INJECT) == "1"
    assert str(inject) in (env.get("PYTHONPATH") or "")
    assert env.get("DISCORD_OS_GATE_HOOK") == "discord-os gate-hook"
    assert env.get("DISCORD_OS_RUN_ID") == "run-inject-1"


def test_gate_inject_patch_invokes_hook_before_tool(tmp_path: Path, monkeypatch):
    """Prove the live wrap fires gate-hook — not install/stamp-only."""

    import importlib.util

    inject_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agent_discord"
        / "orchestration"
        / "gate_inject"
        / "sitecustomize.py"
    )
    spec = importlib.util.spec_from_file_location(
        "discord_os_gate_sitecustomize_test", inject_path
    )
    assert spec and spec.loader
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)

    calls: list[tuple[str, object]] = []

    class _Adapter:
        def _execute_tool(self, name, args, cwd, implement, task):
            calls.append(("tool", name))
            return f"ran:{name}"

    monkeypatch.setenv("DISCORD_OS_GATE_DIR", str(tmp_path / "g"))
    monkeypatch.setenv("DISCORD_OS_RUN_ID", "run-fire")
    monkeypatch.setenv("DISCORD_OS_GATE_TIMEOUT_SECONDS", "0.15")
    monkeypatch.setenv("DISCORD_OS_GATE_INJECT", "1")

    def fake_runner(argv, input=None, capture_output=True, text=True, timeout=None, env=None):
        calls.append(("hook", argv))
        # Simulate gate-hook deny (timeout path shape)
        class _Proc:
            stdout = json.dumps(
                {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "timeout",
                    "continue": False,
                }
            )
            stderr = ""
            returncode = 0

        return _Proc()

    assert sc.patch_execute_tool(_Adapter, runner=fake_runner) is True
    out = _Adapter()._execute_tool("run_terminal", {"command": "ls"}, tmp_path, True, None)
    assert any(row[0] == "hook" for row in calls)
    assert not any(row[0] == "tool" for row in calls)
    assert "denied" in out.lower() or "gate-hook" in out.lower()


def test_gate_inject_patch_allows_then_runs_tool(tmp_path: Path, monkeypatch):
    from pathlib import Path as P
    import importlib.util

    inject_path = (
        P(__file__).resolve().parents[1]
        / "src"
        / "agent_discord"
        / "orchestration"
        / "gate_inject"
        / "sitecustomize.py"
    )
    spec = importlib.util.spec_from_file_location(
        "discord_os_gate_sitecustomize_allow", inject_path
    )
    assert spec and spec.loader
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)

    ran: list[str] = []

    class _Adapter:
        def _execute_tool(self, name, args, cwd, implement, task):
            ran.append(name)
            return "ok"

    monkeypatch.setenv("DISCORD_OS_GATE_DIR", str(tmp_path / "g2"))
    monkeypatch.setenv("DISCORD_OS_RUN_ID", "run-allow")
    monkeypatch.setenv("DISCORD_OS_GATE_INJECT", "1")

    def fake_runner(argv, input=None, capture_output=True, text=True, timeout=None, env=None):
        class _Proc:
            stdout = json.dumps(
                {
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "Allowed.",
                    "continue": True,
                    "gate_result": "allow",
                }
            )
            stderr = ""
            returncode = 0

        return _Proc()

    assert sc.patch_execute_tool(_Adapter, runner=fake_runner) is True
    assert _Adapter()._execute_tool("write_file", {"path": "a"}, tmp_path, True, None) == "ok"
    assert ran == ["write_file"]


def test_drain_auto_allows_when_write_gate_off(tmp_path: Path):
    from agent_discord.orchestration.gate_hook import (
        ensure_run_gate_dir,
        resolve_run_gate_dir,
    )

    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, False)
    receipt = orch.run_task(
        TaskIntake(
            text="review auto allow drain",
            channel_id="ch",
            workspace_id="ws",
            message_id="live-drain-auto",
        )
    )
    run_dir = ensure_run_gate_dir(
        resolve_run_gate_dir(run_id=receipt.run_id, workspace=tmp_path, store=store)
    )
    req = build_request(run_id=receipt.run_id, tool_name="shell", tool_input="pwd")
    enqueue_request(run_dir, req)
    acted = drain_gate_queue(orch)
    assert any(row.get("action") == "auto_allow" for row in acted)
    found = read_result(run_dir, req.request_id)
    assert found is not None
    assert found.decision == "allow"
    # No Discord park when write-gate is off
    assert orch.gate_result_for(receipt.run_id).get("awaiting_gate") in {None, False, 0, ""}
    store.close()


def test_live_hook_cli_fires_enqueue_then_drain_parks(tmp_path: Path):
    """End-to-end: real run_hook enqueues; drain parks Ask/Allow card."""

    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    receipt = orch.run_task(
        TaskIntake(
            text="review live hook fire",
            channel_id="ch",
            workspace_id="ws",
            message_id="live-hook-fire",
        )
    )
    from agent_discord.orchestration.gate_hook import (
        ensure_run_gate_dir,
        resolve_run_gate_dir,
        run_hook,
    )

    run_dir = ensure_run_gate_dir(
        resolve_run_gate_dir(run_id=receipt.run_id, workspace=tmp_path, store=store)
    )
    env = {
        "DISCORD_OS_GATE_DIR": str(run_dir),
        "DISCORD_OS_RUN_ID": receipt.run_id,
        "DISCORD_OS_GATE_TIMEOUT_SECONDS": "2.0",
    }

    box: dict = {}

    def hold() -> None:
        stdin = io.StringIO(
            json.dumps(
                {
                    "tool_name": "run_terminal",
                    "tool_input": {"command": "pytest -q"},
                    "run_id": receipt.run_id,
                }
            )
        )
        stdout = io.StringIO()
        box["code"] = run_hook([], stdin=stdin, stdout=stdout, env=env)
        box["payload"] = json.loads(stdout.getvalue())

    thread = threading.Thread(target=hold)
    thread.start()
    deadline = time.time() + 2.0
    pending_seen = False
    while time.time() < deadline:
        from agent_discord.orchestration.gate_hook import list_pending

        if list_pending(run_dir):
            pending_seen = True
            break
        time.sleep(0.02)
    assert pending_seen, "gate-hook did not enqueue pending/ — hook did not fire"
    parked = drain_gate_queue(orch)
    assert any(row.get("action") == "park" for row in parked)
    assert orch.gate_result_for(receipt.run_id).get("awaiting_gate") is True
    allowed = orch.apply_job_action("approve", receipt.run_id)
    assert allowed["gate_result"] == "allow"
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert box.get("code") == 0
    assert box["payload"]["permissionDecision"] == "allow"
    assert box["payload"]["continue"] is True
    store.close()
