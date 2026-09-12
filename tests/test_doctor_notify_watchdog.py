"""Listen-dead doctor --notify watchdog helpers."""

from __future__ import annotations

from pathlib import Path

from agent_discord.host.install import (
    DOCTOR_NOTIFY_LABEL,
    doctor_notify_cron_example,
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
