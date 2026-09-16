# Overnight brief recipe

Compose **existing** `schedule` + Catch-up honesty into a Discord channel playbook.
No second mailbox, no CRHQ fleet, no new control plane.

## Goal

While you sleep (or the desk is Off), due schedules do not storm On.
When the HOST is armed and On, a scheduled ask lands as a normal JobPool job in
the channel. While Off / disarmed, overdue items collapse into **one** Catch-up
briefing with `skipped_while_disarmed`, then bump forward.

## Setup (&lt;5 min)

1. HOST channel with operators (prefer `DISCORD_OS_REQUIRE_OPERATORS=1` + Pair).
2. Bind realm (and memory if you want think-tank context):

```bash
discord-os add desk-pack --channel-id CHANNEL_ID --realm puppetmaster
# or: bind puppetmaster / bind memory in Discord
```

3. Arm a morning brief (example — adjust interval/prompt):

```bash
discord-os schedule --every 24h --channel-id CHANNEL_ID \
  "Overnight brief: summarize open Needs, live jobs, and gate parks. Keep it short."
discord-os schedule --list --channel-id CHANNEL_ID
```

4. Leave HOST **On** overnight for the brief to fire as a real job, **or** leave
   Off — you will get one Catch-up line instead of a backlog storm.

## Honesty contract

| HOST state when due | What happens |
|---|---|
| On + armed | Schedule fires → JobPool ask in channel (same cards/lanes as a human Ask) |
| Off / disarmed | Due schedules **skipped_while_disarmed**; at most one **Catch-up** post; `next_ms` bumped |

Do not invent a digest mailbox. Status digest / liveness stay separate seams.

## Filmable check

- [ ] `schedule --list` shows `next_ms` / `created_by`
- [ ] Off overnight → one Catch-up, no N jobs on On
- [ ] On overnight → one brief job thread, Cancel/Dismiss work as usual

## See also

- [schedule](schedule.md) — CLI deepen
- [shared-desk-demo](shared-desk-demo.md) — fold this into the &lt;15 min demo
- [host/README](../host/README.md) — Catch-up / armed behavior

## Structured pack (Wave 6 P1c)

Prompts tagged `overnight brief:` inject Needs / Live / gate parks / spend /
Catch-up skipped before the single JobPool ask. Details:
[wave6-overnight-pack](wave6-overnight-pack.md).

