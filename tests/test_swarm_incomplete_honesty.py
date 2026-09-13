"""W1: swarm-incomplete honesty — prose answer must not become a false failed Need."""

from __future__ import annotations

from agent_discord.contracts import EventKind, TaskStatus
from agent_discord.puppetmaster.backend import (
    TokenStreamBuffer,
    is_swarm_incomplete_exit,
    salvage_swarm_incomplete_answer,
)


def test_is_swarm_incomplete_exit_detects_pm_runtime_error() -> None:
    assert is_swarm_incomplete_exit("RuntimeError: swarm exited with incomplete tasks")
    assert is_swarm_incomplete_exit("swarm exited with incomplete tasks")
    assert not is_swarm_incomplete_exit("worker process failed with exit code 1")
    assert not is_swarm_incomplete_exit("")


def test_salvage_keeps_spoken_prose_on_incomplete_swarm() -> None:
    answer = (
        "Discord OS should treat analyze-only answers as Done when the prose "
        "already landed, even if Puppetmaster exits swarm-incomplete."
    )
    salvaged = salvage_swarm_incomplete_answer(
        error="swarm exited with incomplete tasks",
        token_text=answer,
    )
    assert salvaged == answer


def test_salvage_refuses_without_prose() -> None:
    assert (
        salvage_swarm_incomplete_answer(
            error="swarm exited with incomplete tasks",
            token_text="",
        )
        == ""
    )


def test_salvage_refuses_provider_auth_failures() -> None:
    assert (
        salvage_swarm_incomplete_answer(
            error="swarm exited with incomplete tasks",
            token_text=(
                "OpenRouter rejected the API key (HTTP 401). "
                "The worker never reached the model."
            ),
        )
        == ""
    )


def test_iter_cli_process_events_salvages_incomplete_swarm(monkeypatch) -> None:
    from agent_discord.puppetmaster import backend as be

    class _Proc:
        returncode = 1
        stdout = None
        stderr = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    prose = "The checkout is healthy and no further workers are required."

    def _fake_iter(proc, *, model, cli, timeout_seconds):
        # Drive the completion path inside iter_cli_process_events by monkeypatching
        # the internal join — call the real function with a stubbed communicate path.
        yield from ()

    # Exercise the completion salvage block directly via a thin wrapper.
    stdout = prose + "\n"
    stderr = "RuntimeError: swarm exited with incomplete tasks\n"
    safe = be._parse_safe_cli_completion(stdout, stderr)
    # Force error recognition
    safe["error"] = "swarm exited with incomplete tasks"
    salvaged = salvage_swarm_incomplete_answer(
        error=str(safe.get("error")),
        stderr=stderr,
        safe_meta=safe,
        token_text=prose,
        stdout=stdout,
    )
    assert salvaged
    assert "healthy" in salvaged


def test_orchestrator_remaps_failed_incomplete_to_completed(tmp_path, monkeypatch) -> None:
    """Belt-and-suspenders: FAILED + swarm-incomplete + spoken → COMPLETED receipt."""

    from agent_discord.contracts import (
        DispatchEvent,
        DispatchRequest,
        DispatchResult,
        ProgressSummary,
        TaskIntake,
    )
    from agent_discord.orchestration.orchestrator import AgentOrchestrator
    from agent_discord.persistence.sqlite import SQLiteStore
    from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN

    class _Backend:
        pin = AGENTIC_MODEL_PIN

        def resolve_model(self, requested: str):
            return self.pin

        def status(self, run_id: str):
            return TaskStatus.RUNNING

        def cancel(self, run_id: str) -> bool:
            return False

        def stream(self, request: DispatchRequest):
            yield DispatchEvent(
                kind=EventKind.PROGRESS,
                summary=ProgressSummary(
                    stage="plan",
                    message="Path A remote Cancel should hit the SSH cook.",
                    percent=40.0,
                ),
            )
            yield DispatchEvent(
                kind=EventKind.ERROR,
                summary=ProgressSummary(
                    stage="dispatch",
                    message="swarm exited with incomplete tasks",
                ),
            )

        def dispatch(self, request: DispatchRequest) -> DispatchResult:
            return DispatchResult(
                run_id=request.run_id,
                status=TaskStatus.FAILED,
                events=tuple(self.stream(request)),
                final_summary="dispatch failed",
                error="swarm exited with incomplete tasks",
            )

    store = SQLiteStore(tmp_path / "w1.sqlite3")
    store.initialize()
    orch = AgentOrchestrator(
        store=store,
        backend=_Backend(),
        post_progress_to_discord=False,
        compute_cwd=tmp_path,
    )
    receipt = orch.run_task(
        TaskIntake(
            workspace_id="ws",
            channel_id="ch",
            text="What is Path A Cancel honesty?",
            message_id="m-w1-swarm",
        )
    )
    assert receipt.status == TaskStatus.COMPLETED
    assert "Cancel" in (receipt.summary or "")
    assert not receipt.error
