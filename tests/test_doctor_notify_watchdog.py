"""Listen-dead doctor --notify watchdog helpers."""

from __future__ import annotations

from pathlib import Path

from agent_discord.host.install import (
    DOCTOR_NOTIFY_LABEL,
    doctor_notify_cron_example,
    doctor_notify_plist_path,
    install_doctor_notify_watchdog,
    render_doctor_notify_plist,
    write_doctor_notify_example,
)


def test_doctor_notify_plist_and_cron(tmp_path: Path) -> None:
    body = render_doctor_notify_plist(
        argv=["/usr/bin/python3", "-m", "agent_discord", "host", "doctor", "--notify"],
        workspace=tmp_path / ".agent-discord",
        cwd=tmp_path,
        log=tmp_path / "doctor-notify.log",
        start_interval_s=120,
    )
    assert DOCTOR_NOTIFY_LABEL in body
    assert "StartInterval" in body
    assert "doctor" in body and "--notify" in body
    assert "KeepAlive" not in body  # periodic, not restart storm
    cron = doctor_notify_cron_example()
    assert "host doctor --notify" in cron
    path = write_doctor_notify_example(workspace=tmp_path / ".agent-discord")
    assert path.is_file()
    assert "com.discord-os.doctor-notify" in path.read_text(encoding="utf-8")


def test_install_doctor_notify_watchdog_real(tmp_path: Path, monkeypatch) -> None:
    """Real install writes LaunchAgent (or cron fallback) — not example-only."""

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Force darwin path for LaunchAgent write without calling real launchctl.
    monkeypatch.setattr("agent_discord.host.install.sys.platform", "darwin")
    monkeypatch.setattr(
        "agent_discord.host.install._best_effort_launchctl_label",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "agent_discord.host.install.doctor_notify_plist_path",
        lambda: home / "Library" / "LaunchAgents" / f"{DOCTOR_NOTIFY_LABEL}.plist",
    )
    ws = tmp_path / ".agent-discord"
    ws.mkdir()
    result = install_doctor_notify_watchdog(
        workspace=ws,
        cwd=tmp_path,
        python_exe="/usr/bin/python3",
    )
    assert result["kind"] == "launchd"
    plist = Path(result["path"])
    assert plist.is_file()
    body = plist.read_text(encoding="utf-8")
    assert DOCTOR_NOTIFY_LABEL in body
    assert "--notify" in body
    assert "StartInterval" in body
    # Example still written for cron operators.
    example = ws / "com.discord-os.doctor-notify.plist.example"
    assert example.is_file()
