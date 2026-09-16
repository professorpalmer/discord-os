# Parameterized recipe docs (Goose-shaped inputs)

Discord OS recipes stay **markdown playbooks** — Goose-shaped **inputs tables**
for operators, **no YAML recipe runtime**.

## Shared inputs vocabulary

| Input | Type | Required | Notes |
|---|---|---|---|
| `channel_id` | snowflake | yes | Desk / forum / Jobs channel |
| `workspace_id` | string | no | Default `default` |
| `realm` | string | no | Checkout cook bind (`add desk-pack`) |
| `dri` | Discord user | when brain | `add brain --dri` |
| `role` | enum | no | `implementer\|reviewer\|planner` |
| `forum_id` | snowflake | forum lane | Existing tags only |
| `schedule_prompt` | text | overnight | Prefer `overnight brief:` tag |
| `operators` | Pair×N | shared desk | `REQUIRE_OPERATORS=1` |

## Recipe → inputs

### Shared-desk demo

| Input | Example |
|---|---|
| `channel_id` | Jobs / desk channel |
| `operators` | Pair×2 |
| `realm` | `puppetmaster` |

See [shared-desk-demo](../co-work/shared-desk-demo.md).

### Desk-pack

| Input | Example |
|---|---|
| `channel_id` | required |
| `realm` | `puppetmaster` |
| `wiki_url` / `wiki_token` | optional |
| `github_token` | optional |

See [desk-pack](../co-work/desk-pack.md).

### Overnight brief

| Input | Example |
|---|---|
| `channel_id` | scheduled channel |
| `schedule_prompt` | `overnight brief: summarize Needs` |
| `every_s` | e.g. `28800` |

See [overnight-brief](../co-work/overnight-brief.md) + [wave6-overnight-pack](../co-work/wave6-overnight-pack.md).

### Forum lane

| Input | Example |
|---|---|
| `forum_id` | guild forum channel |
| tags | manual `queued/running/done/…` (+ optional Spec Kit phases) |

See [forum-lane](../co-work/forum-lane.md) + [wave6-speckit-tags](../co-work/wave6-speckit-tags.md).

### Wave 6 board + brain demo

| Input | Example |
|---|---|
| `channel_id` | desk |
| `dri` | brain owner |
| phone | Discord-native only — **no** Tailscale/ttyd/filebrowser |

See [wave6-board-brain-demo](../co-work/wave6-board-brain-demo.md).

## What this is not

- No Goose YAML engine / CI recipe runner.
- No CRHQ skills clone.
- HARD parks: mailbox, CU/docker, multi-host DO, second JobPool, auto forum tags.
