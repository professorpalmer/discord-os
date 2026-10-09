# Recipes (versioned playbooks)

Discord OS **recipes** are durable playbooks — checked-in markdown with a
version in the product CHANGELOG — not prompt soup and not a CRHQ skills clone.

Cadence: when a shareability wave ships a user-visible playbook, list it here
and bump the package version. Prefer composing JobPool / cards / listen / HOST
over new planes.

## Current recipes

| Recipe | Where | Cadence note |
|---|---|---|
| Parameterized recipe inputs (Goose-shaped) | [parameterized.md](parameterized.md) | Docs only — no YAML runtime |
| Wave 7 TTFP / cold-start | [ttfp-demo.md](ttfp-demo.md) | Stopwatch to first Done; Discord phone |
| Wave 6 board + brain demo | [board-brain-demo.md](board-brain-demo.md) | Discord phone; spend meter glance |
| Shared-desk demo (&lt;15 min) | [shared-desk-demo](shared-desk-demo.md) | Pair×2, desk-pack, dual ask, handoff, overnight brief, gate park |
| Board catch-up (ADR/PR) | [board-catchup](board-catchup.md) | Catch-up + digest schedules |
| Brain lake / meat-proxy cut | [brain-lake](../memory/brain-lake.md) | `add brain` + handoff lake context |
| Overnight brief | [overnight-brief](overnight-brief.md) | `schedule` + Catch-up `skipped_while_disarmed` |
| Desk-pack inject | [desk-pack](../realms/desk-pack.md) | realm+memory(+wiki/github) |
| Handoff / peer-task | [handoff](../jobs/handoff.md) | JobPool-only |
| Schedule deepen | [schedule](../jobs/schedule.md) | `--list` / `--every` |
| Forum lane | [forum-lane](../realms/forum-lane.md) | Existing tags only; never auto-create `available_tags` |
| Cross-host RO | [cross-host-status](../host/cross-host-status.md) | `discord-os host hosts`; fail-closed allowlist |
| Mailbox | Not shipped. Use job threads and handoff. | **PARKED** |

## Policy / positioning

- HARD locks: [host/policy](../host/policy.md)
- Vs nearby products: [COMPARISON](../COMPARISON.md)

## What is not a recipe

- Ad-hoc channel prompts without a checked-in playbook
- External agent mailboxes (parked)
- Computer-use / docker (parked)
- Multi-host brain-lake / second JobPool
