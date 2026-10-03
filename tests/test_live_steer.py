"""Live steers reach the worker, or the operator is told they did not."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent_discord.contracts import (
    DispatchEvent,
    EventKind,
    ProgressSummary,
    TaskIntake,
    TaskStatus,
)
from agent_discord.discord.facade import DiscordFacade
from agent_discord.discord.layout import iter_component_text
from agent_discord.discord.providers.fake import FakeDiscordMCPProvider
from agent_discord.orchestration.orchestrator import AgentOrchestrator
from agent_discord.persistence.sqlite import SQLiteStore
from agent_discord.puppetmaster.agentic import AgenticPuppetmasterBackend
from agent_discord.puppetmaster.backend import iter_cli_process_events
from agent_discord.puppetmaster.fake import FakePuppetmasterBackend
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN


def test_stream_reports_job_id_once() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "print('job_id: job_abc123'); print('job_id: job_other'); print('hello')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    seen: list[str] = []
    list(iter_cli_process_events(proc, model="m", cli="", timeout_seconds=10, on_job_id=seen.append))
    assert seen == ["job_abc123"]


def _fake_cli(tmp_path: Path, exit_code: int) -> Path:
    log = tmp_path / "argv.txt"
    script = tmp_path / "puppetmaster"
    script.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {log}\nexit {exit_code}\n", encoding="utf-8"
    )
    script.chmod(0o755)
    return script


def test_agentic_steer_calls_puppetmaster_steer(tmp_path: Path) -> None:
    cli = _fake_cli(tmp_path, 0)
    backend = AgenticPuppetmasterBackend(
        cli=str(cli),
        pin=AGENTIC_MODEL_PIN,
        env={"PATH": "/usr/bin:/bin", "PUPPETMASTER_STATE_DIR": str(tmp_path / "pm")},
    )
    assert backend.steer("run-1", "use the v2 API") is False  # job id not known yet
    backend._job_ids["run-1"] = "job_abc123"
    assert backend.steer("run-1", "use the v2 API") is True
    argv = (tmp_path / "argv.txt").read_text(encoding="utf-8").splitlines()
    assert argv[-3:] == ["steer", "job_abc123", "use the v2 API"]
    assert "--state-dir" in argv


def test_agentic_steer_false_when_cli_refuses(tmp_path: Path) -> None:
    backend = AgenticPuppetmasterBackend(cli=str(_fake_cli(tmp_path, 2)), pin=AGENTIC_MODEL_PIN, env={})
    backend._job_ids["run-1"] = "job_abc123"
    assert backend.steer("run-1", "hello") is False


class _SteerableBackend(FakePuppetmasterBackend):
    """Streams a few events; steer succeeds only once the job id is 'known'."""

    def __init__(self, *, steer_after: int, during: list[str]) -> None:
        super().__init__()
        self.steer_after = steer_after
        self.during = during
        self.events_seen = 0
        self.orch: AgentOrchestrator | None = None
        self.delivered: list[str] = []

    def steer(self, run_id: str, text: str) -> bool:
        if self.events_seen < self.steer_after:
            return False
        self.delivered.append(text)
        return True

    def stream(self, request):
        self.last_request = request
        for index in range(4):
            self.events_seen = index
            if index == 0 and self.orch is not None:
                for text in self.during:
                    assert self.orch.steer(request.run_id, text) is True
            yield DispatchEvent(
                kind=EventKind.PROGRESS,
                summary=ProgressSummary(stage="working", message=f"step {index}"),
            )
        yield DispatchEvent(
            kind=EventKind.RECEIPT,
            summary=ProgressSummary(stage="done", message="All set."),
            payload={"final_summary": "All set."},
        )

    def status(self, run_id: str) -> TaskStatus:
        return TaskStatus.COMPLETED


def _orch(tmp_path: Path, backend) -> tuple[AgentOrchestrator, SQLiteStore, FakeDiscordMCPProvider]:
    store = SQLiteStore(tmp_path / "steer.sqlite3")
    store.initialize()
    fake = FakeDiscordMCPProvider()
    orch = AgentOrchestrator(
        store=store,
        backend=backend,
        discord=DiscordFacade(fake, bot_token_fingerprint="fp", owner_id="test"),
        post_progress_to_discord=True,
        host_repos=(),
    )
    backend.orch = orch
    return orch, store, fake


def _intake() -> TaskIntake:
    return TaskIntake(
        text="summarize the repo", channel_id="ch", workspace_id="ws",
        metadata={"compute_mode": "analyze"},
    )


def test_steer_retries_until_job_id_known(tmp_path: Path) -> None:
    """Audit A1/F8: a steer sent before the job id arrives is delivered later."""

    backend = _SteerableBackend(steer_after=2, during=["first", "second"])
    orch, store, _fake = _orch(tmp_path, backend)
    receipt = orch.run_task(_intake())
    assert receipt.status == TaskStatus.COMPLETED
    assert backend.delivered == ["first", "second"]
    assert "Not delivered" not in (store.get_run(receipt.run_id)["summary"] or "")
    store.close()


def test_undelivered_steer_is_named_on_done_card(tmp_path: Path) -> None:
    backend = _SteerableBackend(steer_after=99, during=["switch to staging"])
    orch, store, fake = _orch(tmp_path, backend)
    receipt = orch.run_task(_intake())
    summary = store.get_run(receipt.run_id)["summary"] or ""
    assert "Not delivered to the worker: switch to staging" in summary
    blob = "\n".join(
        part for m in fake.sent for part in iter_component_text((m.metadata or {}).get("components"))
    )
    assert "Not delivered to the worker" in blob
    store.close()


def test_steer_is_an_honest_miss_without_backend_support(tmp_path: Path) -> None:
    class _NoSteer(_SteerableBackend):
        steer = None  # type: ignore[assignment]

    backend = _NoSteer(steer_after=0, during=[])
    orch, store, _fake = _orch(tmp_path, backend)
    seen: list[bool] = []

    original = backend.stream

    def stream(request):
        seen.append(orch.steer(request.run_id, "anything"))
        yield from original(request)

    backend.stream = stream  # type: ignore[method-assign]
    orch.run_task(_intake())
    assert seen == [False]
    store.close()
