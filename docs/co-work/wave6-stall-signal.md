# Wave 6 — Live stall one-liner (opt-in)

After **N steers without progress**, the Live card may show one quiet stall line.

## Opt-in

```bash
export DISCORD_OS_STALL_STEERS=1   # enable
export DISCORD_OS_STALL_N=3        # optional threshold (default 3, clamp 2–20)
```

## Behavior

- Live progress card appends: `Stall? N steers without progress — …`
- Quiet — no channel storm, no second JobPool.
- Off by default.

Brand: **board + brain lakes**. ReflexGrad-inspired signal only — not TextGrad inside the cook loop.
