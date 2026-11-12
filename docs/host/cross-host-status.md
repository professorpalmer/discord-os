# Cross-host status — read-only only

Multi-host is **status glance only**:

```bash
discord-os host hosts              # probe allowlisted hosts (no cook)
discord-os host hosts --no-probe   # ids/labels/kinds only
discord-os host hosts --json
```

Dashboard / status digest include the same public rows (`reachable` when probed).
No multi-host brain-lake, no second JobPool, no silent local ssh cook. SSH gates
stay opt-in; unknown host ids Deny (fail closed).
