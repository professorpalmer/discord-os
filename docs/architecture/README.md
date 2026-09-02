# Architecture

Discord is the screen, identity, ACL, notification bus, and object plane. This process on one Mac is the computer.

```text
CLI / Discord
  → listen + JobPool
  → Orchestrator
       → backend (agentic | cursor | optional Marionette | fake)
       → SQLite (bindings, tasks, runs, events, memory, artifacts, lineage, watermarks, gateway lock)
       → Discord facade → object store → REST (default) | optional SaseQ/BrainDAO | fake
```

JobPool runs two Discord threads at once. Implement writes serialize per checkout. Each run writes a lineage DAG (`node_key = sha256(step, input, parents)`). The live Components v2 card is the console. Puppetmaster is compute on this host, not a fleet.

Intake is REST. Host opens a Gateway only for buttons. The SQLite gateway row is a one-process lock; a dead pid is stolen.

Stdlib-first. Tests inject fakes. No network in `pytest`.

## Honest limits

- Your server, your artifacts. Not a public CDN.
- 10 MiB default object cap.
- History older than the listen watermark is ignored (first listen: now minus 15s).
- One Gateway owner per bot token.

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
