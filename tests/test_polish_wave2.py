"""Polish Wave 2: vault probe deepen, Roles/poll honesty, slash copy."""

from __future__ import annotations

from agent_discord.host.panel import roles_menu_payload, roles_modal_payload
from agent_discord.host.remote_cook import (
    SSH_REMOTE_OPENROUTER_VAULT_SEALED,
    _PROBE_EXIT_VAULT_SEALED,
    _REMOTE_READY_SCRIPT,
    _parse_probe_stdout,
    probe_ssh_remote_ready,
)
from agent_discord.host.runners import RemoteHost
from agent_discord.orchestration.ask_poll import LiveGatePollError, refuse_live_gate_poll


def test_remote_probe_script_distinguishes_vault_sealed() -> None:
    assert "vault-sealed" in _REMOTE_READY_SCRIPT
    assert "master.key" in _REMOTE_READY_SCRIPT
    assert "exit 13" in _REMOTE_READY_SCRIPT
    assert _PROBE_EXIT_VAULT_SEALED == 13
    # Never tunnels secrets on argv / probe stdout keys.
    assert "OPENROUTER_API_KEY=" not in _REMOTE_READY_SCRIPT or "${OPENROUTER_API_KEY" in _REMOTE_READY_SCRIPT
    assert "printf" in _REMOTE_READY_SCRIPT


def test_parse_probe_stdout_vault_sealed() -> None:
    cli, openrouter = _parse_probe_stdout(
        "DISCORD_OS_SSH_PROBE cli=puppetmaster openrouter=vault-sealed\n"
    )
    assert cli == "puppetmaster"
    assert openrouter == "vault-sealed"


def test_probe_vault_sealed_is_honest_deny(monkeypatch) -> None:
    host = RemoteHost(id="lab", label="Lab", kind="ssh", target="cary@lab.local")

    class _Proc:
        returncode = 13
        stdout = "DISCORD_OS_SSH_PROBE cli=puppetmaster openrouter=vault-sealed\n"
        stderr = ""

    def _exec(argv, timeout_seconds=5.0):
        assert argv[:3] == ["ssh", "-o", "BatchMode=yes"]
        assert "OPENROUTER_API_KEY=sk" not in " ".join(argv)
        return _Proc()

    result = probe_ssh_remote_ready(host, exec_fn=_exec)
    assert result.ok is False
    assert result.reason == SSH_REMOTE_OPENROUTER_VAULT_SEALED
    assert result.openrouter == "vault-sealed"


def test_roles_menu_is_modal_not_ephemeral_fantasy() -> None:
    menu = roles_menu_payload()
    modal = roles_modal_payload()
    assert menu == modal
    # Modal callback type 9; ephemeral fantasy menus are type 4 message callbacks.
    assert menu.get("type") == modal.get("type")
    data = menu.get("data") or {}
    assert "components" in data or "custom_id" in str(menu)
    # Must not be an ephemeral Confirm/Cancel Roles fantasy.
    blob = str(menu)
    assert "flags" not in blob or "64" not in blob or "Add an operator role id?" not in blob


def test_refuse_live_gate_poll_still_hard() -> None:
    refuse_live_gate_poll(live=False)
    try:
        refuse_live_gate_poll(live=True)
        assert False, "expected LiveGatePollError"
    except LiveGatePollError:
        pass
