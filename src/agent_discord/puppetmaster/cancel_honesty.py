"""Cancel honesty — kill local/SSH cooks; never paint Cancelled on a lie.

Phone Cancel must terminate the child (process group) or speak
``Cancel unconfirmed`` and leave the run non-cancelled. gjc-remote-shaped
receipts distinguish ``cancellation_pending`` from confirmed cancelled.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

CANCEL_UNCONFIRMED_SPOKEN = "Cancel unconfirmed"
CANCEL_CONFIRMED_SUMMARY = "cancelled"


@dataclass(frozen=True)
class CancelReceipt:
    """gjc-remote-shaped cancel outcome.

    ``confirmed`` means the cook child was actually interrupted.
    ``cancellation_pending`` means we asked but cannot prove the cook stopped —
    callers must not paint Done/Cancelled as success.
    """

    confirmed: bool
    cancellation_pending: bool
    spoken: str
    run_id: str = ""

    @property
    def status(self) -> str:
        return "cancelled" if self.confirmed else "cancellation_pending"

    def as_dict(self) -> dict[str, Any]:
        return {
            "confirmed": self.confirmed,
            "cancellation_pending": self.cancellation_pending,
            "spoken": self.spoken,
            "run_id": self.run_id,
            "status": self.status,
        }


def cancel_receipt(*, confirmed: bool, run_id: str = "") -> CancelReceipt:
    rid = (run_id or "").strip()
    if confirmed:
        return CancelReceipt(
            confirmed=True,
            cancellation_pending=False,
            spoken=CANCEL_CONFIRMED_SUMMARY,
            run_id=rid,
        )
    return CancelReceipt(
        confirmed=False,
        cancellation_pending=True,
        spoken=CANCEL_UNCONFIRMED_SPOKEN,
        run_id=rid,
    )


def popen_kwargs_for_killable_child() -> dict[str, Any]:
    """Kwargs so cancel can SIGTERM/SIGKILL the whole process group."""

    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if flags:
            kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    return kwargs


def process_is_alive(proc: Any) -> bool:
    if proc is None:
        return False
    poll = getattr(proc, "poll", None)
    if not callable(poll):
        return False
    try:
        return poll() is None
    except Exception:
        return False


def terminate_process_group(
    proc: Any,
    *,
    grace_seconds: float = 1.5,
    started_new_session: bool = True,
) -> bool:
    """SIGTERM then SIGKILL the child process group. True when the child is dead.

    POSIX: ``os.killpg`` when we spawned with ``start_new_session``.
    Windows: CREATE_NEW_PROCESS_GROUP + ``terminate`` / ``kill`` best-effort.
    Never raises.
    """

    if proc is None:
        return False
    if not process_is_alive(proc):
        return True
    pid = int(getattr(proc, "pid", 0) or 0)
    if pid <= 0:
        return False

    def _sigterm() -> None:
        if started_new_session and os.name == "posix":
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
        try:
            proc.terminate()
        except Exception:
            pass

    def _sigkill() -> None:
        if started_new_session and os.name == "posix":
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
        try:
            proc.kill()
        except Exception:
            pass

    try:
        _sigterm()
        deadline = time.monotonic() + max(0.05, float(grace_seconds))
        while time.monotonic() < deadline:
            if not process_is_alive(proc):
                return True
            time.sleep(0.05)
        _sigkill()
        try:
            proc.wait(timeout=2.0)
        except Exception:
            pass
        return not process_is_alive(proc)
    except Exception:
        return not process_is_alive(proc)


def ssh_controlmaster_exit(
    target: str,
    *,
    control_path: str = "",
    exec_fn: Any = None,
    timeout_seconds: float = 5.0,
) -> bool:
    """Best-effort ``ssh -O exit`` when a ControlMaster path is known."""

    tgt = (target or "").strip()
    path = (control_path or "").strip()
    if not tgt or not path:
        return False
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ControlPath={path}",
        "-O",
        "exit",
        tgt,
    ]
    try:
        if exec_fn is not None:
            proc = exec_fn(argv, timeout_seconds=float(timeout_seconds))
            return int(getattr(proc, "returncode", 1) or 0) == 0
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
            check=False,
        )
        return completed.returncode == 0
    except Exception:
        return False


def ssh_remote_signal(
    target: str,
    remote_pid: int,
    *,
    exec_fn: Any = None,
    timeout_seconds: float = 8.0,
    sig: str = "TERM",
) -> bool:
    """Best-effort remote ``kill -<sig> -<pid>`` (process group) over BatchMode ssh."""

    tgt = (target or "").strip()
    pid = int(remote_pid or 0)
    if not tgt or pid <= 0:
        return False
    # Negative pid = process group. Credentials never added.
    remote = f"kill -{sig} -{pid} 2>/dev/null || kill -{sig} {pid} 2>/dev/null || true"
    argv = ["ssh", "-o", "BatchMode=yes", tgt, remote]
    try:
        if exec_fn is not None:
            proc = exec_fn(argv, timeout_seconds=float(timeout_seconds))
            return int(getattr(proc, "returncode", 1) or 0) in {0, 1}
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
            check=False,
        )
        return completed.returncode in {0, 1}
    except Exception:
        return False


def resolve_ssh_control_path(
    *,
    explicit: str = "",
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """ControlPath for best-effort ``ssh -O exit`` (env or explicit; never secrets)."""

    path = (explicit or "").strip()
    if path:
        return path
    source = dict(os.environ if env is None else env)
    return (source.get("DISCORD_OS_SSH_CONTROL_PATH") or "").strip()




def ssh_controlmaster_check(
    target: str,
    *,
    control_path: str = "",
    exec_fn: Any = None,
    timeout_seconds: float = 5.0,
) -> bool:
    """True when ``ssh -O check`` reports a live ControlMaster for this path."""

    tgt = (target or "").strip()
    path = (control_path or "").strip()
    if not tgt or not path:
        return False
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ControlPath={path}",
        "-O",
        "check",
        tgt,
    ]
    try:
        if exec_fn is not None:
            proc = exec_fn(argv, timeout_seconds=float(timeout_seconds))
            return int(getattr(proc, "returncode", 1) or 0) == 0
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
            check=False,
        )
        return completed.returncode == 0
    except Exception:
        return False


def ensure_ssh_controlmaster_fresh(
    target: str,
    *,
    control_path: str = "",
    exec_fn: Any = None,
    timeout_seconds: float = 5.0,
) -> bool:
    """Best-effort clear a stale ControlMaster socket before Path A cook/writeback.

    When ``ssh -O check`` fails, try ``-O exit`` and unlink a literal ControlPath
    (no ssh tokens). Returns True when the master looks usable or was cleared;
    False when no path/target — callers still proceed (ControlMaster is optional).
    """

    tgt = (target or "").strip()
    path = (control_path or "").strip()
    if not tgt or not path:
        return False
    if ssh_controlmaster_check(
        tgt, control_path=path, exec_fn=exec_fn, timeout_seconds=timeout_seconds
    ):
        return True
    ssh_controlmaster_exit(
        tgt, control_path=path, exec_fn=exec_fn, timeout_seconds=timeout_seconds
    )
    # Literal paths only — never expand %r/%h/%p ourselves.
    if "%" not in path:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass
    # Cleared best-effort; cook may still start a fresh master via ControlMaster=auto.
    return True


def remote_pid_sidecar_dir(
    *,
    gate_root: Any = None,
    workspace: Any = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Directory for durable Path A remote-pid sidecars (orphan reap after Mac crash)."""

    source = dict(os.environ if env is None else env)
    explicit = (source.get("DISCORD_OS_REMOTE_PID_DIR") or "").strip()
    if explicit:
        return explicit
    if gate_root is not None:
        try:
            root = os.path.join(str(gate_root), "remote_pids")
            os.makedirs(root, mode=0o700, exist_ok=True)
            return root
        except OSError:
            pass
    if workspace is not None:
        try:
            root = os.path.join(str(workspace), ".discord-os", "remote_pids")
            os.makedirs(root, mode=0o700, exist_ok=True)
            return root
        except OSError:
            pass
    root = "/tmp/discord-os-remote-pids"
    try:
        os.makedirs(root, mode=0o700, exist_ok=True)
    except OSError:
        pass
    return root


def persist_remote_pid_sidecar(
    *,
    run_id: str,
    remote_pid: int,
    host_target: str,
    host_id: str = "",
    gate_root: Any = None,
    workspace: Any = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Write a best-effort sidecar so a crashed Mac can reap an orphaned remote pid."""

    rid = (run_id or "").strip()
    pid = int(remote_pid or 0)
    tgt = (host_target or "").strip()
    if not rid or pid <= 0 or not tgt:
        return ""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rid)[:80] or "unknown"
    folder = remote_pid_sidecar_dir(gate_root=gate_root, workspace=workspace, env=env)
    path = os.path.join(folder, f"{safe}.json")
    payload = {
        "run_id": rid,
        "remote_pid": pid,
        "host_target": tgt,
        "host_id": (host_id or "").strip(),
        "created_at_ms": int(time.time() * 1000),
    }
    try:
        import json

        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp, path)
        return path
    except OSError:
        return ""


def clear_remote_pid_sidecar(
    run_id: str,
    *,
    gate_root: Any = None,
    workspace: Any = None,
    env: Optional[Mapping[str, str]] = None,
) -> None:
    rid = (run_id or "").strip()
    if not rid:
        return
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rid)[:80] or "unknown"
    folder = remote_pid_sidecar_dir(gate_root=gate_root, workspace=workspace, env=env)
    path = os.path.join(folder, f"{safe}.json")
    try:
        os.unlink(path)
    except OSError:
        pass


def reap_orphaned_remote_pids(
    *,
    gate_root: Any = None,
    workspace: Any = None,
    exec_fn: Any = None,
    max_age_seconds: float = 6 * 3600,
    env: Optional[Mapping[str, str]] = None,
) -> list[dict[str, Any]]:
    """Best-effort kill remote pids left after a Mac crash / abrupt Path A exit.

    Scans sidecars, signals each remote pid over BatchMode ssh, then clears the
    sidecar. Never raises. Returns a list of attempt records (no secrets).
    """

    import json

    folder = remote_pid_sidecar_dir(gate_root=gate_root, workspace=workspace, env=env)
    out: list[dict[str, Any]] = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    now_ms = int(time.time() * 1000)
    max_age_ms = int(max(60.0, float(max_age_seconds)) * 1000)
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            try:
                os.unlink(path)
            except OSError:
                pass
            continue
        if not isinstance(data, dict):
            continue
        created = int(data.get("created_at_ms") or 0)
        # Skip very fresh sidecars — cook may still be live on this Mac.
        if created and (now_ms - created) < 30_000:
            continue
        if created and (now_ms - created) > max_age_ms:
            try:
                os.unlink(path)
            except OSError:
                pass
            out.append({"run_id": data.get("run_id"), "action": "expired"})
            continue
        tgt = str(data.get("host_target") or "").strip()
        pid = int(data.get("remote_pid") or 0)
        rid = str(data.get("run_id") or "").strip()
        ok = False
        if tgt and pid > 0:
            ok = bool(ssh_remote_signal(tgt, pid, exec_fn=exec_fn))
            if ok:
                # Follow with KILL best-effort for stubborn orphans.
                ssh_remote_signal(tgt, pid, exec_fn=exec_fn, sig="KILL")
        try:
            os.unlink(path)
        except OSError:
            pass
        out.append(
            {
                "run_id": rid,
                "host_id": data.get("host_id") or "",
                "remote_pid": pid,
                "signaled": ok,
                "action": "reaped" if ok else "clear",
            }
        )
    return out


LOCAL_PID_DIR_ENV = "DISCORD_OS_LOCAL_PID_DIR"


def local_pid_sidecar_dir(
    *,
    workspace: Any = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Directory for local agentic pid sidecars (orphan reap after host restart)."""

    source = dict(os.environ if env is None else env)
    explicit = (source.get(LOCAL_PID_DIR_ENV) or "").strip()
    candidates = []
    if explicit:
        candidates.append(explicit)
    if workspace is not None:
        candidates.append(os.path.join(str(workspace), "local_pids"))
    ws_env = (source.get("AGENT_DISCORD_WORKSPACE") or "").strip()
    if ws_env:
        candidates.append(os.path.join(os.path.expanduser(ws_env), "local_pids"))
    candidates.append("/tmp/discord-os-local-pids")
    for root in candidates:
        try:
            os.makedirs(root, mode=0o700, exist_ok=True)
            return root
        except OSError:
            continue
    return candidates[-1]


def _sidecar_path(folder: str, run_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in run_id)[:80]
    return os.path.join(folder, f"{safe or 'unknown'}.json")


def process_command_line(pid: int, *, ps_fn: Any = None) -> str:
    """Best-effort command line for ``pid``. Empty when it cannot be read."""

    target = int(pid or 0)
    if target <= 0:
        return ""
    if ps_fn is not None:
        try:
            return str(ps_fn(target) or "")
        except Exception:
            return ""
    try:
        completed = subprocess.run(
            ["ps", "-o", "command=", "-p", str(target)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""
    return (completed.stdout or "").strip()


_START_SKEW_MS = 5 * 60 * 1000


def _parse_etime(text: str) -> Optional[int]:
    """``ps -o etime`` ``[[dd-]hh:]mm:ss`` to seconds. None when unparseable."""

    raw = (text or "").strip()
    if not raw:
        return None
    days = 0
    if "-" in raw:
        head, _, raw = raw.partition("-")
        if not head.isdigit():
            return None
        days = int(head)
    parts = raw.split(":")
    if not all(part.isdigit() for part in parts) or not 2 <= len(parts) <= 3:
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return days * 86400 + seconds


def process_start_ms(
    pid: int, *, etime_fn: Any = None, now_ms: Optional[int] = None
) -> Optional[int]:
    """When ``pid`` started (epoch ms), from ``ps -o etime``. None when unknown."""

    target = int(pid or 0)
    if target <= 0:
        return None
    try:
        if etime_fn is not None:
            text = str(etime_fn(target) or "")
        else:
            completed = subprocess.run(
                ["ps", "-o", "etime=", "-p", str(target)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            text = completed.stdout or ""
    except Exception:
        return None
    elapsed = _parse_etime(text)
    if elapsed is None:
        return None
    base = int(now_ms if now_ms is not None else time.time() * 1000)
    return base - elapsed * 1000


def process_group_is_alive(pgid: int) -> bool:
    """True when signal 0 reaches the process group."""

    group = int(pgid or 0)
    if group <= 0 or os.name != "posix":
        return False
    try:
        os.killpg(group, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def persist_local_pid_sidecar(
    *,
    run_id: str,
    pid: int,
    pgid: int = 0,
    job_id: str = "",
    workspace: Any = None,
    env: Optional[Mapping[str, str]] = None,
    command: str = "",
) -> str:
    """Record a live local worker so a host restart can reap it. Never raises.

    Local agentic children start in their own session, so an abrupt host exit
    orphans them: they keep cooking, spending, and writing the checkout after
    the write lock is gone. Path A has had this for remote pids.
    """

    import json

    rid = (run_id or "").strip()
    child = int(pid or 0)
    if not rid or child <= 0:
        return ""
    folder = local_pid_sidecar_dir(workspace=workspace, env=env)
    path = _sidecar_path(folder, rid)
    payload = {
        "run_id": rid,
        "pid": child,
        "pgid": int(pgid or child),
        "job_id": (job_id or "").strip(),
        "command": (command or "")[:500],
        "started_at_ms": int(time.time() * 1000),
    }
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        return ""
    return path


def clear_local_pid_sidecar(
    run_id: str,
    *,
    workspace: Any = None,
    env: Optional[Mapping[str, str]] = None,
) -> None:
    rid = (run_id or "").strip()
    if not rid:
        return
    folder = local_pid_sidecar_dir(workspace=workspace, env=env)
    try:
        os.unlink(_sidecar_path(folder, rid))
    except OSError:
        pass


def reap_orphaned_local_pids(
    *,
    workspace: Any = None,
    env: Optional[Mapping[str, str]] = None,
    grace_seconds: float = 2.0,
    max_age_seconds: float = 24 * 3600,
    ps_fn: Any = None,
    killpg_fn: Any = None,
    etime_fn: Any = None,
) -> list[dict[str, Any]]:
    """Terminate local worker groups left alive by an abrupt host exit.

    A pid can be reused, so a group is only signalled when the recorded pid
    still looks like a Puppetmaster process (``ps`` command line). Mismatches
    clear the sidecar without signalling anything. Never raises; returns one
    record per sidecar so the caller can log what happened.
    """

    import json

    folder = local_pid_sidecar_dir(workspace=workspace, env=env)
    out: list[dict[str, Any]] = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    killpg = killpg_fn if killpg_fn is not None else os.killpg
    now_ms = int(time.time() * 1000)
    max_age_ms = int(max(60.0, float(max_age_seconds)) * 1000)
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            try:
                os.unlink(path)
            except OSError:
                pass
            continue
        if not isinstance(data, dict):
            continue
        rid = str(data.get("run_id") or "").strip()
        pid = int(data.get("pid") or 0)
        pgid = int(data.get("pgid") or pid)
        created = int(data.get("started_at_ms") or 0)
        record: dict[str, Any] = {
            "run_id": rid,
            "pid": pid,
            "pgid": pgid,
            "job_id": str(data.get("job_id") or ""),
        }
        if created and (now_ms - created) > max_age_ms:
            record["action"] = "expired"
        elif pgid <= 1 or pid <= 1 or pgid == os.getpgrp():
            # A corrupt sidecar must never signal init or this host's own group.
            record["action"] = "unsafe"
        elif not process_group_is_alive(pgid):
            record["action"] = "gone"
        else:
            command = process_command_line(pid, ps_fn=ps_fn)
            started = process_start_ms(pid, etime_fn=etime_fn, now_ms=now_ms)
            if "puppetmaster" not in command.lower():
                # Pid reuse (or an unreadable ps): do not signal a stranger.
                record["action"] = "not-ours"
                record["command"] = command[:200]
            elif created and (
                started is None or abs(started - created) > _START_SKEW_MS
            ):
                # Another Puppetmaster process (Marionette, an MCP worker) that
                # reused the pid started at a different time than our child.
                record["action"] = "not-ours"
                record["command"] = command[:200]
            else:
                record["action"] = "reaped"
                record["killed"] = _kill_group(killpg, pgid, grace_seconds)
        try:
            os.unlink(path)
        except OSError:
            pass
        out.append(record)
    return out


def _kill_group(killpg: Any, pgid: int, grace_seconds: float) -> bool:
    """SIGTERM the group, then SIGKILL after a grace period. True when dead."""

    try:
        killpg(pgid, signal.SIGTERM)
    except Exception:
        return False
    deadline = time.monotonic() + max(0.05, float(grace_seconds))
    while time.monotonic() < deadline:
        if not process_group_is_alive(pgid):
            return True
        time.sleep(0.05)
    try:
        killpg(pgid, signal.SIGKILL)
    except Exception:
        return False
    return not process_group_is_alive(pgid)


def wait_briefly_for_remote_pid(
    getter,
    *,
    timeout_seconds: float = 0.4,
    poll_seconds: float = 0.05,
) -> int:
    """Poll until a remote pid is known or the brief Cancel race window elapses."""

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        try:
            pid = int(getter() or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid > 0:
            return pid
        if time.monotonic() >= deadline:
            return 0
        time.sleep(max(0.01, float(poll_seconds)))

