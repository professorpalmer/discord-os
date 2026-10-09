"""Audit 2026-10-02 F9: prose lines are not JSON, and large prompts steer too.

Two separate losses:
  * ``if raw[:1] in "{["`` dropped markdown links and citations like "[1] ...".
  * ``_try_parse_json`` rfind-sliced any ``{...}`` out of a prose line, so a
    sentence mentioning JSON became a token event.
"""

from __future__ import annotations

from pathlib import Path

from agent_discord.contracts import EventKind
from agent_discord.puppetmaster.backend import (
    TokenStreamBuffer,
    _event_from_cli_line,
    _parse_token_line,
)
from agent_discord.puppetmaster.prompt_handoff import (
    EARLY_JOB_ID_FLAG,
    agentic_file_bridge,
    plan_local_agentic_handoff,
)

MODEL = "openrouter/auto"


def _prose(line: str) -> str:
    buffer = TokenStreamBuffer()
    event = _event_from_cli_line(line, MODEL, buffer)
    assert event is not None, f"dropped: {line!r}"
    assert event.kind == EventKind.PROGRESS
    return event.summary.details["token_text"]


def test_markdown_citation_survives() -> None:
    assert "[1] https://example.com/spec" in _prose("[1] https://example.com/spec")


def test_markdown_link_line_survives() -> None:
    assert "[the spec](https://example.com)" in _prose("[the spec](https://example.com)")


def test_bracketed_list_item_survives() -> None:
    assert "[x] shipped the fix" in _prose("[x] shipped the fix")


def test_prose_mentioning_json_is_not_a_token_event() -> None:
    line = 'The adapter config is {"adapters": {"agentic": true}} in platform.json'
    # Not parsed as structured output...
    assert _parse_token_line(line, MODEL) is None
    # ...and kept as prose.
    assert "platform.json" in _prose(line)


def test_prose_ending_in_a_brace_is_not_a_token_event() -> None:
    line = 'It failed because the payload was {"type": "delta", "text": "nope"}'
    assert _parse_token_line(line, MODEL) is None
    assert "It failed because" in _prose(line)


def test_a_whole_json_delta_line_is_still_a_token_event() -> None:
    buffer = TokenStreamBuffer()
    event = _parse_token_line('{"type": "delta", "text": "Hello"}', MODEL, buffer=buffer)
    assert event is not None
    assert event.summary.details["token_text"] == "Hello"


def test_a_whole_json_line_is_not_re_emitted_as_prose() -> None:
    buffer = TokenStreamBuffer()
    # A JSON object with no token payload: structured, so not prose either.
    assert _event_from_cli_line('{"unrelated": 1}', MODEL, buffer) is None
    assert _event_from_cli_line('[{"unrelated": 1}]', MODEL, buffer) is None


def test_file_bridge_bakes_the_early_job_id_before_the_subcommand() -> None:
    bridge = agentic_file_bridge(global_flags=(EARLY_JOB_ID_FLAG,))
    assert (
        f"sys.argv = ['puppetmaster', '{EARLY_JOB_ID_FLAG}', 'agentic', prompt"
        in bridge
    )
    assert EARLY_JOB_ID_FLAG not in agentic_file_bridge()


def test_oversized_stream_prompt_still_asks_for_the_job_id(monkeypatch, tmp_path: Path) -> None:
    pm_py = tmp_path / "python"
    pm_py.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "agent_discord.puppetmaster.prompt_handoff.resolve_puppetmaster_python",
        lambda cli: str(pm_py),
    )
    handoff = plan_local_agentic_handoff(
        cli="puppetmaster",
        prompt="x" * 200_000,
        flags=["--provider", "openrouter"],
        early_job_id=True,
    )
    try:
        assert handoff.mode == "file"
        bridge = handoff.argv[2]
        assert EARLY_JOB_ID_FLAG in bridge
        # The flag rides in the bridge source, never on argv beside the prompt.
        assert EARLY_JOB_ID_FLAG not in handoff.argv[3:]
    finally:
        handoff.cleanup()


def test_small_stream_prompt_is_unchanged(monkeypatch) -> None:
    handoff = plan_local_agentic_handoff(
        cli="puppetmaster", prompt="hi", flags=["--provider"], early_job_id=True
    )
    assert handoff.mode == "argv"
    assert handoff.argv == ["puppetmaster", "agentic", "hi", "--provider"]


def test_stream_spawn_uses_the_early_job_id_bridge_for_a_huge_prompt(
    monkeypatch, tmp_path: Path
) -> None:
    from agent_discord.contracts import ContextSnapshot, DispatchRequest
    from agent_discord.puppetmaster.agentic import AgenticPuppetmasterBackend
    from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN

    pm_py = tmp_path / "python"
    pm_py.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "agent_discord.puppetmaster.prompt_handoff.resolve_puppetmaster_python",
        lambda cli: str(pm_py),
    )
    backend = AgenticPuppetmasterBackend(
        cli="puppetmaster", pin=AGENTIC_MODEL_PIN, cwd=tmp_path, env={}
    )
    request = DispatchRequest(
        task_id="t1",
        run_id="r1",
        prompt="y" * 200_000,
        model="openrouter/auto",
        context=ContextSnapshot(task_id="t1", memories=[], bindings={}),
    )
    handoff, _workdir = backend._plan_agentic_spawn(request, stream=True)
    try:
        assert handoff.mode == "file"
        assert EARLY_JOB_ID_FLAG in handoff.argv[2]
    finally:
        handoff.cleanup()
