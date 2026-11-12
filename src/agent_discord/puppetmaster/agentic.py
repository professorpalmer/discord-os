"""Puppetmaster agentic backend — OpenRouter/BYOK via subprocess env only."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from agent_discord.puppetmaster.cancel_honesty import (
    cancel_receipt,
    clear_local_pid_sidecar,
    persist_local_pid_sidecar,
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
    PM_MODELS_PATH_ENV,
    confine_worker_cwd,
    ensure_worker_registry,
    iter_cli_process_events,
    measured_job_usage,
    prepend_early_job_id,
    request_workdir,
    with_state_dir,
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
    # Host state dir (.agent-discord): never a worker cwd; owns gates/.
    workspace: Optional[str | Path] = None
    timeout_seconds: float = 3600.0
    vault: Optional[KeyVault] = None
    env: Optional[Mapping[str, str]] = None
    _statuses: dict[str, TaskStatus] = field(default_factory=dict)
    _children: dict[str, Any] = field(default_factory=dict, repr=False)
    _cancel_requested: set[str] = field(default_factory=set, repr=False)
    # run_id -> Puppetmaster job id, known once the worker prints job_id:.
    _job_ids: dict[str, str] = field(default_factory=dict, repr=False)
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
        # Presence check on an already-picked executable: `self.cli` comes from
        # config.resolve_puppetmaster_cli, the one resolver. Do not re-resolve
        # here, or the backend could run a different CLI than it reports.
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

        child_env = self._worker_child_env(request)

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

        child_env = self._worker_child_env(request)

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
                on_job_id=lambda job_id: self._note_job_id(request.run_id, job_id),
            ):
                if event.kind == EventKind.RECEIPT:
                    event = self._with_measured_usage(
                        event, self._job_ids.get(request.run_id, "")
                    )
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
            self._job_ids.pop(request.run_id, None)
            handoff.cleanup()

    def _with_measured_usage(self, event: DispatchEvent, job_id: str) -> DispatchEvent:
        """Attach Puppetmaster's measured tokens and cost to the final receipt."""

        measured = measured_job_usage(self.cli, job_id, env=self.env)
        if not measured:
            return event
        payload = dict(event.payload or {})
        nested = payload.get("usage")
        payload["usage"] = {**(dict(nested) if isinstance(nested, Mapping) else {}), **measured}
        payload.setdefault("job_id", job_id)
        return replace(event, payload=payload)

    def steer(self, run_id: str, text: str) -> bool:
        """Deliver a follow-up to the live worker via ``puppetmaster steer``.

        False until the worker's job id is known, or when the CLI refuses.
        """

        job_id = self._job_ids.get((run_id or "").strip(), "")
        body = (text or "").strip()
        if not job_id or not body:
            return False
        try:
            proc = subprocess.run(
                with_state_dir([self.cli, "steer", job_id, body]),
                capture_output=True,
                text=True,
                timeout=30,
                env=worker_env(self.env),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0

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
        # No --json-lines: no Puppetmaster release has that flag. Token events
        # come from `deltas --follow --json` (see backend.iter_cli_process_events).
        return flags

    def _plan_agentic_spawn(
        self,
        request: DispatchRequest,
        *,
        stream: bool = False,
    ):
        """Build ARG_MAX-safe local agentic argv (file handoff when oversized)."""

        prompt = _safe_dispatch_prompt(request)
        workdir = confine_worker_cwd(
            request_workdir(request, self.cwd),
            workspace=self._host_workspace(),
            env=self.env,
        )
        mode = str((request.metadata or {}).get("compute_mode") or "implement")
        if mode not in {"implement", "analyze"}:
            mode = "implement"
        is_git = bool(workdir) and (Path(workdir) / ".git").exists()
        flags = self._agentic_flags(
            request, workdir=workdir, mode=mode, is_git=is_git, stream=stream
        )
        if stream:
            # Both shapes ask for the job id up front, or live steer and deltas
            # never start: argv mode via prepend_early_job_id, file mode baked
            # into the bridge before the subcommand.
            handoff = plan_local_agentic_handoff(
                cli=self.cli, prompt=prompt, flags=flags, early_job_id=True
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
        argv = self._sandboxed_argv(list(handoff.argv), workdir=workdir, child_env=child_env)
        try:
            return subprocess.Popen(
                argv,
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


    def _worker_child_env(self, request: DispatchRequest) -> dict[str, str]:
        """Allowlisted env, the provider key, gate stamps, and the model registry."""

        child_env = worker_env(self.env)
        secret = self._resolve_secret()
        if secret:
            child_env["OPENROUTER_API_KEY"] = secret
        self._attach_gate_env(child_env, request)
        if not str(child_env.get(PM_MODELS_PATH_ENV) or "").strip():
            child_env[PM_MODELS_PATH_ENV] = ensure_worker_registry(
                child_env["PUPPETMASTER_STATE_DIR"],
                self.pin.adapter_name or self.pin.canonical,
            )
        return child_env

    def _sandboxed_argv(
        self, argv: list[str], *, workdir: Any, child_env: Mapping[str, str]
    ) -> list[str]:
        """Wrap the worker in the OS sandbox unless it is off or unavailable."""

        from agent_discord.puppetmaster.sandbox import (
            sandbox_enabled,
            worker_profile,
            wrap_argv,
        )

        # The host env decides: worker_env does not carry DISCORD_OS_SANDBOX.
        host_env = dict(os.environ)
        host_env.update(self.env or {})
        if not workdir or not sandbox_enabled(host_env):
            return argv
        state = str(child_env.get("PUPPETMASTER_STATE_DIR") or "").strip()
        if state:
            # The worker cannot create it: its parent is the hidden workspace.
            Path(state).mkdir(parents=True, exist_ok=True)
        runtime: list[Path] = [Path.cwd() / ".env"]
        workspace = self._host_workspace()
        if workspace is not None:
            runtime.extend([workspace, workspace.parent / ".env"])
        profile = worker_profile(workdir=workdir, child_env=child_env, runtime_dirs=runtime)
        return wrap_argv(argv, profile)

    def _register_child(self, run_id: str, proc: Any) -> None:
        rid = (run_id or "").strip()
        if not rid or proc is None:
            return
        with self._child_lock:
            self._children[rid] = proc
        self._write_pid_sidecar(rid, proc)

    def _unregister_child(self, run_id: str, proc: Any) -> None:
        rid = (run_id or "").strip()
        if not rid:
            return
        with self._child_lock:
            current = self._children.get(rid)
            if current is proc or current is None:
                self._children.pop(rid, None)
        clear_local_pid_sidecar(rid, workspace=self._host_workspace(), env=self.env)

    def _write_pid_sidecar(self, run_id: str, proc: Any = None) -> None:
        """Durable record of the live worker group, for reap after a host restart."""

        rid = (run_id or "").strip()
        if not rid:
            return
        with self._child_lock:
            child = proc if proc is not None else self._children.get(rid)
        pid = int(getattr(child, "pid", 0) or 0)
        if pid <= 0:
            return
        # Spawned with start_new_session, so the group leader is the child.
        pgid = pid
        if os.name == "posix":
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid
        try:
            persist_local_pid_sidecar(
                run_id=rid,
                pid=pid,
                pgid=pgid,
                job_id=self._job_ids.get(rid, ""),
                workspace=self._host_workspace(),
                env=self.env,
                command=f"puppetmaster agentic ({self.cli})",
            )
        except Exception:
            pass

    def _note_job_id(self, run_id: str, job_id: str) -> None:
        """Remember the PM job id and fold it into the pid sidecar."""

        rid = (run_id or "").strip()
        ident = (job_id or "").strip()
        if not rid or not ident:
            return
        self._job_ids[rid] = ident
        self._write_pid_sidecar(rid)

    def cancel_receipt_for(self, run_id: str):
        """gjc-remote-shaped receipt after ``cancel`` (inspect only)."""

        rid = (run_id or "").strip()
        confirmed = self._statuses.get(rid) == TaskStatus.CANCELLED
        return cancel_receipt(confirmed=confirmed, run_id=rid)

    def _attach_gate_env(self, child_env: dict[str, str], request: DispatchRequest) -> None:
        """Stamp the live ask-gate file-queue so a PreToolUse hook can hold.

        The queue lives under the host workspace, where listen drains it. Never
        under the worker's checkout: listen would not see it, and the worker
        could write its own results there.
        """

        try:
            from agent_discord.orchestration.gate_hook import attach_gate_env

            attach_gate_env(
                child_env, run_id=request.run_id, workspace=self._host_workspace()
            )
        except Exception:
            pass

    def _host_workspace(self) -> Optional[Path]:
        if self.workspace:
            return Path(self.workspace)
        source = self.env if self.env is not None else os.environ
        raw = str(source.get("AGENT_DISCORD_WORKSPACE") or "").strip()
        return Path(raw) if raw else None

    def _resolve_secret(self) -> str:
        if self.vault is not None:
            stored = self.vault.get("openrouter")
            if stored:
                return stored
        source = self.env if self.env is not None else os.environ
        return (source.get("OPENROUTER_API_KEY") or "").strip()
