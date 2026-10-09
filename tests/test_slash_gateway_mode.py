"""Slash over the existing Gateway (AGENT_DISCORD_INTERACTIONS=gateway).

No Interactions Endpoint URL, no public key, still one Gateway (lock 4).
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_discord.config import check_config, load_config
from agent_discord.discord.interactions import (
    INTERACTION_APPLICATION_COMMAND,
    INTERACTION_APPLICATION_COMMAND_AUTOCOMPLETE,
    RESPONSE_AUTOCOMPLETE,
    interactions_exposed,
    interactions_mode,
    interactions_over_gateway,
    maybe_self_heal_slash_registration,
    route_gateway_interaction,
)
from agent_discord.persistence.sqlite import SQLiteStore


class _Opener:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, request, timeout=0):
        body = request.data.decode("utf-8") if request.data else "{}"
        self.calls.append((request.full_url, json.loads(body)))

        class Resp:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()


def _gateway_config(workspace: Path, *, application_id: str = "app"):
    return load_config(
        env={
            "AGENT_DISCORD_WORKSPACE": str(workspace),
            "AGENT_DISCORD_INTERACTIONS": "gateway",
            "DISCORD_APPLICATION_ID": application_id,
            "DISCORD_BOT_TOKEN": "tok",
        },
        dotenv_path=workspace / "missing.env",
    )


def test_interactions_mode_normalizes():
    assert interactions_mode("gateway") == "gateway"
    assert interactions_mode("http") == "http"
    assert interactions_mode("off") == "off"
    assert interactions_mode("", env={}) == "off"
    assert interactions_exposed("gateway") is True
    assert interactions_over_gateway("gateway") is True
    assert interactions_over_gateway("http") is False


def test_gateway_mode_routes_application_command_and_posts_callback(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    opener = _Opener()
    label = route_gateway_interaction(
        {
            "type": INTERACTION_APPLICATION_COMMAND,
            "id": "ix-1",
            "token": "ix-token",
            "channel_id": "ch-1",
            "member": {"user": {"id": "human-1"}},
            "data": {"name": "on"},
        },
        workspace=ws,
        roots=[ws],
        interactions="gateway",
        opener=opener,
    )
    assert label == "slash:on"
    assert len(opener.calls) == 1
    url, body = opener.calls[0]
    assert url.endswith("/interactions/ix-1/ix-token/callback")
    assert body["data"]["content"] == "On"
    assert body["data"]["flags"] == 64

    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    assert store.host_is_armed("ch-1") is True
    store.close()


def test_gateway_mode_routes_autocomplete(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    repo = tmp_path / "puppetmaster"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setenv("DISCORD_OS_REPOS", f"puppetmaster:{repo}")
    opener = _Opener()
    label = route_gateway_interaction(
        {
            "type": INTERACTION_APPLICATION_COMMAND_AUTOCOMPLETE,
            "id": "ix-2",
            "token": "tok-2",
            "channel_id": "ch-1",
            "data": {
                "name": "bind",
                "options": [{"name": "name", "value": "pup", "focused": True}],
            },
        },
        workspace=ws,
        roots=[ws],
        interactions="gateway",
        opener=opener,
    )
    assert label == "slash:bind"
    _, body = opener.calls[0]
    assert body["type"] == RESPONSE_AUTOCOMPLETE
    values = [c["value"] for c in body["data"]["choices"]]
    assert "puppetmaster" in values


def test_gateway_route_is_off_by_default_and_skips_components(tmp_path: Path):
    opener = _Opener()
    command = {
        "type": INTERACTION_APPLICATION_COMMAND,
        "id": "ix-3",
        "token": "tok-3",
        "channel_id": "ch-1",
        "data": {"name": "status"},
    }
    assert (
        route_gateway_interaction(
            command, workspace=tmp_path, interactions="off", opener=opener, env={}
        )
        is None
    )
    assert (
        route_gateway_interaction(
            command, workspace=tmp_path, interactions="http", opener=opener, env={}
        )
        is None
    )
    # Component click stays on the HOST panel custom_id path.
    assert (
        route_gateway_interaction(
            {
                "type": 3,
                "id": "ix-4",
                "token": "tok-4",
                "data": {"custom_id": "host:on"},
            },
            workspace=tmp_path,
            interactions="gateway",
            opener=opener,
        )
        is None
    )
    assert opener.calls == []


def test_gateway_route_survives_a_failed_callback(tmp_path: Path, capsys):
    def boom(request, timeout=0):
        raise OSError("discord unreachable")

    label = route_gateway_interaction(
        {
            "type": INTERACTION_APPLICATION_COMMAND,
            "id": "ix-5",
            "token": "tok-5",
            "channel_id": "ch-1",
            "data": {"name": "status"},
        },
        workspace=tmp_path,
        roots=[tmp_path],
        interactions="gateway",
        opener=boom,
    )
    assert label == "slash:status"
    assert "slash callback failed" in capsys.readouterr().out


def test_gateway_self_heal_needs_no_public_key(tmp_path: Path):
    calls: list[dict] = []

    def register(**kwargs):
        calls.append(kwargs)
        return ["status"]

    result = maybe_self_heal_slash_registration(
        workspace=tmp_path,
        token="tok",
        application_id="app",
        public_key="",
        interactions="gateway",
        package_version="0.5.90",
        register_fn=register,
    )
    assert result.registered is True
    assert len(calls) == 1
    assert not [w for w in result.warnings if "PUBLIC_KEY" in w]


def test_config_accepts_gateway(tmp_path: Path):
    config = _gateway_config(tmp_path, application_id="app-1")
    assert config.interactions == "gateway"
    assert config.discord_public_key == ""
    problems = check_config(config, require_token=False)
    assert not [p for p in problems if "INTERACTIONS" in p or "PUBLIC_KEY" in p]


def test_check_config_gateway_requires_application_id(tmp_path: Path):
    config = _gateway_config(tmp_path, application_id="")
    problems = check_config(config, require_token=False)
    assert any("DISCORD_APPLICATION_ID" in p and "gateway" in p for p in problems)


def test_doctor_reports_gateway_mode(tmp_path: Path):
    from agent_discord.host.doctor import _check_slash_self_heal

    lines: list[str] = []
    _check_slash_self_heal(_gateway_config(tmp_path), tmp_path, lines)
    assert any("mode=gateway" in line for line in lines)
    assert not [line for line in lines if "DISCORD_PUBLIC_KEY" in line]
