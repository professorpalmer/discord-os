"""P1.5 write-gate Allow / Always allow / Deny and P1.6 Continue."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import TaskIntake, TaskStatus
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.host.actions import job_action_from_custom_id, job_custom_id
from agent_discord.host.panel import (
    JOBS_ID,
    _publish_job_card,
    handle_gateway_interaction,
)
from agent_discord.orchestration.cards import job_action_row, receipt_card, working_card
from agent_discord.orchestration.job_briefing import DEFAULT_CONTINUE_PROMPT, is_idle_job
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.orchestration.service import (
    set_write_gate,
    set_write_session_allow,
    write_session_allows_writes,
    writes_need_approval_for,
)
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend


def _orch(tmp_path: Path):
    store = SQLiteStore(tmp_path / "gate.sqlite3")
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


def _button_ids(card) -> list[str]:
    ids: list[str] = []
    for row in card.rows or ():
        for item in row.get("components") or ():
            cid = str(item.get("custom_id") or "")
            if cid:
                ids.append(cid)
    return ids


def test_parked_row_is_discode_allow_always_deny():
    row = job_action_row("run-1", actions="parked")
    labels = [c["label"] for c in row["components"]]
    ids = [c["custom_id"] for c in row["components"]]
    assert labels == ["Allow", "Always allow", "Deny"]
    assert ids == [
        "discord-os:job:approve:run-1",
        "discord-os:job:always:run-1",
        "discord-os:job:deny:run-1",
    ]
    assert job_action_from_custom_id(ids[0]).action == "approve"
    assert job_action_from_custom_id(ids[1]).action == "always"
    assert job_action_from_custom_id(ids[2]).action == "deny"


def test_idle_row_offers_continue():
    row = job_action_row("run-2", actions="idle")
    assert [c["label"] for c in row["components"]] == ["Continue"]
    assert row["components"][0]["custom_id"] == "discord-os:job:continue:run-2"
    assert job_action_from_custom_id(job_custom_id("continue", "run-2")).action == "continue"


def test_deny_fails_parked_write_with_spoken_summary(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    parked = orch.run_task(
        TaskIntake(
            text="implement the login timeout fix",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-deny",
        )
    )
    assert parked.status == TaskStatus.PENDING
    assert backend.dispatch_count == 0
    result = orch.apply_job_action("deny", parked.run_id)
    assert result["action"] == "deny"
    assert result["status"] == TaskStatus.FAILED.value
    assert "Denied" in result["summary"]
    run = store.get_run(parked.run_id)
    assert run["status"] == TaskStatus.FAILED.value
    assert "Denied" in (run.get("summary") or "")
    assert backend.dispatch_count == 0
    store.close()


def test_allow_resumes_parked_write_once(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    parked = orch.run_task(
        TaskIntake(
            text="implement the allow path",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-allow",
        )
    )
    assert parked.status == TaskStatus.PENDING
    result = orch.apply_job_action("approve", parked.run_id)
    assert result["status"] == TaskStatus.COMPLETED.value
    assert backend.dispatch_count == 1
    store.close()


def test_always_allow_sets_session_pref_and_skips_later_gate(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    set_write_gate(store, True)
    first = orch.run_task(
        TaskIntake(
            text="implement session allow first",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-always-1",
        )
    )
    assert first.status == TaskStatus.PENDING
    thread_id = next(iter(fake.threads))
    result = orch.apply_job_action("always", first.run_id)
    assert result["action"] == "always"
    assert result["status"] == TaskStatus.COMPLETED.value
    assert write_session_allows_writes(store, thread_id)
    assert not writes_need_approval_for(
        store, channel_id="ch", thread_id=thread_id
    )
    second = orch.run_task(
        TaskIntake(
            text="implement session allow second",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-always-2",
            thread_id=thread_id,
        )
    )
    assert second.status == TaskStatus.COMPLETED
    assert backend.dispatch_count == 2
    store.close()


def test_continue_starts_tip_parented_job_in_same_thread(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    first = orch.run_task(
        TaskIntake(
            text="review the billing module",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-cont-1",
        )
    )
    assert first.status == TaskStatus.COMPLETED
    thread_id = next(iter(fake.threads))
    task = store.get_task(first.task_id)
    assert task["thread_id"] == thread_id
    assert is_idle_job({"status": "completed"})
    before = backend.dispatch_count
    result = orch.apply_job_action("continue", first.run_id)
    assert result["action"] == "continue"
    assert result["status"] == TaskStatus.COMPLETED.value
    assert result["thread_id"] == thread_id
    assert result["intake_text"] == DEFAULT_CONTINUE_PROMPT
    assert backend.dispatch_count == before + 1
    child = store.get_run(result["run_id"])
    assert child is not None
    child_task = store.get_task(child["task_id"])
    assert child_task["thread_id"] == thread_id
    assert child_task["intake_text"] == DEFAULT_CONTINUE_PROMPT
    store.close()


def test_continue_uses_ask_prompt_when_provided(tmp_path: Path):
    orch, store, fake, backend = _orch(tmp_path)
    first = orch.run_task(
        TaskIntake(
            text="review invoices",
            channel_id="ch",
            workspace_id="ws",
            message_id="ask-cont-prompt",
        )
    )
    result = orch.apply_job_action(
        "continue", first.run_id, prompt="Tighten the summary wording."
    )
    assert result["intake_text"] == "Tighten the summary wording."
    child = store.get_task(store.get_run(result["run_id"])["task_id"])
    assert child["intake_text"] == "Tighten the summary wording."
    store.close()


def test_publish_job_card_idle_includes_continue(tmp_path: Path):
    store = SQLiteStore(tmp_path / "panel.sqlite3")
    store.initialize()
    store.create_task(
        task_id="t-idle",
        workspace_id="ws",
        channel_id="ch",
        thread_id="thread-idle",
        intake_text="ship the fix",
    )
    store.create_run(
        run_id="run-idle",
        task_id="t-idle",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.COMPLETED,
    )
    store.update_run("run-idle", status=TaskStatus.COMPLETED, summary="Done. Fix shipped.")

    sent: list[dict] = []

    def opener(request, timeout=60):
        class _Resp:
            status = 200

            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        body = getattr(request, "data", None) or b""
        if isinstance(body, bytes):
            raw = body.decode("utf-8", errors="replace")
        else:
            raw = str(body)
        sent.append({"url": str(getattr(request, "full_url", "")), "body": raw})
        return _Resp()

    payload = {
        "application_id": "app",
        "token": "ix",
        "data": {"custom_id": JOBS_ID, "values": ["run-idle"]},
    }
    _publish_job_card(
        store,
        "ch",
        payload,
        token="bot-token",
        opener=opener,
    )
    assert sent
    blob = str(sent[-1].get("body") or "")
    assert "discord-os:job:continue:run-idle" in blob
    pending = store.get_preference("_host", "pending_continue:ch")
    assert pending == "run-idle"
    store.close()


def test_gateway_deny_button_routes_to_on_job(tmp_path: Path):
    store = SQLiteStore(tmp_path / "gw.sqlite3")
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
            "data": {"custom_id": job_custom_id("deny", "run-parked")},
            "member": {"user": {"id": "u1"}},
        },
        opener=_Opener(),
        on_job=on_job,
    )
    assert action == "deny"
    assert seen == [("deny", "run-parked")]
    store.close()


def test_session_allow_helper_round_trip(tmp_path: Path):
    store = SQLiteStore(tmp_path / "pref.sqlite3")
    store.initialize()
    set_write_gate(store, True)
    assert writes_need_approval_for(store, channel_id="ch", thread_id="th")
    set_write_session_allow(store, "th", ttl_seconds=120)
    assert write_session_allows_writes(store, "th")
    assert not writes_need_approval_for(store, channel_id="ch", thread_id="th")
    store.close()
