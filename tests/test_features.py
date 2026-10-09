"""One switchboard for the opt-ins: CLI, slash /features, and HOST More > Features."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_discord.discord.interactions import OPT_IN_COMMANDS, handle_interaction_payload
from agent_discord.host.features import (
    FEATURE_NAMES,
    feature_states,
    set_feature,
    sync_feature_env,
)
from agent_discord.host.panel import (
    FEATURE_TOGGLE_PREFIX,
    FEATURES_ID,
    MORE_ID,
    handle_gateway_interaction,
)
from agent_discord.orchestration.capture import capture_first_enabled
from agent_discord.orchestration.ci_watch import ci_watch_enabled
from agent_discord.orchestration.morning import morning_enabled
from agent_discord.orchestration.pm_inbox import pm_inbox_channel_id
from agent_discord.persistence.sqlite import SQLiteStore

from tests.test_operator_authz import _click, _Recorder, _slash

HOST_FLAGS = ("DISCORD_OS_CI_WATCH", "DISCORD_OS_MORNING", "DISCORD_OS_VOICE_DONE")
CHANNEL_FLAGS = (
    "DISCORD_OS_CAPTURE_FIRST",
    "DISCORD_OS_CAPTURE_CHANNELS",
    "DISCORD_OS_PM_INBOX_CHANNEL",
)


def _clean_env(monkeypatch) -> None:
    # setenv first so monkeypatch restores the key even when it was absent:
    # a toggle writes os.environ, and that must not leak into other tests.
    for key in HOST_FLAGS + CHANNEL_FLAGS:
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)


def _store(tmp_path: Path, *, owner: str = "") -> SQLiteStore:
    store = SQLiteStore(tmp_path / "agent_discord.sqlite3")
    store.initialize()
    store.set_host_control("ch", armed=True)
    if owner:
        store.add_operator(owner, role="owner")
    return store


def test_every_feature_is_off_by_default(tmp_path: Path, monkeypatch) -> None:
    _clean_env(monkeypatch)
    store = _store(tmp_path)
    states = feature_states(store, channel_id="ch")
    assert [s.feature.name for s in states] == list(FEATURE_NAMES)
    assert not any(s.on for s in states)
    store.close()


def test_host_toggle_reaches_the_enabled_check_without_restart(
    tmp_path: Path, monkeypatch
) -> None:
    _clean_env(monkeypatch)
    store = _store(tmp_path)
    environ: dict[str, str] = {}
    set_feature(store, "ci-watch", True, environ=environ)
    set_feature(store, "morning", True, environ=environ)
    assert ci_watch_enabled(env=environ) and morning_enabled(env=environ)

    # Another process (the listen loop) picks the toggle up from the store.
    fresh: dict[str, str] = {}
    sync_feature_env(store, environ=fresh)
    assert ci_watch_enabled(env=fresh) and morning_enabled(env=fresh)

    # A stored Off wins over a .env On.
    set_feature(store, "morning", False, environ={})
    loaded = {"DISCORD_OS_MORNING": "1"}
    sync_feature_env(store, environ=loaded)
    assert not morning_enabled(env=loaded)
    store.close()


def test_sync_leaves_env_alone_without_a_toggle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    environ = {"DISCORD_OS_CI_WATCH": "1"}
    sync_feature_env(store, environ=environ)
    assert environ == {"DISCORD_OS_CI_WATCH": "1"}
    store.close()


def test_channel_features_are_per_channel(tmp_path: Path, monkeypatch) -> None:
    _clean_env(monkeypatch)
    store = _store(tmp_path)
    assert set_feature(store, "capture", True, channel_id="ch").on
    assert capture_first_enabled(store, "ch", env={})
    assert not capture_first_enabled(store, "other", env={})
    assert not set_feature(store, "capture", False, channel_id="ch").on
    assert not capture_first_enabled(store, "ch", env={})

    assert set_feature(store, "pm-inbox", True, channel_id="ch").on
    assert pm_inbox_channel_id(store, env={}) == "ch"
    elsewhere = feature_states(store, channel_id="other")
    inbox = next(s for s in elsewhere if s.feature.name == "pm-inbox")
    assert not inbox.on and "ch" in inbox.note
    # Off from another channel does not close this channel's inbox.
    set_feature(store, "pm-inbox", False, channel_id="other")
    assert pm_inbox_channel_id(store, env={}) == "ch"
    set_feature(store, "pm-inbox", False, channel_id="ch")
    assert pm_inbox_channel_id(store, env={}) == ""
    store.close()


def test_env_only_state_names_the_env_key(tmp_path: Path, monkeypatch) -> None:
    _clean_env(monkeypatch)
    monkeypatch.setenv("DISCORD_OS_CAPTURE_CHANNELS", "ch")
    store = _store(tmp_path)
    capture = next(s for s in feature_states(store, channel_id="ch") if s.feature.name == "capture")
    assert capture.on and capture.source == "env"
    assert "DISCORD_OS_CAPTURE_CHANNELS" in capture.note
    store.close()


def test_bad_requests_raise(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for name, channel in (("nope", "ch"), ("capture", "")):
        try:
            set_feature(store, name, True, channel_id=channel, environ={})
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(name)
    store.close()


def test_cli_round_trip(tmp_path: Path, monkeypatch, capsys) -> None:
    from agent_discord.cli import main

    _clean_env(monkeypatch)
    ws = tmp_path / ".agent-discord"
    ws.mkdir()
    monkeypatch.setenv("AGENT_DISCORD_WORKSPACE", str(ws))
    assert main(["features", "on", "ci-watch"]) == 0
    assert "CI watcher: on" in capsys.readouterr().out
    assert main(["features", "on", "capture"]) == 2
    capsys.readouterr()
    assert main(["features", "on", "capture", "--channel-id", "ch"]) == 0
    capsys.readouterr()
    assert main(["features", "--channel-id", "ch", "--json"]) == 0
    rows = {row["name"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["ci-watch"]["on"] and rows["capture"]["on"]
    assert not rows["morning"]["on"]
    store = SQLiteStore(ws / "agent_discord.sqlite3")
    store.initialize()
    fresh: dict[str, str] = {}
    sync_feature_env(store, environ=fresh)
    assert fresh == {"DISCORD_OS_CI_WATCH": "1"}
    store.close()


def _features_slash(user: str, feature: str = "", state: str = "") -> dict[str, Any]:
    options = []
    if feature:
        options.append({"name": "feature", "value": feature})
    if state:
        options.append({"name": "state", "value": state})
    return _slash("features", user, options)


def test_features_slash_is_registered_and_operator_only(tmp_path: Path, monkeypatch) -> None:
    _clean_env(monkeypatch)
    names = {command["name"] for command in OPT_IN_COMMANDS}
    assert "features" in names
    _store(tmp_path, owner="owner-1").close()

    denied = handle_interaction_payload(
        _features_slash("stranger-9", "morning", "on"), workspace=tmp_path, roots=[tmp_path]
    )
    assert "Denied" in denied["data"]["content"]

    listed = handle_interaction_payload(
        _features_slash("owner-1"), workspace=tmp_path, roots=[tmp_path]
    )
    assert "Morning summary: off" in listed["data"]["content"]

    flipped = handle_interaction_payload(
        _features_slash("owner-1", "capture", "on"), workspace=tmp_path, roots=[tmp_path]
    )
    assert flipped["data"]["content"] == "Capture first: on"
    store = _store(tmp_path)
    assert capture_first_enabled(store, "ch", env={})
    store.close()


def _more(value: str, user: str) -> dict[str, Any]:
    payload = _click(MORE_ID, user)
    payload["data"] = {"custom_id": MORE_ID, "values": [value]}
    return payload


def test_panel_features_menu_toggles_for_operators_only(tmp_path: Path, monkeypatch) -> None:
    _clean_env(monkeypatch)
    store = _store(tmp_path, owner="owner-1")
    recorder = _Recorder()
    assert handle_gateway_interaction(store, "ch", _more(FEATURES_ID, "owner-1"), opener=recorder) == "features"
    menu = recorder.bodies[-1]["data"]
    ids = [b["custom_id"] for row in menu["components"] for b in row["components"]]
    assert f"{FEATURE_TOGGLE_PREFIX}morning:on" in ids

    toggle = f"{FEATURE_TOGGLE_PREFIX}morning:on"
    assert handle_gateway_interaction(store, "ch", _click(toggle, "stranger-9"), opener=recorder) == "denied"
    assert store.get_preference("_host", "feature:morning") is None

    assert handle_gateway_interaction(store, "ch", _click(toggle, "owner-1"), opener=recorder) == "feature"
    assert store.get_preference("_host", "feature:morning") == "1"
    updated = recorder.bodies[-1]
    assert updated["type"] == 7
    ids = [b["custom_id"] for row in updated["data"]["components"] for b in row["components"]]
    assert f"{FEATURE_TOGGLE_PREFIX}morning:off" in ids
    store.close()
