# Recipes (versioned playbooks)

Discord OS **recipes** are durable playbooks — checked-in markdown with a
version in the product CHANGELOG — not prompt soup and not a CRHQ skills clone.

Cadence: when a shareability wave ships a user-visible playbook, list it here
and bump the package version. Prefer composing JobPool / cards / listen / HOST
over new planes.

## Current recipes

| Recipe | Where | Cadence note |
|---|---|---|
| Wave 5 board + brain demo | [co-work/wave5-board-brain-demo](../co-work/wave5-board-brain-demo.md) | desk-pack → brain → handoff envelope → board catch-up |
| Shared-desk demo (&lt;15 min) | [co-work/shared-desk-demo](../co-work/shared-desk-demo.md) | Pair×2, desk-pack, dual ask, handoff, overnight brief, gate park |
| Board catch-up (ADR/PR) | [co-work/board-catchup](../co-work/board-catchup.md) | Catch-up + digest schedules |
| Brain lake / meat-proxy cut | [co-work/brain-lake](../co-work/brain-lake.md) | `add brain --dri` + handoff lake context |
| Overnight brief | [co-work/overnight-brief](../co-work/overnight-brief.md) | `schedule` + Catch-up `skipped_while_disarmed` |
| Desk-pack inject | [co-work/desk-pack](../co-work/desk-pack.md) | realm+memory(+wiki/github) |
| Handoff / peer-task | [co-work/handoff](../co-work/handoff.md) | JobPool-only |
| Schedule deepen | [co-work/schedule](../co-work/schedule.md) | `--list` / `--every` |
| Forum lane | [co-work/forum-lane](../co-work/forum-lane.md) | Existing tags only; never auto-create `available_tags` |
| Cross-host RO | [co-work/cross-host-ro](../co-work/cross-host-ro.md) | `discord-os host hosts`; fail-closed allowlist |
| Mailbox | [co-work/mailbox-park](../co-work/mailbox-park.md) | **PARKED** |

## Policy / positioning

- HARD locks: [host/policy](../host/policy.md)
- Vs nearby products: [COMPARISON](../COMPARISON.md)
- Lift notes (no CRHQ clone): [co-work/crhq-audit](../co-work/crhq-audit.md)

## What is not a recipe

- Ad-hoc channel prompts without a checked-in playbook
- External agent mailboxes (parked)
- Computer-use / docker (parked)
- Multi-host brain-lake / second JobPool
