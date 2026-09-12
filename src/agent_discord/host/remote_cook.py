"""Path A: real remote cook for allowlisted ``kind=ssh`` hosts.

Control-plane Mac resolves the host, then invokes the remote worker over SSH
(``BatchMode=yes``, credentials never in argv). Product compute on the remote
is Puppetmaster ``agentic`` / OpenRouter — the remote host must already have
``OPENROUTER_API_KEY`` (or vault) configured; this Mac never tunnels secrets
on argv.

``stream()`` pipes remote agentic stdout/stderr into live Discord PROGRESS
(same line parsers as local agentic). Fail closed: unreachable / BatchMode
failure / missing remote CLI → spoken Deny. Never silent local cook for
``kind=ssh``.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence

from agent_discord.puppetmaster.cancel_honesty import (
    cancel_receipt,
    popen_kwargs_for_killable_child,
    process_is_alive,
    ssh_controlmaster_exit,
    ssh_remote_signal,
    terminate_process_group,
)

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
    TokenStreamBuffer,
    _completion_summary,
    _event_from_cli_line,
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


def _default_popen(argv: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_kwargs_for_killable_child(),
    )


def wrap_remote_command_with_pid_echo(remote_command: Sequence[str]) -> list[str]:
    """Prefix remote argv so the first stdout line is ``DISCORD_OS_REMOTE_PID=<pid>``.

    Lets Path A cancel signal the remote process group without credentials in argv.
    """

    import shlex

    inner = " ".join(shlex.quote(str(part)) for part in remote_command)
    # bash -lc so $$ is the remote shell pid (process group leader under ssh).
    return ["bash", "-lc", f"echo DISCORD_OS_REMOTE_PID=$$; exec {inner}"]


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
    control_path: str = ""
    popen_fn: Optional[Callable[[list[str]], Any]] = None
    _statuses: dict[str, TaskStatus] = field(default_factory=dict)
    _children: dict[str, Any] = field(default_factory=dict, repr=False)
    _remote_pids: dict[str, int] = field(default_factory=dict, repr=False)
    _cancel_requested: set[str] = field(default_factory=set, repr=False)
    _child_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def resolve_model(self, requested: str) -> ModelPin:
        self.pin.assert_allowed(requested)
        return self.pin

    def available(self) -> bool:
        # Local ssh binary is required; remote puppetmaster is probed at cook time.
        return shutil.which("ssh") is not None

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        """Collect live Path A stream events into a single result (Cancel-safe)."""

        events = tuple(self.stream(request))
        status = self._statuses.get(request.run_id, TaskStatus.FAILED)
        final_summary = ""
        error: Optional[str] = None
        usage = None
        for event in events:
            if event.kind == EventKind.RECEIPT:
                final_summary = event.summary.message
                if isinstance(event.payload, dict) and event.payload:
                    usage = usage_from_cli_meta(self.pin, self.cli, event.payload)
            elif event.kind == EventKind.ERROR:
                error = event.summary.message
                if not final_summary:
                    final_summary = error
            elif event.kind == EventKind.CANCEL_REQUESTED:
                final_summary = "cancelled"
                error = "cancelled"
        if status == TaskStatus.CANCELLED:
            final_summary = final_summary or "cancelled"
            error = error or "cancelled"
        elif status == TaskStatus.COMPLETED:
            final_summary = final_summary or "completed"
        elif status == TaskStatus.FAILED and not final_summary:
            final_summary = error or "remote cook failed"
        return DispatchResult(
            run_id=request.run_id,
            status=status,
            events=events,
            final_summary=final_summary,
            error=error,
            usage=usage,
        )

    def stream(self, request: DispatchRequest) -> Iterator[DispatchEvent]:
        """Live SSH progress pipe: DISPATCH → PROGRESS… → RECEIPT/ERROR/CANCEL.

        Parses remote agentic stdout/stderr the same way local agentic does
        (NDJSON / progress / prose). Never silent local cook. Cancel honesty
        unchanged (tracked Popen + remote pid echo + ControlMaster).
        """

        self._statuses[request.run_id] = TaskStatus.RUNNING
        deny = self._preflight_deny()
        if deny:
            self._statuses[request.run_id] = TaskStatus.FAILED
            yield DispatchEvent(
                kind=EventKind.ERROR,
                summary=ProgressSummary(stage="deny", message=deny),
            )
            return

        remote_cmd = build_remote_agentic_argv(
            request,
            cli=self.cli,
            pin=self.pin,
            timeout_seconds=self.timeout_seconds,
            remote_cwd=str((request.metadata or {}).get("host_workdir") or ""),
        )
        wrapped = wrap_remote_command_with_pid_echo(remote_cmd)
        try:
            proc = self._spawn_ssh_cook(wrapped)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._statuses[request.run_id] = TaskStatus.FAILED
            spoken = spoken_ssh_unreachable(self.host.id, detail=str(exc)[:160])
            yield DispatchEvent(
                kind=EventKind.ERROR,
                summary=ProgressSummary(stage="deny", message=spoken),
            )
            return

        self._register_child(request.run_id, proc)
        try:
            yield DispatchEvent(
                kind=EventKind.DISPATCH,
                summary=ProgressSummary(
                    stage="dispatch",
                    message=(
                        f"dispatched via ssh/{self.host.id} "
                        f"agentic with {self.pin.adapter_name}"
                    ),
                    percent=2.0,
                    details={
                        "model": self.pin.canonical,
                        "host_id": self.host.id,
                        "host_kind": "ssh",
                    },
                ),
            )
            for event in self._iter_ssh_cook_events(request.run_id, proc):
                if request.run_id in self._cancel_requested:
                    self._statuses[request.run_id] = TaskStatus.CANCELLED
                    yield DispatchEvent(
                        kind=EventKind.CANCEL_REQUESTED,
                        summary=ProgressSummary(
                            stage="cancelled", message="cancelled"
                        ),
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

    def cancel(self, run_id: str) -> bool:
        rid = (run_id or "").strip()
        if not rid:
            return False
        with self._child_lock:
            self._cancel_requested.add(rid)
            proc = self._children.get(rid)
            remote_pid = int(self._remote_pids.get(rid) or 0)
        if proc is None:
            return False
        # Prefer remote interrupt first so OpenRouter stops cooking, then local ssh.
        if remote_pid > 0:
            ssh_remote_signal(
                self.host.target,
                remote_pid,
                exec_fn=self.exec_fn,
            )
        if self.control_path:
            ssh_controlmaster_exit(
                self.host.target,
                control_path=self.control_path,
                exec_fn=self.exec_fn,
            )
        local_ok = terminate_process_group(proc, started_new_session=True)
        confirmed = bool(local_ok) or (not process_is_alive(proc))
        if confirmed:
            self._statuses[rid] = TaskStatus.CANCELLED
        return bool(confirmed)

    def cancel_receipt_for(self, run_id: str):
        rid = (run_id or "").strip()
        confirmed = self._statuses.get(rid) == TaskStatus.CANCELLED
        return cancel_receipt(confirmed=confirmed, run_id=rid)

    def status(self, run_id: str) -> TaskStatus:
        return self._statuses.get(run_id, TaskStatus.PENDING)

    def _spawn_ssh_cook(self, remote_command: Sequence[str]) -> Any:
        from agent_discord.host.runners import host_runner_argv

        argv = host_runner_argv(self.host, remote_command)
        if self.popen_fn is not None:
            return self.popen_fn(list(argv))
        if self.exec_fn is not None:
            # Test harnesses inject blocking exec_fn — wrap as a fake live child.
            return _ExecFnChild(self.exec_fn, list(argv), self.timeout_seconds)
        return _default_popen(list(argv))

    def _iter_ssh_cook_events(
        self, run_id: str, proc: Any
    ) -> Iterator[DispatchEvent]:
        """Drain SSH child stdout/stderr into live PROGRESS, then terminal event.

        Captures ``DISCORD_OS_REMOTE_PID`` for Cancel. Does not follow local
        ``puppetmaster deltas`` (remote job is not on this Mac).
        """

        model = self.pin.canonical
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        deadline = time.monotonic() + float(self.timeout_seconds)
        token_buffer = TokenStreamBuffer()
        has_pipes = (
            getattr(proc, "stdout", None) is not None
            or getattr(proc, "stderr", None) is not None
        )

        def _note_remote_pid(line: str) -> bool:
            if "DISCORD_OS_REMOTE_PID=" not in line:
                return False
            try:
                raw = line.strip().split("DISCORD_OS_REMOTE_PID=", 1)[1]
                pid = int(raw.split()[0])
            except (TypeError, ValueError, IndexError):
                return True
            if pid > 0:
                with self._child_lock:
                    self._remote_pids[run_id] = pid
            return True

        if has_pipes:
            line_queue: queue.Queue[Any] = queue.Queue()
            main_done = 0

            def _reader(pipe: Any, sink: list[str]) -> None:
                try:
                    if pipe is None:
                        return
                    for line in iter(pipe.readline, ""):
                        sink.append(line)
                        line_queue.put(line)
                except Exception:
                    pass
                finally:
                    line_queue.put("__main_done__")

            for pipe, sink in (
                (getattr(proc, "stdout", None), stdout_chunks),
                (getattr(proc, "stderr", None), stderr_chunks),
            ):
                threading.Thread(
                    target=_reader, args=(pipe, sink), daemon=True
                ).start()

            while True:
                try:
                    item = line_queue.get(timeout=0.05)
                except queue.Empty:
                    if run_id in self._cancel_requested:
                        break
                    if time.monotonic() > deadline:
                        terminate_process_group(proc, started_new_session=True)
                        break
                    if not process_is_alive(proc) and main_done >= 2:
                        break
                    continue
                if item == "__main_done__":
                    main_done += 1
                    if not process_is_alive(proc) and main_done >= 2:
                        break
                    continue
                line = str(item)
                if _note_remote_pid(line):
                    continue
                if run_id in self._cancel_requested:
                    break
                event = _event_from_cli_line(line, model, token_buffer)
                if event is not None:
                    # Tag Path A origin without leaking secrets.
                    details = dict(event.summary.details or {})
                    details.setdefault("host_id", self.host.id)
                    details.setdefault("host_kind", "ssh")
                    yield DispatchEvent(
                        kind=event.kind,
                        summary=ProgressSummary(
                            stage=event.summary.stage,
                            message=event.summary.message,
                            percent=event.summary.percent,
                            details=details,
                        ),
                        payload=event.payload,
                    )
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        else:
            # Fake/_ExecFnChild: blocking communicate — no live lines.
            communicate = getattr(proc, "communicate", None)
            if callable(communicate):
                try:
                    out, err = communicate(timeout=self.timeout_seconds)
                except TypeError:
                    out, err = communicate()
                except subprocess.TimeoutExpired:
                    terminate_process_group(proc, started_new_session=True)
                    out, err = "", ""
                text_out = str(out or "")
                for line in text_out.splitlines(keepends=True):
                    stdout_chunks.append(line)
                    _note_remote_pid(line)
                stderr_chunks.append(str(err or ""))

        if run_id in self._cancel_requested:
            return

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        view = _ProcView(
            returncode=int(getattr(proc, "returncode", 1) or 0),
            stdout=stdout,
            stderr=stderr,
        )
        if _is_ssh_transport_failure(view):
            detail = (stderr or stdout).strip().splitlines()
            bit = detail[0] if detail else f"exit {view.returncode}"
            spoken = spoken_ssh_unreachable(self.host.id, detail=bit[:160])
            yield DispatchEvent(
                kind=EventKind.ERROR,
                summary=ProgressSummary(stage="deny", message=spoken),
            )
            return

        safe_meta = _parse_safe_cli_completion(stdout, stderr)
        code = int(view.returncode)
        if code != 0:
            err = (
                safe_meta.get("error")
                or stderr.strip()
                or f"remote exit {code}"
            )
            lower = str(err).lower()
            if "not found" in lower or "no such file" in lower:
                spoken = spoken_host_deny(
                    self.host.id,
                    reason="remote agentic CLI missing / Deny",
                )
                yield DispatchEvent(
                    kind=EventKind.ERROR,
                    summary=ProgressSummary(stage="deny", message=spoken),
                )
                return
            yield DispatchEvent(
                kind=EventKind.ERROR,
                summary=ProgressSummary(stage="dispatch", message=str(err)[:500]),
            )
            return

        summary = _completion_summary(safe_meta, token_buffer, self.cli)
        if isinstance(safe_meta, dict):
            safe_meta["summary"] = summary
        yield DispatchEvent(
            kind=EventKind.RECEIPT,
            summary=ProgressSummary(stage="done", message=summary, percent=100.0),
            payload=safe_meta,
        )

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
            self._remote_pids.pop(rid, None)

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


@dataclass
class _ProcView:
    returncode: int = 1
    stdout: str = ""
    stderr: str = ""


class _ExecFnChild:
    """Adapter so tests that inject ``exec_fn`` still look like a killable child."""

    def __init__(self, exec_fn: ExecFn, argv: list[str], timeout_seconds: float) -> None:
        self._exec_fn = exec_fn
        self._argv = list(argv)
        self._timeout = float(timeout_seconds)
        self.pid = 0
        self.returncode: Optional[int] = None
        self.stdout = None
        self.stderr = None
        self._result: Any = None
        self._killed = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._result = self._exec_fn(self._argv, timeout_seconds=self._timeout)
        except Exception as exc:  # noqa: BLE001
            self._result = _ProcView(returncode=1, stderr=str(exc))
        with self._lock:
            if self._killed:
                self.returncode = -9
            else:
                self.returncode = int(getattr(self._result, "returncode", 1) or 0)

    def poll(self) -> Optional[int]:
        return self.returncode

    def terminate(self) -> None:
        with self._lock:
            self._killed = True
            if self.returncode is None:
                self.returncode = -15

    def kill(self) -> None:
        self.terminate()
        with self._lock:
            self.returncode = -9

    def wait(self, timeout: Optional[float] = None) -> int:
        self._thread.join(timeout=timeout)
        if self.returncode is None:
            self.returncode = -9
        return int(self.returncode)

    def communicate(self, timeout: Optional[float] = None) -> tuple[str, str]:
        self._thread.join(timeout=timeout if timeout is not None else self._timeout)
        result = self._result or _ProcView()
        if self.returncode is None:
            self.returncode = int(getattr(result, "returncode", 1) or 0)
        return str(getattr(result, "stdout", "") or ""), str(getattr(result, "stderr", "") or "")


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
