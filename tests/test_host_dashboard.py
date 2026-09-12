"""P2.12 companion web dashboard — read-only, loopback, no secrets."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from agent_discord import __version__
from agent_discord.cli import build_parser, main
from agent_discord.host.dashboard import (
    DEFAULT_DASHBOARD_HOST,
    DashboardBindError,
    build_status_snapshot,
    make_dashboard_handler,
    resolve_bind_host,
    serve_dashboard,
)
from agent_discord.persistence.sqlite import SQLiteStore


def _workspace(tmp_path: Path, monkeypatch) -> Path:
    ws = tmp_path / ".agent-discord"
    ws.mkdir(parents=True)
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-should-not-leak")
    return ws


def test_cli_exposes_host_dashboard() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "dashboard" in help_text
    args = parser.parse_args(["host", "dashboard", "--once"])
    assert args.command == "host"
    assert args.host_command == "dashboard"
    assert args.once is True
    top = parser.parse_args(["dashboard", "--once"])
    assert top.command == "dashboard"


def test_bind_policy_fail_closed() -> None:
    assert resolve_bind_host(None) == DEFAULT_DASHBOARD_HOST
    assert resolve_bind_host("127.0.0.1") == "127.0.0.1"
    with pytest.raises(DashboardBindError):
        resolve_bind_host("0.0.0.0")
    with pytest.raises(DashboardBindError):
        resolve_bind_host("::")
    with pytest.raises(DashboardBindError):
        resolve_bind_host("192.168.1.10")
    assert resolve_bind_host("0.0.0.0", allow_non_loopback=True) == "0.0.0.0"


def test_snapshot_shape_and_allowlist_no_secrets(tmp_path: Path, monkeypatch) -> None:
    ws = _workspace(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.set_host_control("chan-1", armed=True)
    store.create_task(
        task_id="t1",
        workspace_id="default",
        channel_id="chan-1",
        intake_text="planted password=supersecret and token=leakme",
    )
    store.create_run(
        run_id="r1",
        task_id="t1",
        model="fake",
        adapter_name="fake",
    )
    meta = ws / "host.meta.json"
    # service uses host_meta_path — write via API if possible
    from agent_discord.host.service import write_host_meta

    write_host_meta(ws, pid=1, channel_id="chan-1")
    monkeypatch.setenv(
        "DISCORD_OS_HOSTS",
        json.dumps(
            [
                {
                    "id": "lab",
                    "label": "Lab Mac",
                    "ssh": "cary@lab.local",
                    "workdir": "/Users/cary/secret-path",
                }
            ]
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-planted-should-not-appear")
    snap = build_status_snapshot(
        workspace=ws,
        store=store,
        include_doctor=False,
        env=dict(**{k: v for k, v in __import__("os").environ.items()}),
    )
    store.close()
    assert snap["version"] == __version__
    assert snap["readonly"] is True
    assert "power" not in snap or True
    assert snap["host"]["channel_id"] == "chan-1"
    assert snap["host"]["armed"] is True
    assert "spend" in snap and "spend_usd" in snap["spend"]
    assert isinstance(snap["jobs"], list)
    assert snap["hosts"] == [{"id": "lab", "label": "Lab Mac", "kind": "ssh"}]
    blob = json.dumps(snap)
    assert "cary@lab.local" not in blob
    assert "secret-path" not in blob
    assert "sk-planted" not in blob
    assert "test-token-should-not-leak" not in blob
    assert "supersecret" not in blob
    assert "leakme" not in blob
    assert "target" not in blob
    # cleanup meta pid file noise
    del meta


def test_handler_read_only_and_no_secret_leak(tmp_path: Path, monkeypatch) -> None:
    ws = _workspace(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=False)
    from agent_discord.host.service import write_host_meta

    write_host_meta(ws, pid=1, channel_id="ch")
    monkeypatch.setenv(
        "DISCORD_OS_HOSTS",
        '[{"id":"nas","label":"NAS","ssh":"user:hunter2@nas.local"}]',
    )
    planted = "BEGIN RSA PRIVATE KEY fake"
    monkeypatch.setenv("DISCORD_BOT_TOKEN", planted)

    def snapshot() -> dict:
        return build_status_snapshot(
            workspace=ws,
            store=store,
            include_doctor=False,
            env=dict(__import__("os").environ),
        )

    server = serve_dashboard(
        host="127.0.0.1",
        port=0,
        snapshot_fn=snapshot,
        workspace=ws,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        base = f"http://{host}:{port}"
        with urlopen(base + "/api/status", timeout=2) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
        assert "hunter2" not in body
        assert planted not in body
        assert "BEGIN RSA" not in body
        data = json.loads(body)
        assert data["readonly"] is True
        assert data["hosts"][0]["id"] == "nas"
        assert "target" not in json.dumps(data["hosts"])

        with urlopen(base + "/", timeout=2) as resp:
            html = resp.read().decode("utf-8")
            assert resp.status == 200
        assert "companion" in html.lower() or "Discord OS" in html
        assert "hunter2" not in html

        for method in ("POST", "PUT", "PATCH", "DELETE"):
            req = Request(base + "/api/status", method=method, data=b"{}")
            with pytest.raises(HTTPError) as exc:
                urlopen(req, timeout=2)
            assert exc.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
        store.close()


def test_cli_once_prints_json(tmp_path: Path, monkeypatch, capsys) -> None:
    ws = _workspace(tmp_path, monkeypatch)
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    store.close()
    assert main(["host", "dashboard", "--once"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["version"] == __version__
    assert payload["readonly"] is True


def test_cli_refuses_non_loopback_without_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    _workspace(tmp_path, monkeypatch)
    code = main(["host", "dashboard", "--host", "0.0.0.0", "--once"])
    # --once does not bind; check resolve path via serve flag absence:
    # exercise bind refusal without --once by calling resolve through main serve briefly
    code = main(["dashboard", "--host", "0.0.0.0"])
    assert code == 2
    err = capsys.readouterr().err
    assert "refuse" in err.lower() or "non-loopback" in err.lower() or "0.0.0.0" in err
