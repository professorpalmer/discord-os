"""Login-item helper so On/Off in Discord work after reboot. Best-effort."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


SERVICE_LABEL = "com.discord-os.host"
DOCTOR_NOTIFY_LABEL = "com.discord-os.doctor-notify"
SERVICE_ENV = "DISCORD_OS_SERVICE"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"


def systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "discord-os-host.service"


def windows_startup_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "discord-os-host.vbs"
    )


def render_launchd_plist(
    *,
    argv: list[str],
    workspace: Path,
    cwd: Path,
    log: Path,
) -> str:
    args = "\n".join(f"      <string>{_xml(item)}</string>" for item in argv)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "  <key>Label</key>\n"
        f"  <string>{SERVICE_LABEL}</string>\n"
        "  <key>RunAtLoad</key>\n"
        "  <true/>\n"
        "  <key>KeepAlive</key>\n"
        "  <true/>\n"
        "  <key>WorkingDirectory</key>\n"
        f"  <string>{_xml(str(cwd))}</string>\n"
        "  <key>EnvironmentVariables</key>\n"
        "  <dict>\n"
        f"    <key>{SERVICE_ENV}</key>\n"
        "    <string>1</string>\n"
        "    <key>PYTHONUNBUFFERED</key>\n"
        "    <string>1</string>\n"
        "    <key>AGENT_DISCORD_WORKSPACE</key>\n"
        f"    <string>{_xml(str(workspace))}</string>\n"
        "  </dict>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        f"{args}\n"
        "  </array>\n"
        "  <key>StandardOutPath</key>\n"
        f"  <string>{_xml(str(log))}</string>\n"
        "  <key>StandardErrorPath</key>\n"
        f"  <string>{_xml(str(log))}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def render_systemd_unit(
    *,
    argv: list[str],
    workspace: Path,
    cwd: Path,
    log: Path,
) -> str:
    exec_start = " ".join(_quote(part) for part in argv)
    return (
        "[Unit]\n"
        "Description=Discord OS host\n"
        "[Service]\n"
        f"WorkingDirectory={cwd}\n"
        f"Environment={SERVICE_ENV}=1\n"
        f"Environment=AGENT_DISCORD_WORKSPACE={workspace}\n"
        f"ExecStart={exec_start}\n"
        "Restart=always\n"
        f"StandardOutput=append:{log}\n"
        f"StandardError=append:{log}\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def render_windows_vbs(*, argv: list[str]) -> str:
    command = " ".join(_vbs_quote(part) for part in argv)
    return (
        'Set shell = CreateObject("WScript.Shell")\n'
        f'shell.Run { _vbs_string(command) }, 0, False\n'
    )


def install_login_host(
    *,
    channel_id: str,
    workspace: Path,
    cwd: Optional[Path] = None,
    extra: Optional[list[str]] = None,
) -> dict[str, str]:
    """Write a user login helper. Kickstart is best-effort and may be a no-op in CI."""

    from agent_discord.host.service import host_log_path, host_run_argv

    workspace = Path(workspace)
    here = Path(cwd) if cwd is not None else Path.cwd()
    log = host_log_path(workspace)
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = host_run_argv(channel_id, extra=extra)
    if sys.platform == "darwin":
        path = launchd_plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_launchd_plist(argv=argv, workspace=workspace, cwd=here, log=log),
            encoding="utf-8",
        )
        _best_effort_launchctl(path)
        return {"kind": "launchd", "path": str(path)}
    if sys.platform == "win32":
        path = windows_startup_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_windows_vbs(argv=argv), encoding="utf-8")
        return {"kind": "startup", "path": str(path)}
    path = systemd_unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_systemd_unit(argv=argv, workspace=workspace, cwd=here, log=log),
        encoding="utf-8",
    )
    _best_effort_systemctl()
    return {"kind": "systemd", "path": str(path)}


def _best_effort_launchctl(plist: Path) -> None:
    _best_effort_launchctl_label(plist, SERVICE_LABEL)


def _best_effort_systemctl() -> None:
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "discord-os-host.service"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _quote(text: str) -> str:
    if not text or any(ch.isspace() for ch in text):
        return "'" + text.replace("'", "'\\''") + "'"
    return text


def _vbs_quote(text: str) -> str:
    if " " in text:
        return f'"{text}"'
    return text


def _vbs_string(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'



def doctor_notify_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{DOCTOR_NOTIFY_LABEL}.plist"


def render_doctor_notify_plist(
    *,
    argv: list[str],
    workspace: Path,
    cwd: Path,
    log: Path,
    start_interval_s: int = 120,
) -> str:
    """Periodic LaunchAgent for ``discord-os host doctor --notify``.

    Runs even when the listen/host KeepAlive agent is dead so the phone still
    wakes. StartInterval (not KeepAlive) — intentional Off stays quiet once
    host.pid is cleared.
    """

    args = "\n".join(f"      <string>{_xml(item)}</string>" for item in argv)
    interval = max(60, int(start_interval_s))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        "<plist version=\"1.0\">\n"
        "<dict>\n"
        "  <key>Label</key>\n"
        f"  <string>{DOCTOR_NOTIFY_LABEL}</string>\n"
        "  <key>RunAtLoad</key>\n"
        "  <true/>\n"
        "  <key>StartInterval</key>\n"
        f"  <integer>{interval}</integer>\n"
        "  <key>WorkingDirectory</key>\n"
        f"  <string>{_xml(str(cwd))}</string>\n"
        "  <key>EnvironmentVariables</key>\n"
        "  <dict>\n"
        "    <key>PYTHONUNBUFFERED</key>\n"
        "    <string>1</string>\n"
        "    <key>AGENT_DISCORD_WORKSPACE</key>\n"
        f"    <string>{_xml(str(workspace))}</string>\n"
        "  </dict>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        f"{args}\n"
        "  </array>\n"
        "  <key>StandardOutPath</key>\n"
        f"  <string>{_xml(str(log))}</string>\n"
        "  <key>StandardErrorPath</key>\n"
        f"  <string>{_xml(str(log))}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def doctor_notify_cron_example(*, python: str = "discord-os") -> str:
    """One crontab line: wake phone when listen pid is dead / doctor FAIL."""

    return (
        f"*/2 * * * * {python} host doctor --notify "
        ">>/tmp/discord-os-doctor-notify.log 2>&1"
    )


def write_doctor_notify_example(
    *,
    workspace: Path,
    dest: Optional[Path] = None,
    python_exe: str = "",
) -> Path:
    """Write an example LaunchAgent plist the operator can bootstrap."""

    exe = python_exe or sys.executable
    argv = [exe, "-m", "agent_discord", "host", "doctor", "--notify"]
    cwd = Path(workspace).resolve().parent if Path(workspace).name == ".agent-discord" else Path(workspace)
    log = Path(workspace) / "doctor-notify.log"
    body = render_doctor_notify_plist(
        argv=argv,
        workspace=Path(workspace),
        cwd=cwd,
        log=log,
        start_interval_s=120,
    )
    path = dest or (Path(workspace) / "com.discord-os.doctor-notify.plist.example")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def install_doctor_notify_watchdog(
    *,
    workspace: Path,
    cwd: Optional[Path] = None,
    python_exe: str = "",
    start_interval_s: int = 120,
) -> dict[str, str]:
    """Install listen-dead doctor --notify for real (LaunchAgent / cron hint).

    Unlike ``write_doctor_notify_example``, this writes the live LaunchAgents
    plist and best-effort bootstraps launchctl so phone notify works when
    listen/host KeepAlive is already dead. StartInterval (not KeepAlive).
    """

    workspace = Path(workspace)
    here = Path(cwd) if cwd is not None else Path.cwd()
    exe = python_exe or sys.executable
    argv = [exe, "-m", "agent_discord", "host", "doctor", "--notify"]
    log = workspace / "doctor-notify.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    # Also keep an example copy in the workspace for operators who prefer cron.
    write_doctor_notify_example(workspace=workspace, python_exe=exe)
    if sys.platform == "darwin":
        path = doctor_notify_plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_doctor_notify_plist(
                argv=argv,
                workspace=workspace,
                cwd=here,
                log=log,
                start_interval_s=start_interval_s,
            ),
            encoding="utf-8",
        )
        _best_effort_launchctl_label(path, DOCTOR_NOTIFY_LABEL)
        return {"kind": "launchd", "path": str(path), "label": DOCTOR_NOTIFY_LABEL}
    # Non-Darwin: write example + return cron line (no fake systemd KeepAlive).
    example = write_doctor_notify_example(workspace=workspace, python_exe=exe)
    return {
        "kind": "cron",
        "path": str(example),
        "cron": doctor_notify_cron_example(python=exe),
    }


def _best_effort_launchctl_label(plist: Path, label: str) -> None:
    """Bootstrap/kickstart one LaunchAgent label. Best-effort (no-op in CI)."""

    uid = os.getuid()
    target = f"gui/{uid}/{label}"
    try:
        subprocess.run(
            ["launchctl", "bootout", target],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["launchctl", "kickstart", "-k", target],
            check=False,
            capture_output=True,
        )
    except OSError:
        return

