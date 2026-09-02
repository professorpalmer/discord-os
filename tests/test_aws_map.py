"""AWS=Discord analog catalog is packaged JSON and a local CLI."""

from __future__ import annotations

import json

from agent_discord.aws_map import (
    RANKS,
    analog_payload,
    analogs,
    filter_rank,
    format_table,
    lift_payload,
    lifts,
    load_catalog,
    lookup,
)
from agent_discord.contracts import DiscordObjectRef


def test_catalog_loads_and_ranks_are_closed():
    payload = load_catalog()
    assert "one Mac" in payload["thesis"]
    rows = analogs(payload)
    world = lifts(payload)
    assert len(rows) >= 20
    assert len(world) >= 6
    assert {row.rank for row in rows} <= RANKS
    assert {row.rank for row in world} <= RANKS
    assert all(row.aws and row.discord for row in rows)
    assert all(item.id and item.adapt for item in world)


def test_s3_analog_is_snowflake_not_cdn_url():
    hits = lookup("S3")
    assert len(hits) == 1
    row = hits[0]
    assert "snowflake" in row.discord.lower()
    assert row.module.endswith("object_store.py")
    assert "CDN URL" in row.note


def test_object_ref_has_no_url_field():
    ref = DiscordObjectRef(
        channel_id="1",
        message_id="2",
        attachment_id="3",
        filename="a.bin",
        kind="blob",
        size=4,
        sha256="abcd",
    )
    assert "url" not in ref.__dataclass_fields__
    dumped = analog_payload(lookup("S3")[0])
    assert "url" not in dumped


def test_never_rejects_second_cloud_and_activities():
    never = filter_rank("never")
    names = {row.aws for row in never}
    assert "CloudFront" in names
    assert "Amplify" in names
    assert "VPC" in names
    assert "Organizations" in names


def test_now_lifts_include_steer_and_write_key():
    world = {item.id: item.rank for item in lifts()}
    assert world["write-key-cwd"] == "shipped"
    assert world["thread-poll"] == "shipped"
    assert world["cli-compute-mode"] == "shipped"
    assert "execution-lineage" in world


def test_lookup_miss_is_empty():
    assert lookup("not-a-real-aws-service") == ()
    assert "no analogs matched" in format_table(())


def test_lookup_lifts_finds_write_key():
    from agent_discord.aws_map import lookup_lifts

    hits = lookup_lifts("write-key")
    assert any(item.id == "write-key-cwd" for item in hits)


def test_lambda_analog_names_cwd_lock():
    row = lookup("Lambda reserved concurrency")[0]
    assert "cwd" in row.discord.lower()
    assert row.rank == "shipped"


def test_lift_payload_is_json_safe():
    json.dumps([lift_payload(item) for item in lifts()])


def test_cli_map_s3_is_local(capsys):
    from agent_discord.cli import main

    assert main(["map", "s3"]) == 0
    out = capsys.readouterr().out.lower()
    assert "snowflake" in out
    assert main(["map", "not-a-real-aws-service"]) == 1


def test_cli_map_prints_lifts_and_json_miss_fails(capsys):
    from agent_discord.cli import main

    assert main(["map", "write-key"]) == 0
    out = capsys.readouterr().out.lower()
    assert "write-key-cwd" in out
    assert main(["map", "--json", "not-a-real-aws-service"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["analogs"] == []
    assert payload["lifts"] == []

