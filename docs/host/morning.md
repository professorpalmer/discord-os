# Morning summary

One card on the HOST channel, once per local day, at a fixed time. Off by
default. When it is on, there is nothing to schedule, no recipe to pick, and no model run. The
[overnight brief](../recipes/overnight-brief.md) is the opposite shape — a
schedule you write that buys one cook. This is free and automatic.

## What it says

Up to five lines, red first:

```text
Morning · 2026-10-02
- CI red on discord-os (master)          [ Cook: CI red on discord-os (master) ]
- discord-os: PR #68 checks red          [ Cook: discord-os: PR #68 checks red ]
- discord-os: 1 open PR(s), 4 open issue(s)
- 2 job(s) failed overnight
- Needs open: 3 — DOS-10007:failed deploy
```

Sources, all deterministic:

- bound realms' PR and CI state, from [repo-status](../realms/repo-status.md)
- completed / failed latest runs in the last 16 hours (`count_settled_since`)
- open Needs, gate parks, catch-up skipped and spend, from
  `orchestration/overnight_pack.py` `collect_overnight_facts`

Spend appears only when it is known — never `$0` for an unpriced run.

## Silence

No lines means no post. This never announces that it ran, never prints a
doctor or liveness line, and never posts an empty "all clear".

## Once a day

The watermark is a SQLite preference, `morning_posted_on:<channel>`, holding
the local date. It is written whether or not a card went out, so a restart at
08:00 does not post a second summary and a quiet 07:30 stays a quiet day.

## The Cook buttons

A line gets a button only when it maps to an obvious ask — today that is a red
check, whose ask is a fixed get-CI-green prompt naming the repo and the PR or
branch. The button is **operator-only** and the cook is **not pre-approved**:
it goes through `on_ask` into JobPool like a typed ask, so the write gate
holds it. The plumbing is shared with the
[CI watcher](../realms/ci-watch.md) (`orchestration/cook_button.py`); the
prompt lives in SQLite under `cook_ask:<token>`, so a tap survives a restart
and an expired token cooks nothing.

## Defaults

| Knob | Default |
|---|---|
| `DISCORD_OS_MORNING` | off; `1` / `on` / `true` / `yes` turns it on |
| Toggle | `/features`, HOST More > Features, or `discord-os features on morning` ([features](features.md)) |
| `DISCORD_OS_MORNING_AT` | `07:30` local; a malformed value falls back to it |
| Where | the HOST channel only, from the listen tick |
| When | first tick at or after the hour, on an armed host |
| Lines | at most 5 |

## Code

- `src/agent_discord/orchestration/morning.py`
- `src/agent_discord/orchestration/cook_button.py`
- `src/agent_discord/orchestration/listen.py` —
  `_tick_morning_summary_best_effort`, gated on `host_channel_id`
- `src/agent_discord/persistence/sqlite.py` — `count_settled_since`
