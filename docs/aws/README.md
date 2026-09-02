# AWS = Discord

Discord is the screen, identity, ACL, notification bus, and object plane. This process on one Mac is the computer. AWS names here are **analogs**, not a second cloud.

The catalog is packaged JSON. Query it without Discord:

```text
discord-os map
discord-os map s3
discord-os map --rank now
discord-os map --json
```

Ranks:

| Rank | Meaning |
|---|---|
| shipped | Already the product |
| now | Fits Discord + one host; do next |
| next | Fits, but needs a Discord primitive we do not use yet |
| never | Breaks product truths (hosted fleet, CDN URL keys, second UI, MCP-inside-Discord) |

## How to read a row

Each analog names the AWS service, the Discord or host primitive, the owning module, and a constraint. `S3` is attachments addressed by channel/message/attachment snowflakes plus sha256. The CDN URL is a fetch, never the key.

World lifts (arxiv, OpenHands durable handles, Restate human-in-the-loop, Discord Components v2 / snapshots) live in the same JSON under `lifts`. `discord-os map write-key` finds them. Adaptation is always: SQLite + Discord REST on this Mac.

## Do not lift

- A Temporal/Step Functions cluster
- Discord Activities as a second dashboard
- Per-realm bot tokens or VPC-style isolation of the Mac disk
- Forum channels as a second job system
- Persisting Discord CDN URLs

## Code

- `src/agent_discord/data/aws_catalog.json` — source of truth
- `src/agent_discord/aws_map.py` — load / lookup
- Tests: `tests/test_aws_map.py`
