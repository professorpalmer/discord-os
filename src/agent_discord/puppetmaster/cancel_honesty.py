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

