# Wave 6 P1c — Overnight brief structured pack

Schedule prompts tagged `overnight brief:` (also `overnight brief`,
`[overnight-brief]`) inject a structured pack before the **one** JobPool ask:

| Block | Cap |
|---|---|
| Needs | ≤5 |
| Live | ≤5 |
| Gate parks | ≤5 |
| Spend snapshot | unknown ≠ $0 honesty |
| Catch-up skipped count | integer |

## Honesty

| HOST when due | Behavior |
|---|---|
| On + armed | Pack inject → one JobPool ask (same cards as human Ask) |
| Off / disarmed | Existing Catch-up path — **one** briefing, no storm |

No mailbox / CRHQ fleet. Compose lives in `orchestration/overnight_pack.py`.

## Example

```bash
discord-os schedule --every 24h --channel-id CHANNEL_ID \
  "overnight brief: summarize open Needs, live jobs, and gate parks. Keep it short."
```

See also [overnight-brief](overnight-brief.md).
