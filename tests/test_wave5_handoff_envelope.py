"""Wave 5 P0a: typed handoff envelope + idempotent already_claimed."""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import RunReceipt, TaskStatus
from agent_discord.host.brain import format_meat_proxy_handoff_preamble
from agent_discord.orchestration.cards import receipt_card
from agent_discord.orchestration.handoff_envelope import (
    build_handoff_envelope,
    find_live_handoff_claim,
    spoken_already_claimed,
    stable_handoff_id,
)
from agent_discord.persistence.sqlite import SQLiteStore


def test_stable_id_and_kv_parse():
    env, cleaned = build_handoff_envelope(
        from_id="111",
        to_id="222",
        peer_prompt="finish tests | constraints=no-push | expecting=ci-green",
        now_ms=1,
    )
    assert cleaned == "finish tests"
    assert env.constraints == "no-push"
    assert env.expecting == "ci-green"
    assert env.handoff_id == stable_handoff_id(
        from_id="111", to_id="222", prompt="finish tests"
    )
    assert env.freshness.startswith("ms:")


def test_explicit_handoff_id():
    env, cleaned = build_handoff_envelope(
        from_id="1",
        to_id="2",
        peer_prompt="id=abc123 do work",
        now_ms=1,
    )
    assert env.handoff_id == "abc123"
    assert "do work" in cleaned


def test_already_claimed_round_trip(tmp_path: Path):
    store = SQLiteStore(tmp_path / "h.sqlite3")
    store.initialize()
    env, cleaned = build_handoff_envelope(
        from_id="111", to_id="222", peer_prompt="same task", now_ms=9
    )
    assert find_live_handoff_claim(store, env.handoff_id, channel_id="ch") is None
    store.create_task(
        task_id="task-handoff-1",
        workspace_id="default",
        channel_id="ch",
        intake_text=cleaned,
        requester_id="222",
        metadata=env.as_metadata(),
    )
    # create_task defaults pending — treat as live for claim
    store._connection().execute(
        "UPDATE tasks SET status=? WHERE task_id=?",
        ("running", "task-handoff-1"),
    )
    store._connection().commit()
    hit = find_live_handoff_claim(store, env.handoff_id, channel_id="ch")
    assert hit is not None
    assert "already_claimed" in spoken_already_claimed(env.handoff_id)
    store.close()


def test_receipt_and_preamble_include_envelope(tmp_path: Path):
    store = SQLiteStore(tmp_path / "b.sqlite3")
    store.initialize()
    env, cleaned = build_handoff_envelope(
        from_id="111",
        to_id="222",
        peer_prompt="ship it | brain_dri=alex | constraints=no-push",
        now_ms=2,
    )
    preamble = format_meat_proxy_handoff_preamble(
        store,
        workspace_id="default",
        channel_id="ch",
        from_id="111",
        to_id="222",
        peer_prompt=cleaned,
        envelope=env,
    )
    assert "meat-proxy-cut" in preamble
    assert "handoff-envelope" in preamble
    assert env.handoff_id in preamble
    receipt = RunReceipt(
        task_id="t",
        run_id="r",
        status=TaskStatus.COMPLETED,
        summary="ok",
    )
    card = receipt_card(receipt, operator="222", lane="handoff", handoff_envelope=env)
    names = {n for n, _v, _i in card.fields}
    assert "Handoff" in names
    assert "From" in names
    store.close()
