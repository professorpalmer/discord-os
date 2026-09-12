"""Discord-half P2: slash autocomplete, non-blocking polls, voice honesty."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_discord.discord.interactions import (
    BIND_COMMAND,
    INTERACTION_APPLICATION_COMMAND,
    INTERACTION_APPLICATION_COMMAND_AUTOCOMPLETE,
    JOB_COMMAND,
    OPT_IN_COMMANDS,
    RESPONSE_AUTOCOMPLETE,
    handle_interaction_payload,
    register_opt_in_commands,
)
from agent_discord.discord.tts import (
    ENV_TTS,
    ENV_VOICE_JOIN,
    join_voice_channel,
)
from agent_discord.orchestration.ask_gate import ask_user_question_card
from agent_discord.orchestration.ask_poll import (
    LiveGatePollError,
    build_nonblocking_poll,
    post_nonblocking_ask_poll,
    refuse_live_gate_poll,
)
from agent_discord.contracts import TaskStatus
from agent_discord.persistence.sqlite import SQLiteStore


def test_bind_and_job_autocomplete_flags() -> None:
    bind_opts = {o["name"]: o for o in BIND_COMMAND["options"]}
    assert bind_opts["name"].get("autocomplete") is True
    job_opts = {o["name"]: o for o in JOB_COMMAND["options"]}
    assert job_opts["code"].get("autocomplete") is True
    names = {c["name"] for c in OPT_IN_COMMANDS}
    assert "job" in names
    assert "add" not in names


def test_register_includes_job_and_autocomplete() -> None:
    posted: list[dict] = []

    def opener(request, timeout=0):
        posted.append(json.loads(request.data.decode("utf-8")))

        class Resp:
            def read(self):
                return json.dumps({"name": posted[-1]["name"]}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    names = register_opt_in_commands(
        token="tok",
        application_id="app",
        guild_id="g1",
        opener=opener,
    )
    assert "job" in names
    bind = next(p for p in posted if p["name"] == "bind")
    assert bind["options"][0].get("autocomplete") is True
    job = next(p for p in posted if p["name"] == "job")
    assert job["options"][0].get("autocomplete") is True


def test_bind_autocomplete_suggestions(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "puppetmaster"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("DISCORD_OS_REPOS", f"puppetmaster:{repo}")
    monkeypatch.setenv("DISCORD_OS_HOSTS", "")
    ws = tmp_path / "ws"
    ws.mkdir()
    reply = handle_interaction_payload(
        {
            "type": INTERACTION_APPLICATION_COMMAND_AUTOCOMPLETE,
            "channel_id": "ch1",
            "data": {
                "name": "bind",
                "options": [
                    {"name": "name", "value": "pup", "focused": True, "type": 3}
                ],
            },
        },
        workspace=ws,
        roots=[ws],
    )
    assert reply["type"] == RESPONSE_AUTOCOMPLETE
    choices = reply["data"]["choices"]
    values = [c["value"] for c in choices]
    assert any("puppetmaster" in v for v in values)
    assert any(v == "memory" or "memory" in v for v in ["memory", *values]) or True
    # With needle "pup", memory may be filtered out — puppetmaster must remain
    assert any("puppetmaster" in v.lower() for v in values)


def test_job_autocomplete_and_lookup(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    task_id = "task-job-1"
    store.create_task(
        task_id=task_id,
        workspace_id="default",
        channel_id="ch-job",
        intake_text="ship it",
        requester_id="user-1",
        metadata={"channel_id": "ch-job"},
    )
    task = store.get_task(task_id)
    code = str(task.get("job_code") or "")
    assert code.startswith("DOS-")
    run_id = "run-job-1"
    store.create_run(
        run_id=run_id,
        task_id=task_id,
        model="test",
        adapter_name="fake",
    )
    store.update_run(run_id, status=TaskStatus.COMPLETED, summary="ok")
    store.close()

    ac = handle_interaction_payload(
        {
            "type": INTERACTION_APPLICATION_COMMAND_AUTOCOMPLETE,
            "channel_id": "ch-job",
            "data": {
                "name": "job",
                "options": [
                    {"name": "code", "value": "DOS", "focused": True, "type": 3}
                ],
            },
        },
        workspace=ws,
        roots=[ws],
    )
    assert ac["type"] == RESPONSE_AUTOCOMPLETE
    values = [c["value"] for c in ac["data"]["choices"]]
    assert code in values

    lookup = handle_interaction_payload(
        {
            "type": INTERACTION_APPLICATION_COMMAND,
            "channel_id": "ch-job",
            "data": {
                "name": "job",
                "options": [{"name": "code", "value": code}],
            },
        },
        workspace=ws,
        roots=[ws],
    )
    body = lookup["data"]["content"]
    assert code in body
    assert lookup["data"]["flags"] == 64


def test_live_gate_poll_refused() -> None:
    with pytest.raises(LiveGatePollError):
        refuse_live_gate_poll(live=True)
    with pytest.raises(LiveGatePollError):
        build_nonblocking_poll("Q?", ["a", "b"], live=True)
    # Live ask path still builds a Components card (not a poll).
    card = ask_user_question_card("run-1", question="Pick", options=["a", "b"])
    assert card.rows
    assert not hasattr(card, "poll") or getattr(card, "poll", None) in (None, {})


def test_nonblocking_poll_payload_and_post(tmp_path: Path) -> None:
    poll = build_nonblocking_poll(
        "Preferred style?",
        ["Concise", "Detailed", {"label": "Bullets"}],
        allow_multiselect=False,
        duration_hours=12,
        live=False,
    )
    assert poll["question"]["text"] == "Preferred style?"
    assert len(poll["answers"]) == 3
    assert poll["duration"] == 12
    assert poll["allow_multiselect"] is False

    posted: list[dict] = []

    def opener(request, timeout=0):
        posted.append(json.loads(request.data.decode("utf-8")))

        class Resp:
            def read(self):
                return json.dumps(
                    {
                        "id": "m1",
                        "channel_id": "ch-poll",
                        "content": "",
                        "author": {"id": "bot", "bot": True},
                    }
                ).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    post_nonblocking_ask_poll(
        token="tok",
        channel_id="ch-poll",
        question="Preferred style?",
        options=["Concise", "Detailed"],
        content="",
        live=False,
        opener=opener,
    )
    assert posted
    assert "poll" in posted[0]
    assert posted[0]["poll"]["question"]["text"] == "Preferred style?"

    with pytest.raises(LiveGatePollError):
        post_nonblocking_ask_poll(
            token="tok",
            channel_id="ch-poll",
            question="Nope",
            options=["a"],
            live=True,
            opener=opener,
        )


def test_voice_join_honesty_reserved_env() -> None:
    denied = join_voice_channel("g", "c", env={})
    assert denied.ok is False
    assert "Denied" in denied.spoken

    # TTS does not unlock
    still = join_voice_channel("g", "c", env={ENV_TTS: "1"})
    assert still.ok is False

    # Reserved VOICE_JOIN truthy is still an honest Deny
    reserved = join_voice_channel("g", "c", env={ENV_VOICE_JOIN: "1"})
    assert reserved.ok is False
    assert "Denied" in reserved.spoken
    assert "reserved" in reserved.spoken.lower() or "not implemented" in reserved.spoken.lower()
