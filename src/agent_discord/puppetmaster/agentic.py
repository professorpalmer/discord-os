"""Puppetmaster agentic backend — OpenRouter/BYOK via subprocess env only."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from agent_discord.puppetmaster.cancel_honesty import (
    cancel_receipt,
    popen_kwargs_for_killable_child,
    terminate_process_group,
)
from agent_discord.puppetmaster.prompt_handoff import (
    is_arg_max_oserror,
    plan_local_agentic_handoff,
    spoken_arg_max_denied,
)

from agent_discord.contracts import (
    DispatchEvent,
    DispatchRequest,
    DispatchResult,
    EventKind,
    ModelNotAllowedError,
    ModelPin,
    ProgressSummary,
    TaskStatus,
    UsageReceipt,
)
from agent_discord.keys.vault import KeyVault
from agent_discord.puppetmaster.backend import (
    usage_from_cli_meta,
    _parse_safe_cli_completion,
    _safe_dispatch_prompt,
    cli_supports_flag,
    iter_cli_process_events,
    prepend_early_job_id,
    request_workdir,
    worker_env,
    salvage_swarm_incomplete_answer,
)
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN


@dataclass
class AgenticPuppetmasterBackend:
    """Boundary for ``puppetmaster agentic`` with OpenRouter injected in env.

    The API key is never placed on argv and is never logged. Model resolution
    is exact-allowlist only (``openrouter/auto``); no silent fallback.
    """

    cli: str = "puppetmaster"
    pin: ModelPin = field(default_factory=lambda: AGENTIC_MODEL_PIN)
    cwd: Optional[str | Path] = None
    timeout_seconds: float = 3600.0
    vault: Optional[KeyVault] = None
    env: Optional[Mapping[str, str]] = None
    _statuses: dict[str, TaskStatus] = field(default_factory=dict)
    _children: dict[str, Any] = field(default_factory=dict, repr=False)
    _cancel_requested: set[str] = field(default_factory=set, repr=False)
    _child_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def resolve_model(self, requested: str) -> ModelPin:
        self.pin.assert_allowed(requested)
        if requested != self.pin.canonical:
            raise ModelNotAllowedError(
                f"requested {requested!r} != pinned {self.pin.canonical!r}; "
                "no silent fallback"
            )
        return self.pin

    def available(self) -> bool:
        return shutil.which(self.cli) is not None

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        pin = self.resolve_model(request.model)
        self._statuses[request.run_id] = TaskStatus.RUNNING

        if not self.available():
            self._statuses[request.run_id] = TaskStatus.FAILED
            return DispatchResult(
                run_id=request.run_id,
                status=TaskStatus.FAILED,
                events=(
                    DispatchEvent(
                        kind=EventKind.ERROR,
                        summary=ProgressSummary(
                            stage="dispatch",
                            message=f"puppetmaster CLI not found: {self.cli}",
                        ),
                    ),
                ),
                final_summary="puppetmaster CLI unavailable",
                error=f"CLI not found: {self.cli}",
            )

        if not pin.adapter_name:
            self._statuses[request.run_id] = TaskStatus.FAILED
            return DispatchResult(
                run_id=request.run_id,
                status=TaskStatus.FAILED,
                events=(
                    DispatchEvent(
                        kind=EventKind.ERROR,
                        summary=ProgressSummary(
                            stage="dispatch",
                            message="model pin adapter_name is unavailable",
                        ),
                    ),
                ),
                final_summary="model pin unavailable",
                error="adapter_name missing on model pin",
            )

        handoff, workdir = self._plan_agentic_spawn(request, stream=False)

        child_env = worker_env(self.env)
        secret = self._resolve_secret()
        if secret:
            child_env["OPENROUTER_API_KEY"] = secret
        self._attach_gate_env(child_env, request, workdir)

        try:
            proc = self._spawn_agentic_popen(
                handoff, workdir=workdir, child_env=child_env
            )
        except OSError as exc:
            self._statuses[request.run_id] = TaskStatus.FAILED
            return DispatchResult(
                run_id=request.run_id,
                status=TaskStatus.FAILED,
                events=(
                    DispatchEvent(
                        kind=EventKind.ERROR,
                        summary=ProgressSummary(stage="dispatch", message=str(exc)),
                    ),
                ),
                final_summary="dispatch failed",
                error=str(exc),
            )

        self._register_child(request.run_id, proc)
        try:
            try:
                stdout, stderr = proc.communicate(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                terminate_process_group(proc, started_new_session=True)
                try:
                    stdout, stderr = proc.communicate(timeout=2)
                except Exception:
                    stdout, stderr = "", ""
                self._statuses[request.run_id] = TaskStatus.FAILED
                return DispatchResult(
                    run_id=request.run_id,
                    status=TaskStatus.FAILED,
                    events=(
                        DispatchEvent(
                            kind=EventKind.ERROR,
                            summary=ProgressSummary(stage="dispatch", message="timeout"),
                        ),
                    ),
                    final_summary="dispatch failed",
                    error="timeout",
                )
        finally:
            self._unregister_child(request.run_id, proc)
            handoff.cleanup()

        if request.run_id in self._cancel_requested:
            self._statuses[request.run_id] = TaskStatus.CANCELLED
            self._cancel_requested.discard(request.run_id)
            return DispatchResult(
                run_id=request.run_id,
                status=TaskStatus.CANCELLED,
                events=(
                    DispatchEvent(
                        kind=EventKind.CANCEL_REQUESTED,
                        summary=ProgressSummary(stage="cancelled", message="cancelled"),
                    ),
                ),
                final_summary="cancelled",
                error="cancelled",
            )

        safe_meta = _parse_safe_cli_completion(stdout or "", stderr or "")
        if proc.returncode != 0:
            err = safe_meta.get("error") or (stderr or "").strip() or f"exit {proc.returncode}"
            salvaged = salvage_swarm_incomplete_answer(
                error=str(err),
                stderr=stderr or "",
                safe_meta=safe_meta if isinstance(safe_meta, dict) else {},
                stdout=stdout or "",
            )
            if salvaged:
                if isinstance(safe_meta, dict):
                    safe_meta["summary"] = salvaged
                    safe_meta["swarm_incomplete_salvaged"] = True
                self._statuses[request.run_id] = TaskStatus.COMPLETED
                return DispatchResult(
                    run_id=request.run_id,
                    status=TaskStatus.COMPLETED,
                    events=(
                        DispatchEvent(
                            kind=EventKind.RECEIPT,
                            summary=ProgressSummary(
                                stage="done", message=salvaged, percent=100.0
                            ),
                            payload=safe_meta if isinstance(safe_meta, dict) else {"summary": salvaged},
                        ),
                    ),
                    final_summary=salvaged,
                    usage=usage_from_cli_meta(pin, self.cli, safe_meta),
                )
            self._statuses[request.run_id] = TaskStatus.FAILED
            return DispatchResult(
                run_id=request.run_id,
                status=TaskStatus.FAILED,
                events=(
                    DispatchEvent(
                        kind=EventKind.ERROR,
                        summary=ProgressSummary(stage="dispatch", message=str(err)),
                    ),
                ),
                final_summary="dispatch failed",
                error=str(err),
            )

        summary = str(safe_meta.get("summary") or "completed")
        self._statuses[request.run_id] = TaskStatus.COMPLETED
        return DispatchResult(
            run_id=request.run_id,
            status=TaskStatus.COMPLETED,
            events=(
                DispatchEvent(
                    kind=EventKind.DISPATCH,
                    summary=ProgressSummary(
                        stage="dispatch",
                        message=f"dispatched via agentic with {pin.adapter_name}",
                        details={"model": pin.canonical},
                    ),
                ),
                DispatchEvent(
                    kind=EventKind.RECEIPT,
                    summary=ProgressSummary(stage="done", message=summary, percent=100.0),
                    payload=safe_meta,
                ),
            ),
            final_summary=summary,
            usage=usage_from_cli_meta(pin, self.cli, safe_meta),
        )

    def cancel(self, run_id: str) -> bool:
        rid = (run_id or "").strip()
        if not rid:
            return False
        with self._child_lock:
            self._cancel_requested.add(rid)
            proc = self._children.get(rid)
        if proc is None:
            # No live child to interrupt — cannot confirm.
            return False
        ok = terminate_process_group(proc, started_new_session=True)
        if ok:
            self._statuses[rid] = TaskStatus.CANCELLED
        return bool(ok)

    def status(self, run_id: str) -> TaskStatus:
        return self._statuses.get(run_id, TaskStatus.PENDING)

    def stream(self, request: DispatchRequest) -> Iterator[DispatchEvent]:
        """Stream agentic dispatch progress live instead of blocking until completion."""
        pin = self.resolve_model(request.model)
        self._statuses[request.run_id] = TaskStatus.RUNNING

        if not self.available():
            self._statuses[request.run_id] = TaskStatus.FAILED
            yield DispatchEvent(
                kind=EventKind.ERROR,
                summary=ProgressSummary(
                    stage="dispatch",
                    message=f"puppetmaster CLI not found: {self.cli}",
                ),
            )
            return

        if not pin.adapter_name:
            self._statuses[request.run_id] = TaskStatus.FAILED
            yield DispatchEvent(
                kind=EventKind.ERROR,
                summary=ProgressSummary(
                    stage="dispatch",
                    message="model pin adapter_name is unavailable",
                ),
            )
            return

        handoff, workdir = self._plan_agentic_spawn(request, stream=True)

        child_env = worker_env(self.env)
        secret = self._resolve_secret()
        if secret:
            child_env["OPENROUTER_API_KEY"] = secret
        self._attach_gate_env(child_env, request, workdir)

        try:
            proc = self._spawn_agentic_popen(
                handoff, workdir=workdir, child_env=child_env
            )
        except OSError as exc:
            self._statuses[request.run_id] = TaskStatus.FAILED
            yield DispatchEvent(
                kind=EventKind.ERROR,
                summary=ProgressSummary(stage="dispatch", message=str(exc)),
            )
            return

        self._register_child(request.run_id, proc)
        try:
            yield DispatchEvent(
                kind=EventKind.DISPATCH,
                summary=ProgressSummary(
                    stage="dispatch",
                    message=f"dispatched via agentic with {pin.adapter_name}",
                    percent=2.0,
                    details={"model": pin.canonical},
                ),
            )
            for event in iter_cli_process_events(
                proc,
                model=pin.canonical,
                cli=self.cli,
                timeout_seconds=self.timeout_seconds,
            ):
                if request.run_id in self._cancel_requested:
                    self._statuses[request.run_id] = TaskStatus.CANCELLED
                    yield DispatchEvent(
                        kind=EventKind.CANCEL_REQUESTED,
                        summary=ProgressSummary(stage="cancelled", message="cancelled"),
                    )
                    return
                if event.kind == EventKind.ERROR:
                    self._statuses[request.run_id] = TaskStatus.FAILED
                elif event.kind == EventKind.RECEIPT:
                    self._statuses[request.run_id] = TaskStatus.COMPLETED
                yield event
            if request.run_id in self._cancel_requested:
                self._statuses[request.run_id] = TaskStatus.CANCELLED
                yield DispatchEvent(
                    kind=EventKind.CANCEL_REQUESTED,
                    summary=ProgressSummary(stage="cancelled", message="cancelled"),
                )
                return
            if self._statuses.get(request.run_id) == TaskStatus.RUNNING:
                self._statuses[request.run_id] = TaskStatus.COMPLETED
        finally:
            self._unregister_child(request.run_id, proc)
            self._cancel_requested.discard(request.run_id)
            handoff.cleanup()

    def _agentic_flags(
        self,
        request: DispatchRequest,
        *,
        workdir: Optional[str],
        mode: str,
        is_git: bool,
        stream: bool,
    ) -> list[str]:
        """Flags after the prompt (provider/model/mode/cwd/…)."""

        pin = self.pin
        flags: list[str] = [
            "--provider",
            "openrouter",
            "--model",
            pin.adapter_name or pin.canonical,
            "--mode",
            mode,
            "--timeout-seconds",
            str(int(self.timeout_seconds)),
        ]
        if stream:
            flags.extend(["--worker-mode", "inline"])
        if mode == "implement":
            flags.append("--allow-dirty")
            if not is_git:
                flags.append("--allow-non-worktree")
        elif not is_git:
            flags.extend(["--allow-non-worktree", "--disable-codegraph"])
        if workdir:
            flags.extend(["--cwd", workdir])
        if stream and cli_supports_flag(self.cli, "agentic", "--json-lines"):
            flags.append("--json-lines")
        return flags

    def _plan_agentic_spawn(
        self,
        request: DispatchRequest,
        *,
        stream: bool = False,
    ):
        """Build ARG_MAX-safe local agentic argv (file handoff when oversized)."""

        prompt = _safe_dispatch_prompt(request)
        workdir = request_workdir(request, self.cwd)
        mode = str((request.metadata or {}).get("compute_mode") or "implement")
        if mode not in {"implement", "analyze"}:
            mode = "implement"
        is_git = bool(workdir) and (Path(workdir) / ".git").exists()
        flags = self._agentic_flags(
            request, workdir=workdir, mode=mode, is_git=is_git, stream=stream
        )
        if stream:
            # prepend_early_job_id wraps the full command; apply after handoff plan
            # only for argv mode. File handoff uses PM python -c (no early job id
            # prefix — job id still arrives on stdout from the worker).
            handoff = plan_local_agentic_handoff(
                cli=self.cli, prompt=prompt, flags=flags
            )
            if handoff.mode == "argv":
                handoff.argv = prepend_early_job_id(list(handoff.argv))
            return handoff, workdir
        return (
            plan_local_agentic_handoff(cli=self.cli, prompt=prompt, flags=flags),
            workdir,
        )

    def _spawn_agentic_popen(self, handoff, *, workdir, child_env):
        """Popen local agentic; map E2BIG to spoken ARG_MAX Deny."""

        if not handoff.argv:
            raise OSError(spoken_arg_max_denied(detail="no puppetmaster interpreter"))
        try:
            return subprocess.Popen(
                handoff.argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=workdir,
                env=child_env,
                **popen_kwargs_for_killable_child(),
            )
        except OSError as exc:
            handoff.cleanup()
            if is_arg_max_oserror(exc):
                raise OSError(spoken_arg_max_denied(detail=str(exc)[:120])) from exc
            raise


    def _register_child(self, run_id: str, proc: Any) -> None:
        rid = (run_id or "").strip()
        if not rid or proc is None:
            return
        with self._child_lock:
            self._children[rid] = proc

    def _unregister_child(self, run_id: str, proc: Any) -> None:
        rid = (run_id or "").strip()
        if not rid:
            return
        with self._child_lock:
            current = self._children.get(rid)
            if current is proc or current is None:
                self._children.pop(rid, None)

    def cancel_receipt_for(self, run_id: str):
        """gjc-remote-shaped receipt after ``cancel`` (inspect only)."""

        rid = (run_id or "").strip()
        confirmed = self._statuses.get(rid) == TaskStatus.CANCELLED
        return cancel_receipt(confirmed=confirmed, run_id=rid)

    def _attach_gate_env(
        self, child_env: dict[str, str], request: DispatchRequest, workdir: Optional[str]
    ) -> None:
        """Stamp the live ask-gate file-queue so a PreToolUse hook can hold."""

        try:
            from agent_discord.orchestration.gate_hook import attach_gate_env

            ws = workdir or (str(self.cwd) if self.cwd else None)
            attach_gate_env(child_env, run_id=request.run_id, workspace=ws)
        except Exception:
            pass

    def _resolve_secret(self) -> str:
        if self.vault is not None:
            stored = self.vault.get("openrouter")
            if stored:
                return stored
        source = self.env if self.env is not None else os.environ
        return (source.get("OPENROUTER_API_KEY") or "").strip()
