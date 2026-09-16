"""Cross-host read-only status — no targets, fail-closed probe."""

from __future__ import annotations

from pathlib import Path

from agent_discord.host.cross_host import cross_host_ro_status, probe_host_ro, public_host_fields
from agent_discord.host.runners import RemoteHost


def test_public_host_fields_omit_target():
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="user@secret.example")
    row = public_host_fields(host, reachable=True, detail="capable")
    assert "target" not in row
    assert row["id"] == "lab"
    assert row["reachable"] is True


def test_local_probe_path(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    host = RemoteHost(id="local", label="Here", kind="local", target=str(root))
    ok, detail = probe_host_ro(host)
    assert ok is True
    missing = RemoteHost(id="gone", label="Gone", kind="local", target=str(tmp_path / "nope"))
    ok2, _ = probe_host_ro(missing)
    assert ok2 is False


def test_cross_host_ro_status_no_probe(monkeypatch):
    blob = '[{"id":"lab","label":"Lab","kind":"ssh","target":"u@h"}]'
    rows = cross_host_ro_status(
        env={"DISCORD_OS_HOSTS": blob},
        probe=False,
    )
    assert rows == [{"id": "lab", "label": "Lab", "kind": "ssh"}]


def test_ssh_probe_uses_exec_fn():
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="u@h")

    def fake_exec(argv, **kwargs):
        return 1, "", "ssh: unreachable"

    ok, detail = probe_host_ro(host, exec_fn=fake_exec)
    assert ok is False
    assert "target" not in detail
