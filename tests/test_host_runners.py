"""P2.11 multi-host runners — fail-closed allowlist."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_discord.host.doctor import run_doctor
from agent_discord.host.install import SERVICE_LABEL
from agent_discord.host.power import is_power_command, parse_power_command
from agent_discord.host.remote_cook import (
    SSH_COOK_CAPABLE,
    SSH_COOK_UNREACHABLE,
    build_remote_agentic_argv,
    probe_ssh_host,
    ssh_cook_enabled,
)
from agent_discord.host.runners import (
    SSH_COOK_STATUS,
    HostAllowlistError,
    RemoteHost,
    assert_host_cook_allowed,
    bind_channel_host,
    get_host,
    host_runner_argv,
    is_host_bind_command,
    load_host_allowlist,
    parse_host_bind_command,
    power_stays_local,
    resolve_channel_host,
    spoken_host_deny,
    spoken_ssh_cook_deny,
    validate_host_allowlist,
)
from agent_discord.contracts import ContextSnapshot, DispatchRequest
from agent_discord.persistence.sqlite import SQLiteStore


def test_empty_allowlist_ok_single_host(tmp_path: Path) -> None:
    hosts = load_host_allowlist(env={})
    assert hosts == ()
    store = SQLiteStore(tmp_path / "empty.sqlite3")
    store.initialize()
    assert (
        resolve_channel_host(store, "ch", workspace_id="ws", allowlist=()) is None
    )
    store.close()


def test_unknown_host_rejected() -> None:
    allow = (
        RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local"),
    )
    with pytest.raises(HostAllowlistError) as exc:
        get_host("stranger", allow)
    assert "Denied" in str(exc.value.spoken)
    assert "stranger" in str(exc.value.spoken)


def test_allowlisted_host_accepted(tmp_path: Path) -> None:
    allow = (
        RemoteHost(id="lab", label="Lab Mac", kind="ssh", target="cary@lab.local"),
    )
    host = get_host("lab", allow)
    assert host.id == "lab"
    assert host.label == "Lab Mac"
    store = SQLiteStore(tmp_path / "bind.sqlite3")
    store.initialize()
    bound = bind_channel_host(
        store,
        workspace_id="ws",
        channel_id="ch",
        host_id="lab",
        allowlist=allow,
    )
    assert bound.id == "lab"
    row = store.get_binding("ws", "ch")
    assert row is not None
    assert "lab" in str(row.get("metadata_json") or "")
    resolved = resolve_channel_host(
        store, "ch", workspace_id="ws", allowlist=allow
    )
    assert resolved is not None and resolved.id == "lab"
    store.close()


def test_unknown_bound_host_fail_closed_no_local_fallback(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "deny.sqlite3")
    store.initialize()
    store.merge_binding_metadata("ws", "ch", {"host_id": "ghost"})
    with pytest.raises(HostAllowlistError):
        resolve_channel_host(
            store,
            "ch",
            workspace_id="ws",
            allowlist=(
                RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local"),
            ),
        )
    # Binding present but allowlist empty still fails closed (no silent local).
    with pytest.raises(HostAllowlistError):
        resolve_channel_host(store, "ch", workspace_id="ws", allowlist=())
    store.close()


def test_power_stays_local() -> None:
    assert power_stays_local() is True
    assert is_power_command("/off")
    assert parse_power_command("/off").action == "off"
    assert is_power_command("/on")
    assert not is_host_bind_command("/off")


def test_no_credential_in_argv(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "ghp_should_never_appear")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord.bot.token.value")
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    argv = host_runner_argv(host, ["uname", "-a"])
    joined = " ".join(argv)
    assert "ghp_" not in joined
    assert "discord.bot.token" not in joined
    assert "GH_TOKEN" not in joined
    assert argv[:3] == ["ssh", "-o", "BatchMode=yes"]
    assert "cary@lab.local" in argv
    # Inline secret material in remote_command is refused.
    with pytest.raises(HostAllowlistError):
        host_runner_argv(host, ["echo", "token=secret-value"])


def test_load_json_and_csv_formats() -> None:
    blob = json.dumps(
        [
            {
                "id": "lab",
                "label": "Lab Mac",
                "ssh": "cary@lab.local",
                "channels": ["111"],
                "workdir": "/Users/cary/Projects",
            },
            {"id": "nas", "label": "NAS", "path": "/Volumes/work"},
        ]
    )
    hosts = load_host_allowlist(env={"DISCORD_OS_HOSTS": blob})
    assert {h.id for h in hosts} == {"lab", "nas"}
    lab = get_host("lab", hosts)
    assert lab.kind == "ssh" and lab.channel_ids == ("111",)
    nas = get_host("nas", hosts)
    assert nas.kind == "local" and nas.target == "/Volumes/work"
    csv_hosts = load_host_allowlist(
        env={"DISCORD_OS_HOSTS": "lab:ssh:cary@lab.local,nas:path:/Volumes/work"}
    )
    assert {h.id for h in csv_hosts} == {"lab", "nas"}


def test_duplicate_channel_claim_fail_closed() -> None:
    allow = (
        RemoteHost(
            id="a", label="A", kind="ssh", target="a@host", channel_ids=("ch",)
        ),
        RemoteHost(
            id="b", label="B", kind="ssh", target="b@host", channel_ids=("ch",)
        ),
    )
    with pytest.raises(HostAllowlistError):
        resolve_channel_host(None, "ch", workspace_id="ws", allowlist=allow)


def test_bind_host_command_parse() -> None:
    assert is_host_bind_command("bind host lab")
    assert is_host_bind_command("/bind host lab")
    assert parse_host_bind_command("bind host lab") == "lab"
    assert parse_host_bind_command("bind puppetmaster") == ""
    assert spoken_host_deny("x").startswith("Denied.")


def test_validate_and_doctor_allowlist(tmp_path: Path, monkeypatch) -> None:
    assert validate_host_allowlist(()) == []
    bad = (
        RemoteHost(id="x", label="x", kind="ssh", target=""),
        RemoteHost(id="x", label="dup", kind="ssh", target="u@h"),
    )
    problems = validate_host_allowlist(bad)
    assert any("missing target" in p for p in problems)
    assert any("duplicate" in p for p in problems)

    home = tmp_path / "home"
    ws = home / "discord-os" / ".agent-discord"
    ws.mkdir(parents=True)
    py = tmp_path / "python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    import plistlib

    plist = home / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(
        plistlib.dumps(
            {
                "Label": SERVICE_LABEL,
                "WorkingDirectory": str(home / "discord-os"),
                "EnvironmentVariables": {"AGENT_DISCORD_WORKSPACE": str(ws)},
                "ProgramArguments": [str(py), "-m", "agent_discord", "host", "run"],
            }
        )
    )
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.close()
    from agent_discord import config as cfgmod

    token_path = ws / "bot.token"
    monkeypatch.setattr(cfgmod, "DEFAULT_HOST_BOT_TOKEN_PATH", token_path)
    token_path.write_text("dummy\n", encoding="utf-8")
    monkeypatch.delenv("DISCORD_OS_HOSTS", raising=False)
    code, lines = run_doctor(workspace=ws, plist_path=plist, home=home)
    assert any("host allowlist empty (single-host)" in line for line in lines), lines

    monkeypatch.setenv(
        "DISCORD_OS_HOSTS",
        json.dumps([{"id": "lab", "ssh": "cary@lab.local"}]),
    )
    monkeypatch.setenv("DISCORD_OS_SSH_COOK", "1")

    def _fake_probe(host, **kwargs):
        return True, SSH_COOK_CAPABLE

    monkeypatch.setattr(
        "agent_discord.host.doctor.probe_ssh_host"
        if False
        else "agent_discord.host.remote_cook.probe_ssh_host",
        _fake_probe,
    )
    # Doctor imports probe inside the function — patch the module used at call time.
    import agent_discord.host.remote_cook as rc

    monkeypatch.setattr(rc, "probe_ssh_host", _fake_probe)
    code, lines = run_doctor(workspace=ws, plist_path=plist, home=home)
    assert any("host allowlist 1: lab" in line for line in lines), lines
    assert any(
        "OK host ssh lab:" in line and "cook-capable" in line for line in lines
    ), lines

    def _fail_probe(host, **kwargs):
        return False, "Connection refused"

    monkeypatch.setattr(rc, "probe_ssh_host", _fail_probe)
    code, lines = run_doctor(workspace=ws, plist_path=plist, home=home)
    assert any(
        "WARN host ssh lab:" in line and SSH_COOK_UNREACHABLE in line for line in lines
    ), lines

    monkeypatch.setenv(
        "DISCORD_OS_HOSTS",
        json.dumps([{"id": "bad", "ssh": "user@host -i /tmp/key"}]),
    )
    # unsafe target is filtered at load (skipped) OR validated — JSON with ssh
    # that has spaces fails unsafe check only if loaded; our loader keeps the
    # full ssh string. Doctor should FAIL.
    hosts = load_host_allowlist()
    # ssh value with spaces is kept by JSON loader; validate catches it
    assert hosts and hosts[0].target.startswith("user@host")
    code, lines = run_doctor(workspace=ws, plist_path=plist, home=home)
    assert any(line.startswith("FAIL host allowlist:") for line in lines), lines
    assert code == 1


def test_bind_unknown_host_raises(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "u.sqlite3")
    store.initialize()
    with pytest.raises(HostAllowlistError):
        bind_channel_host(
            store,
            workspace_id="ws",
            channel_id="ch",
            host_id="nope",
            allowlist=(),
        )
    store.close()


def test_ssh_cook_allowed_local_path_allowed(tmp_path: Path) -> None:
    """Path A: ssh kind is cook-eligible; local/path still may; argv stays clean."""

    ssh = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    assert_host_cook_allowed(ssh)  # no raise — remote cook path owns reachability
    assert SSH_COOK_STATUS in spoken_ssh_cook_deny("lab")
    assert ssh_cook_enabled() is True

    # Empty / None: single-host unchanged.
    assert_host_cook_allowed(None)

    local = RemoteHost(
        id="nas",
        label="NAS",
        kind="local",
        target=str(tmp_path),
    )
    assert_host_cook_allowed(local)  # no raise

    argv = host_runner_argv(ssh, ["puppetmaster", "agentic", "status"])
    assert argv[:3] == ["ssh", "-o", "BatchMode=yes"]
    joined = " ".join(argv)
    assert "ghp_" not in joined
    assert "token=" not in joined


def test_ssh_bound_channel_cook_gate(tmp_path: Path) -> None:
    """resolve + assert: bound ssh is cook-eligible; local still allowed."""

    allow = (
        RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local"),
        RemoteHost(id="nas", label="NAS", kind="local", target=str(tmp_path)),
    )
    store = SQLiteStore(tmp_path / "cook.sqlite3")
    store.initialize()
    bind_channel_host(
        store,
        workspace_id="ws",
        channel_id="ch-ssh",
        host_id="lab",
        allowlist=allow,
    )
    host = resolve_channel_host(
        store, "ch-ssh", workspace_id="ws", allowlist=allow
    )
    assert host is not None and host.kind == "ssh"
    assert_host_cook_allowed(host)

    bind_channel_host(
        store,
        workspace_id="ws",
        channel_id="ch-local",
        host_id="nas",
        allowlist=allow,
    )
    local = resolve_channel_host(
        store, "ch-local", workspace_id="ws", allowlist=allow
    )
    assert local is not None and local.kind == "local"
    assert_host_cook_allowed(local)
    store.close()


def test_remote_cook_argv_and_mock_probe() -> None:
    """Path A building blocks: agentic argv over ssh; probe mockable."""

    ssh = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")
    req = DispatchRequest(
        task_id="t",
        run_id="r",
        prompt="review invoices",
        model="openrouter/auto",
        context=ContextSnapshot(
            task_id="t", memories=(), bindings={}, provenance={}
        ),
        metadata={"compute_mode": "analyze", "host_workdir": "/tmp/work"},
    )
    remote = build_remote_agentic_argv(req, remote_cwd="/tmp/work")
    assert remote[0] == "puppetmaster"
    assert "agentic" in remote
    assert "openrouter" in remote
    joined = " ".join(remote)
    assert "token=" not in joined
    assert "OPENROUTER" not in joined

    argv = host_runner_argv(ssh, remote)
    assert argv[:3] == ["ssh", "-o", "BatchMode=yes"]
    assert "cary@lab.local" in argv

    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _exec(argv, *, timeout_seconds=0):
        calls.append(list(argv))
        return _Proc()

    ok, detail = probe_ssh_host(ssh, exec_fn=_exec)
    assert ok is True
    assert SSH_COOK_CAPABLE in detail
    assert calls and calls[0][:3] == ["ssh", "-o", "BatchMode=yes"]
    assert "true" in calls[0]

    class _Bad:
        returncode = 255
        stdout = ""
        stderr = "Connection refused"

    def _bad(argv, *, timeout_seconds=0):
        return _Bad()

    ok, detail = probe_ssh_host(ssh, exec_fn=_bad)
    assert ok is False
    assert "refused" in detail.lower() or detail
