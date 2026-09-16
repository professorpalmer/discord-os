# Wave 6 — HOST phone spend meter + Halt honesty

Glanceable session spend on the Discord HOST panel and `/status` digest. **Honesty meter** — not a fleet hard-cap / SpendGuard product.

## Strip schema

| Bit | Meaning |
|---|---|
| ASCII meter | `progress_bar` fill when **cap known** and spend **known** |
| `spent` | `format_spend` → `$x.xxxx` or `unknown` (missing `cost_usd` ≠ `$0`) |
| `cap` | `$y.yyyy` or `cap none` |
| `known` / `unknown` | Provider cost recorded this session? |
| `halted` | Badge when Halt is on (or soft-cap tripped) |

### Cap known

```
[====........] 33% · $0.4200 / $1.2500 · halted
```

Spend unknown with cap set (empty meter, no invented dollars):

```
[............] ? · unknown / $10.0000 · unknown
```

### Cap none

```
$0.4200 · cap none · known
unknown · cap none · unknown
```

## Halt

Halt still stops new JobPool admits. Badge shares the spend strip so phone filmings catch cost + stop in one glance.

## vs Ledger / SpendGuard

Discord OS **meters and Halts** on this Mac desk. We do **not** sell a multi-tenant spend firewall, FinOps dashboard, or hard-cap fleet product. Policy: unknown ≠ $0.

## Parks

No companion Tailscale/ttyd/filebrowser strip. No second JobPool.
