# Cross-host status — read-only only

Multi-host is **status glance only**. No multi-host brain-lake, no second
JobPool, no silent local ssh cook. SSH gates stay opt-in.

## Commands

```bash
# Probe allowlisted hosts (local path exists / ssh soft probe)
discord-os host hosts
discord-os host hosts --no-probe   # ids only
discord-os host hosts --json

# Dashboard JSON once includes probe_hosts=True
discord-os host dashboard --once
```

## Snapshot fields

Each host row: `id`, `label`, `kind`, optional `reachable` + `detail`.
**Never** includes SSH `target` or secrets.

Status digest / signature may show `lab:ok` / `lab:down`.

## Fail closed

- Unknown host id → Deny (existing allowlist).
- `kind=ssh` unreachable → reported down; cook still Denies (never silent local).
