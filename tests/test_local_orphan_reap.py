"""Audit 2026-10-02 F6: reap local agentic children orphaned by a host restart.

Local workers spawn with ``start_new_session=True``, so an abrupt host exit left
them cooking, spending, and writing the checkout after the write lock was gone.
Path A already had this for remote pids.
"""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path

from agent_discord.puppetmaster.cancel_honesty import (
    clear_local_pid_sidecar,
    local_pid_sidecar_dir,
    persist_local_pid_sidecar,
    reap_orphaned_local_pids,
)


def _sidecars(folder: str) -> list[str]:
    return sorted(name for name in os.listdir(folder) if name.endswith(".json"))


def test_sidecar_dir_lives_under_the_host_workspace(tmp_path: Path) -> None:
    folder = local_pid_sidecar_dir(workspace=tmp_path / ".agent-discord", env={})
    assert Path(folder) == tmp_path / ".agent-discord" / "local_pids"
    assert Path(folder).is_dir()


def test_persist_then_clear_round_trips(tmp_path: Path) -> None:
    folder = local_pid_sidecar_dir(workspace=tmp_path, env={})
    path = persist_local_pid_sidecar(
        run_id="run-1", pid=4242, pgid=4242, job_id="j7", workspace=tmp_path, env={}
    )
    assert path
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["run_id"] == "run-1"
    assert data["pid"] == 4242
    assert data["pgid"] == 4242
    assert data["job_id"] == "j7"
    assert data["started_at_ms"] > 0
    clear_local_pid_sidecar("run-1", workspace=tmp_path, env={})
    assert _sidecars(folder) == []


def test_persist_refuses_a_bad_run_or_pid(tmp_path: Path) -> None:
    assert persist_local_pid_sidecar(run_id="", pid=1, workspace=tmp_path, env={}) == ""
    assert persist_local_pid_sidecar(run_id="r", pid=0, workspace=tmp_path, env={}) == ""


def test_reap_terminates_a_live_puppetmaster_group(monkeypatch, tmp_path: Path) -> None:
    folder = local_pid_sidecar_dir(workspace=tmp_path, env={})
    persist_local_pid_sidecar(
        run_id="run-1", pid=4242, pgid=4242, job_id="j7", workspace=tmp_path, env={}
    )
    alive = {4242: True}
    sent: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        sent.append((pgid, sig))
        if sig == signal.SIGTERM:
            alive[pgid] = False

    monkeypatch.setattr(
        "agent_discord.puppetmaster.cancel_honesty.process_group_is_alive",
        lambda pgid: alive.get(int(pgid), False),
    )
    records = reap_orphaned_local_pids(
        workspace=tmp_path,
        env={},
        ps_fn=lambda pid: "/opt/bin/puppetmaster agentic --provider openrouter",
        killpg_fn=fake_killpg,
        etime_fn=lambda pid: "00:03",
    )
    assert [r["action"] for r in records] == ["reaped"]
    assert records[0]["killed"] is True
    assert records[0]["job_id"] == "j7"
    assert sent == [(4242, signal.SIGTERM)]
    assert _sidecars(folder) == []


def test_reap_escalates_to_sigkill_when_sigterm_is_ignored(
    monkeypatch, tmp_path: Path
) -> None:
    persist_local_pid_sidecar(run_id="run-1", pid=99, pgid=99, workspace=tmp_path, env={})
    sent: list[int] = []
    monkeypatch.setattr(
        "agent_discord.puppetmaster.cancel_honesty.process_group_is_alive",
        lambda pgid: True,
    )
    records = reap_orphaned_local_pids(
        workspace=tmp_path,
        env={},
        grace_seconds=0.05,
        ps_fn=lambda pid: "puppetmaster agentic",
        killpg_fn=lambda pgid, sig: sent.append(sig),
        etime_fn=lambda pid: "00:03",
    )
    assert sent == [signal.SIGTERM, signal.SIGKILL]
    # Group still alive after SIGKILL: do not claim it died.
    assert records[0]["killed"] is False


def test_reap_never_signals_a_reused_pid(monkeypatch, tmp_path: Path) -> None:
    folder = local_pid_sidecar_dir(workspace=tmp_path, env={})
    persist_local_pid_sidecar(run_id="run-1", pid=4242, pgid=4242, workspace=tmp_path, env={})
    monkeypatch.setattr(
        "agent_discord.puppetmaster.cancel_honesty.process_group_is_alive",
        lambda pgid: True,
    )
    sent: list[int] = []
    records = reap_orphaned_local_pids(
        workspace=tmp_path,
        env={},
        ps_fn=lambda pid: "/usr/sbin/httpd -D FOREGROUND",
        killpg_fn=lambda pgid, sig: sent.append(sig),
    )
    assert sent == []
    assert records[0]["action"] == "not-ours"
    assert _sidecars(folder) == []


def test_reap_never_signals_when_ps_is_unreadable(monkeypatch, tmp_path: Path) -> None:
    persist_local_pid_sidecar(run_id="run-1", pid=4242, pgid=4242, workspace=tmp_path, env={})
    monkeypatch.setattr(
        "agent_discord.puppetmaster.cancel_honesty.process_group_is_alive",
        lambda pgid: True,
    )
    sent: list[int] = []
    records = reap_orphaned_local_pids(
        workspace=tmp_path,
        env={},
        ps_fn=lambda pid: "",
        killpg_fn=lambda pgid, sig: sent.append(sig),
    )
    assert sent == []
    assert records[0]["action"] == "not-ours"


def test_reap_clears_a_dead_group_without_signalling(monkeypatch, tmp_path: Path) -> None:
    folder = local_pid_sidecar_dir(workspace=tmp_path, env={})
    persist_local_pid_sidecar(run_id="run-1", pid=4242, pgid=4242, workspace=tmp_path, env={})
    monkeypatch.setattr(
        "agent_discord.puppetmaster.cancel_honesty.process_group_is_alive",
        lambda pgid: False,
    )
    sent: list[int] = []
    records = reap_orphaned_local_pids(
        workspace=tmp_path,
        env={},
        ps_fn=lambda pid: "puppetmaster agentic",
        killpg_fn=lambda pgid, sig: sent.append(sig),
    )
    assert sent == []
    assert records[0]["action"] == "gone"
    assert _sidecars(folder) == []


def test_reap_expires_an_ancient_sidecar(tmp_path: Path) -> None:
    folder = local_pid_sidecar_dir(workspace=tmp_path, env={})
    path = Path(
        persist_local_pid_sidecar(run_id="run-1", pid=4242, workspace=tmp_path, env={})
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["started_at_ms"] = 1
    path.write_text(json.dumps(data), encoding="utf-8")
    records = reap_orphaned_local_pids(workspace=tmp_path, env={})
    assert records[0]["action"] == "expired"
    assert _sidecars(folder) == []


def test_reap_drops_a_corrupt_sidecar(tmp_path: Path) -> None:
    folder = local_pid_sidecar_dir(workspace=tmp_path, env={})
    Path(folder, "junk.json").write_text("not json", encoding="utf-8")
    assert reap_orphaned_local_pids(workspace=tmp_path, env={}) == []
    assert _sidecars(folder) == []


def test_reap_on_a_missing_dir_is_empty(tmp_path: Path) -> None:
    assert reap_orphaned_local_pids(workspace=tmp_path / "nope" / "deep", env={}) == []


def test_agentic_backend_writes_and_clears_a_pid_sidecar(tmp_path: Path) -> None:
    from agent_discord.puppetmaster.agentic import AgenticPuppetmasterBackend
    from agent_discord.puppetmaster.models import AGENTIC_MODEL_PIN

    workspace = tmp_path / ".agent-discord"
    backend = AgenticPuppetmasterBackend(
        cli="puppetmaster",
        pin=AGENTIC_MODEL_PIN,
        workspace=workspace,
        env={},
    )

    class _Child:
        pid = os.getpid()

    child = _Child()
    backend._register_child("run-9", child)
    folder = local_pid_sidecar_dir(workspace=workspace, env={})
    assert _sidecars(folder) == ["run-9.json"]
    data = json.loads(Path(folder, "run-9.json").read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    assert "puppetmaster" in data["command"]

    # A job id arriving later is folded in, not lost.
    backend._note_job_id("run-9", "job-77")
    data = json.loads(Path(folder, "run-9.json").read_text(encoding="utf-8"))
    assert data["job_id"] == "job-77"

    backend._unregister_child("run-9", child)
    assert _sidecars(folder) == []


def test_reap_spares_another_puppetmaster_process_that_reused_the_pid(
    monkeypatch, tmp_path: Path
) -> None:
    """A Marionette or MCP worker can reuse the pid; its start time gives it away."""

    persist_local_pid_sidecar(run_id="run-1", pid=4242, pgid=4242, workspace=tmp_path, env={})
    monkeypatch.setattr(
        "agent_discord.puppetmaster.cancel_honesty.process_group_is_alive",
        lambda pgid: True,
    )
    sent: list[int] = []
    records = reap_orphaned_local_pids(
        workspace=tmp_path,
        env={},
        ps_fn=lambda pid: "puppetmaster agentic --provider openrouter",
        killpg_fn=lambda pgid, sig: sent.append(sig),
        etime_fn=lambda pid: "2-03:00:00",  # started two days before the sidecar
    )
    assert [r["action"] for r in records] == ["not-ours"]
    assert sent == []


def test_reap_refuses_unsafe_process_groups(monkeypatch, tmp_path: Path) -> None:
    import os

    for index, (pid, pgid) in enumerate(((4242, 1), (1, 1), (4242, os.getpgrp()))):
        persist_local_pid_sidecar(
            run_id=f"run-{index}", pid=pid, pgid=pgid, workspace=tmp_path, env={}
        )
    monkeypatch.setattr(
        "agent_discord.puppetmaster.cancel_honesty.process_group_is_alive",
        lambda pgid: True,
    )
    sent: list[int] = []
    records = reap_orphaned_local_pids(
        workspace=tmp_path,
        env={},
        ps_fn=lambda pid: "puppetmaster agentic",
        killpg_fn=lambda pgid, sig: sent.append(pgid),
        etime_fn=lambda pid: "00:03",
    )
    assert sent == []
    assert all(r["action"] == "unsafe" for r in records), records


def test_parse_etime() -> None:
    from agent_discord.puppetmaster.cancel_honesty import _parse_etime

    assert _parse_etime("00:03") == 3
    assert _parse_etime("01:02:03") == 3723
    assert _parse_etime("2-03:00:00") == 2 * 86400 + 3 * 3600
    assert _parse_etime("") is None
    assert _parse_etime("bogus") is None
