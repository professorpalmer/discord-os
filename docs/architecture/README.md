# Architecture

Discord is the screen, identity, ACL, notification bus, and object plane. This process on one Mac is the computer.

```text
CLI / Discord
  → listen + JobPool
  → Orchestrator
       → backend (agentic/OpenRouter | optional Marionette | fake)
       → SQLite (bindings, tasks, runs, events, memory, artifacts, lineage, GitHub binds/rules, watermarks, gateway lock)
       → Discord facade → object store → REST (default) | optional SaseQ/BrainDAO | fake
```

JobPool caps at eight live jobs by default (`DISCORD_OS_MAX_LIVE`, tunable). Analyze can overlap; implement/swarm writes serialize per checkout. Real ceilings are OpenRouter RPM/TPM/spend, machine resources, and Discord limits — not a hard two-cook product voice. The host associates the ask to a named checkout and scans GitHub there before the worker. Each run writes a lineage DAG (`node_key = sha256(step, input, parents)`). Idle job threads stay listenable; each keeps its own listen watermark so parent HOST paints cannot hide unread follow-ups. The live Components v2 card is the console. Puppetmaster agentic / OpenRouter is compute on this host (or Path A SSH remote), not a Cursor fleet.

Intake is REST. Host opens a Gateway only for buttons. The SQLite gateway row is a one-process lock; a dead pid is stolen.

Stdlib-first. Tests inject fakes. No network in `pytest`.

## Honest limits

- Your server, your artifacts. Not a public CDN.
- 10 MiB default object cap.
- History older than that destination's listen watermark is ignored (first listen: now minus 15s). Session threads watermark separately from the parent channel.
- One Gateway owner per bot token.
- Live job ceiling is `DISCORD_OS_MAX_LIVE` (default 8), not unbounded.

## Layout

| Tree | Role |
|---|---|
| `src/agent_discord/cli.py` | Surface |
| `src/agent_discord/host/` | Realms, tools, wiki, memory, panel, add |
| `src/agent_discord/orchestration/` | Jobs, listen, cards, orchestrator |
| `src/agent_discord/discord/` | REST, facade, objects |
| `src/agent_discord/puppetmaster/` | Compute backends |
| `src/agent_discord/persistence/` | SQLite |

AWS names for these boxes live in [docs/aws](../aws/README.md). Query: `discord-os map`.

Optional Discord MCP adapters: see [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) at the repo root. Upstream source is not copied.
