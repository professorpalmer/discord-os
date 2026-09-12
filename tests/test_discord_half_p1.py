"""Discord-half P1: chrome Sections, settle File, dos: router, ACK-first, ephemeral menus."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import ArtifactRef, RunReceipt, TaskStatus
from agent_discord.discord.layout import TYPE_FILE, TYPE_SECTION
from agent_discord.host.actions import (
    DOS_ID_PREFIX,
    job_action_from_custom_id,
    job_custom_id,
    resolve_job_run_id,
)
from agent_discord.host.panel import (
    FLAG_EPHEMERAL,
    GATE_CONFIRM_ID,
    GATE_ID,
    PAIR_CONFIRM_ID,
    PAIR_ID,
    gate_menu_payload,
    handle_gateway_interaction,
    host_panel_components,
    pair_menu_payload,
    panel_action_from_custom_id,
)
from agent_discord.orchestration.cards import (
    settle_file_attachment,
    working_card,
)
from agent_discord.orchestration.job_briefing import (
    CHROME_DONE,
    CHROME_LIVE,
    CHROME_NEED,
    accent_for_chrome,
    chrome_bucket,
)
from agent_discord.orchestration.reactive import reactive_paint, reactive_receipt_card
from agent_discord.persistence.sqlite import SQLiteStore


def test_chrome_bucket_need_live_done():
    assert chrome_bucket({"status": "failed"}) == CHROME_NEED
    assert chrome_bucket({"status": "pending"}) == CHROME_NEED
    assert chrome_bucket({"status": "running"}) == CHROME_LIVE
    assert chrome_bucket({"status": "completed"}) == CHROME_DONE
    assert accent_for_chrome(CHROME_NEED) != accent_for_chrome(CHROME_DONE)


def test_job_card_section_layout_by_chrome():
    card = working_card(task_label="Allow write", message="park", run_id="run-1", actions="parked")
    root = card.v2_components()[0]
    assert root["accent_color"] == card.color
    types = [child.get("type") for child in root["components"]]
    assert TYPE_SECTION in types
    assert card.chrome == CHROME_NEED


def test_settle_file_on_fail_and_diff(tmp_path: Path):
    diff = tmp_path / "patch.diff"
    diff.write_text("--- a\n+++ b\n", encoding="utf-8")
    failed = RunReceipt(
        task_id="t",
        run_id="r1",
        status=TaskStatus.FAILED,
        summary="boom",
        error="traceback here",
    )
    name, data = settle_file_attachment(failed)
    assert name == "error.log"
    assert b"traceback" in data

    ok = RunReceipt(
        task_id="t",
        run_id="r2",
        status=TaskStatus.COMPLETED,
        summary="shipped",
        artifacts=(
            ArtifactRef(
                artifact_id="a1",
                kind="diff",
                path=str(diff),
                filename="patch.diff",
                sha256="x",
                size=diff.stat().st_size,
            ),
        ),
    )
    name, data = settle_file_attachment(ok)
    assert name == "patch.diff"
    assert b"+++" in data
    painted = reactive_receipt_card(ok, has_thread=True)
    assert painted.file_name == "patch.diff"
    assert painted.file_data
    assert painted.chrome == CHROME_DONE
    types = [c.get("type") for c in painted.v2_components()[0]["components"]]
    assert TYPE_FILE in types


def test_dos_custom_id_router_restart_safe(tmp_path: Path):
    store = SQLiteStore(tmp_path / "p1.sqlite3")
    store.initialize()
    store.create_task(
        task_id="task-1",
        workspace_id="ws",
        channel_id="ch",
        intake_text="cook",
    )
    code = store.task_job_code("task-1")
    assert code.startswith("DOS-")
    store.create_run(
        run_id="run-abcdef12zzzz",
        task_id="task-1",
        model="openrouter/auto",
        adapter_name="openrouter/auto",
        status=TaskStatus.RUNNING,
    )
    run_id = "run-abcdef12zzzz"
    minted = job_custom_id("cancel", run_id, job_code=code)
    assert minted.startswith(DOS_ID_PREFIX)
    assert code in minted
    parsed = job_action_from_custom_id(minted)
    assert parsed is not None
    assert parsed.action == "cancel"
    assert parsed.job_code == code
    assert resolve_job_run_id(store, parsed) == run_id
    # Legacy still parses.
    legacy = job_custom_id("cancel", run_id)
    assert legacy.startswith("discord-os:job:")
    assert job_action_from_custom_id(legacy).run_id == run_id


def test_ephemeral_pair_and_gate_menus():
    assert panel_action_from_custom_id(PAIR_ID) == "pair"
    assert panel_action_from_custom_id(PAIR_CONFIRM_ID) == "pair-confirm"
    assert panel_action_from_custom_id(GATE_ID) == "gate"
    assert panel_action_from_custom_id(GATE_CONFIRM_ID) == "gate-confirm"
    pair = pair_menu_payload()
    assert pair["type"] == 4
    assert pair["data"]["flags"] == FLAG_EPHEMERAL
    gate = gate_menu_payload(write_gate=False)
    assert GATE_CONFIRM_ID in str(gate)


def test_pair_opens_ephemeral_menu_not_seed(tmp_path: Path):
    store = SQLiteStore(tmp_path / "pair.sqlite3")
    calls: list[dict] = []

    def opener(request, timeout=10):  # noqa: ANN001
        body = request.data or b""
        calls.append({"url": request.full_url, "body": body})

        class _Resp:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

        return _Resp()

    payload = {
        "id": "ix1",
        "token": "tok",
        "application_id": "app",
        "type": 3,
        "channel_id": "ch1",
        "member": {"user": {"id": "u1"}, "roles": []},
        "data": {"custom_id": "discord-os:more", "values": [PAIR_ID]},
    }
    result = handle_gateway_interaction(
        store, "ch1", payload, token="bot", opener=opener
    )
    assert result == "pair"
    assert calls, "expected interaction ACK"
    body = calls[0]["body"].decode("utf-8", errors="replace")
    assert "Pair this Discord user" in body or PAIR_CONFIRM_ID in body
    assert FLAG_EPHEMERAL == 64


def test_jobs_select_prefixes_chrome_bucket():
    rows = host_panel_components(
        True,
        jobs=[
            {
                "run_id": "r1",
                "status": "failed",
                "job_code": "DOS-10001",
                "summary": "broke",
            }
        ],
    )
    jobs = rows[-1]["components"][0]
    assert jobs["options"][0]["label"].startswith("Need")
    assert "DOS-10001" in jobs["options"][0]["label"]


def test_reactive_failed_chrome_is_need():
    paint = reactive_paint(TaskStatus.FAILED, has_thread=True)
    assert paint.chrome == CHROME_NEED
    assert paint.accent == accent_for_chrome(CHROME_NEED)
