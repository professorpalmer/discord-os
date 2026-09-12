"""Path A: real remote cook for allowlisted ``kind=ssh`` hosts.

Control-plane Mac resolves the host, then invokes the remote worker over SSH
(``BatchMode=yes``, credentials never in argv). Product compute on the remote
is Puppetmaster ``agentic`` / OpenRouter — the remote host must already have
``OPENROUTER_API_KEY`` (or vault) configured; this Mac never tunnels secrets
on argv.

Fail closed: unreachable / BatchMode failure / missing remote CLI → spoken
Deny. Never silent local cook for ``kind=ssh``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence

from agent_discord.contracts import (
    DispatchEvent,
    DispatchRequest,
    DispatchResult,
    EventKind,
    ModelPin,
    ProgressSummary,
    TaskStatus,
)
from agent_discord.host.runners import (
    HostAllowlistError,
    RemoteHost,
    host_runner_argv,
    spoken_host_deny,
)
from agent_discord.puppetmaster.backend import (
    _parse_safe_cli_completion,
    _safe_dispatch_prompt,
    usage_from_cli_meta,
)
from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN

# Doctor / spoken honesty once Path A is wired.
SSH_COOK_CAPABLE = "cook via ssh BatchMode (remote agentic)"
SSH_COOK_UNREACHABLE = "ssh unreachable / Deny"
SSH_PROBE_TIMEOUT_S = 5.0

ExecResult = Any
ExecFn = Callable[..., ExecResult]


def ssh_cook_enabled(*, env: Optional[Mapping[str, str]] = None) -> bool:
    """Kill switch: ``DISCORD_OS_SSH_COOK=0`` restores spoken Deny (no remote)."""

    source = dict(os.environ if env is None else env)
    raw = (source.get("DISCORD_OS_SSH_COOK") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "deny"}


def spoken_ssh_unreachable(host_id: str, *, detail: str = "") -> str:
    why = SSH_COOK_UNREACHABLE
    bit = (detail or "").strip()
    if bit:
        why = f"{why}: {bit}"
    return spoken_host_deny(host_id, reason=why)


def spoken_ssh_cook_disabled(host_id: str) -> str:
    return spoken_host_deny(
        host_id,
        reason="routing only / Deny until remote cook (DISCORD_OS_SSH_COOK=0)",
    )


def probe_ssh_host(
    host: RemoteHost,
    *,
    exec_fn: Optional[ExecFn] = None,
    timeout_seconds: float = SSH_PROBE_TIMEOUT_S,
) -> tuple[bool, str]:
    """Return ``(ok, detail)``. Soft probe for doctor + pre-cook gate."""

    kind = (host.kind or "").strip().lower()
    if kind != "ssh":
        return False, f"not ssh (kind={host.kind!r})"
    target = (host.target or "").strip()
    if not target:
        return False, "missing ssh target"
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(1, int(timeout_seconds))}",
        target,
        "true",
    ]
    try:
        proc = _run_exec(argv, exec_fn=exec_fn, timeout_seconds=timeout_seconds)
    except Exception as exc:  # noqa: BLE001 — probe must never raise to doctor
        return False, str(exc)[:160]
    code = int(getattr(proc, "returncode", 1) or 0)
    if code == 0:
        return True, SSH_COOK_CAPABLE
    err = (
        str(getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "")
        .strip()
        .splitlines()
    )
    detail = (err[0] if err else f"exit {code}")[:160]
    return False, detail or f"exit {code}"


def build_remote_agentic_argv(
    request: DispatchRequest,
    *,
    cli: str = "puppetmaster",
    pin: Optional[ModelPin] = None,
    timeout_seconds: float = 3600.0,
    remote_cwd: str = "",
) -> list[str]:
    """Remote argv for ``puppetmaster agentic`` (no secrets)."""

    model = pin or AGENTIC_MODEL_PIN
    prompt = _safe_dispatch_prompt(request)
    mode = str((request.metadata or {}).get("compute_mode") or "implement")
    if mode not in {"implement", "analyze"}:
        mode = "implement"
    command = [
        cli,
        "agentic",
        prompt,
        "--provider",
        "openrouter",
        "--model",
        model.adapter_name or model.canonical,
        "--mode",
        mode,
        "--timeout-seconds",
        str(int(timeout_seconds)),
    ]
    if mode == "implement":
        command.append("--allow-dirty")
        command.append("--allow-non-worktree")
    else:
        command.extend(["--allow-non-worktree", "--disable-codegraph"])
    cwd = (remote_cwd or "").strip()
    if not cwd:
        cwd = str((request.metadata or {}).get("host_workdir") or "").strip()
    if cwd:
        command.extend(["--cwd", cwd])
    return command


def run_ssh_remote_cook(
    host: RemoteHost,
    remote_command: Sequence[str],
    *,
    exec_fn: Optional[ExecFn] = None,
    timeout_seconds: float = 3600.0,
) -> ExecResult:
    """Invoke ``host_runner_argv`` then run. Credentials never added here."""

    argv = host_runner_argv(host, remote_command)
    return _run_exec(argv, exec_fn=exec_fn, timeout_seconds=timeout_seconds)


def _run_exec(
    argv: Sequence[str],
    *,
    exec_fn: Optional[ExecFn],
    timeout_seconds: float,
) -> ExecResult:
    fn = exec_fn
    if fn is None:
        fn = _default_exec
    return fn(list(argv), timeout_seconds=float(timeout_seconds))


def _default_exec(argv: list[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _is_ssh_transport_failure(proc: ExecResult) -> bool:
    code = int(getattr(proc, "returncode", 1) or 0)
    text = (
        f"{getattr(proc, 'stderr', '') or ''}\n{getattr(proc, 'stdout', '') or ''}"
    ).lower()
    markers = (
        "permission denied",
        "connection refused",
        "connection timed out",
        "could not resolve",
        "no route to host",
        "network is unreachable",
        "host key verification failed",
        "operation timed out",
        "connection reset",
        "banner exchange",
    )
    if any(marker in text for marker in markers):
        return True
    # ssh itself usually exits 255 on transport failure
    if code == 255:
        return True
    return False


@dataclass
class SshRemoteCookBackend:
    """Puppetmaster-shaped backend that cooks only via SSH (never local)."""

    host: RemoteHost
    cli: str = "puppetmaster"
    pin: ModelPin = field(default_factory=lambda: AGENTIC_MODEL_PIN)
    timeout_seconds: float = 3600.0
    exec_fn: Optional[ExecFn] = None
    probe_first: bool = True
    _statuses: dict[str, TaskStatus] = field(default_factory=dict)

    def resolve_model(self, requested: str) -> ModelPin:
        self.pin.assert_allowed(requested)
        return self.pin

    def available(self) -> bool:
        # Local ssh binary is required; remote puppetmaster is probed at cook time.
        return shutil.which("ssh") is not None

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        self._statuses[request.run_id] = TaskStatus.RUNNING
        deny = self._preflight_deny()
        if deny:
            self._statuses[request.run_id] = TaskStatus.FAILED
            return self._deny_result(request.run_id, deny)

        remote_cmd = build_remote_agentic_argv(
            request,
            cli=self.cli,
            pin=self.pin,
            timeout_seconds=self.timeout_seconds,
            remote_cwd=str((request.metadata or {}).get("host_workdir") or ""),
        )
        try:
            proc = run_ssh_remote_cook(
                self.host,
                remote_cmd,
                exec_fn=self.exec_fn,
                timeout_seconds=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._statuses[request.run_id] = TaskStatus.FAILED
            return self._deny_result(
                request.run_id,
                spoken_ssh_unreachable(self.host.id, detail=str(exc)[:160]),
            )

        if _is_ssh_transport_failure(proc):
            self._statuses[request.run_id] = TaskStatus.FAILED
            detail = (
                str(getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "")
                .strip()
                .splitlines()
            )
            bit = detail[0] if detail else f"exit {getattr(proc, 'returncode', '?')}"
            return self._deny_result(
                request.run_id,
                spoken_ssh_unreachable(self.host.id, detail=bit[:160]),
            )

        safe_meta = _parse_safe_cli_completion(
            str(getattr(proc, "stdout", "") or ""),
            str(getattr(proc, "stderr", "") or ""),
        )
        code = int(getattr(proc, "returncode", 1) or 0)
        if code != 0:
            self._statuses[request.run_id] = TaskStatus.FAILED
            err = (
                safe_meta.get("error")
                or str(getattr(proc, "stderr", "") or "").strip()
                or f"remote exit {code}"
            )
            # Missing remote CLI / agentic → spoken Deny (fail closed, no local).
            lower = str(err).lower()
            if "not found" in lower or "no such file" in lower:
                return self._deny_result(
                    request.run_id,
                    spoken_host_deny(
                        self.host.id,
                        reason="remote agentic CLI missing / Deny",
                    ),
                )
            return DispatchResult(
                run_id=request.run_id,
                status=TaskStatus.FAILED,
                events=(
                    DispatchEvent(
                        kind=EventKind.ERROR,
                        summary=ProgressSummary(stage="dispatch", message=str(err)[:500]),
                    ),
                ),
                final_summary="remote cook failed",
                error=str(err)[:500],
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
                        message=(
                            f"dispatched via ssh/{self.host.id} "
                            f"agentic with {self.pin.adapter_name}"
                        ),
                        details={
                            "model": self.pin.canonical,
                            "host_id": self.host.id,
                            "host_kind": "ssh",
                        },
                    ),
                ),
                DispatchEvent(
                    kind=EventKind.RECEIPT,
                    summary=ProgressSummary(
                        stage="done", message=summary, percent=100.0
                    ),
                    payload=safe_meta,
                ),
            ),
            final_summary=summary,
            usage=usage_from_cli_meta(self.pin, self.cli, safe_meta),
        )

    def stream(self, request: DispatchRequest) -> Iterator[DispatchEvent]:
        """MVP: one-shot SSH cook; yield dispatch then receipt/error (no live tokens)."""

        result = self.dispatch(request)
        for event in result.events:
            yield event

    def cancel(self, run_id: str) -> bool:
        return False

    def status(self, run_id: str) -> TaskStatus:
        return self._statuses.get(run_id, TaskStatus.PENDING)

    def _preflight_deny(self) -> str:
        if not ssh_cook_enabled():
            return spoken_ssh_cook_disabled(self.host.id)
        if (self.host.kind or "").strip().lower() != "ssh":
            return spoken_host_deny(
                self.host.id,
                reason=f"has unknown kind {self.host.kind!r}",
            )
        if not (self.host.target or "").strip():
            return spoken_host_deny(self.host.id, reason="missing ssh target")
        if self.probe_first:
            ok, detail = probe_ssh_host(
                self.host, exec_fn=self.exec_fn, timeout_seconds=SSH_PROBE_TIMEOUT_S
            )
            if not ok:
                return spoken_ssh_unreachable(self.host.id, detail=detail)
        if not self.available() and self.exec_fn is None:
            return spoken_ssh_unreachable(self.host.id, detail="ssh binary missing")
        return ""

    def _deny_result(self, run_id: str, spoken: str) -> DispatchResult:
        return DispatchResult(
            run_id=run_id,
            status=TaskStatus.FAILED,
            events=(
                DispatchEvent(
                    kind=EventKind.ERROR,
                    summary=ProgressSummary(stage="deny", message=spoken),
                ),
            ),
            final_summary=spoken,
            error=spoken,
        )


def make_ssh_cook_backend(
    host: RemoteHost,
    *,
    exec_fn: Optional[ExecFn] = None,
    cli: str = "puppetmaster",
    timeout_seconds: float = 3600.0,
) -> SshRemoteCookBackend:
    return SshRemoteCookBackend(
        host=host,
        cli=cli,
        exec_fn=exec_fn,
        timeout_seconds=timeout_seconds,
    )


def assert_ssh_remote_cook_ready(
    host: Optional[RemoteHost],
    *,
    exec_fn: Optional[ExecFn] = None,
    env: Optional[Mapping[str, str]] = None,
) -> None:
    """Raise ``HostAllowlistError`` (spoken Deny) when ssh cook cannot run.

    ``None`` / ``kind=local`` are no-ops (local path). Unknown kinds Deny.
    """

    if host is None:
        return
    kind = (host.kind or "").strip().lower()
    if kind == "local" or kind == "path":
        return
    if kind != "ssh":
        raise HostAllowlistError(
            spoken_host_deny(host.id, reason=f"has unknown kind {host.kind!r}"),
            host_id=host.id,
        )
    if not ssh_cook_enabled(env=env):
        raise HostAllowlistError(
            spoken_ssh_cook_disabled(host.id),
            host_id=host.id,
        )
    if not (host.target or "").strip():
        raise HostAllowlistError(
            spoken_host_deny(host.id, reason="missing ssh target"),
            host_id=host.id,
        )
    ok, detail = probe_ssh_host(host, exec_fn=exec_fn)
    if not ok:
        raise HostAllowlistError(
            spoken_ssh_unreachable(host.id, detail=detail),
            host_id=host.id,
        )
