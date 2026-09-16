# Wave 6 P1a — Dual-operator steer attribution

Live job cards show the last steer as a quiet footer bit:

```text
by:<operator_id> · <clip>
```

## Conflict NOTE (quiet, once)

When **two distinct operators** steer the same live run within ~120s **and** the
job has no board `claim` owner (`claimed_by`), Discord OS posts **one** NOTE in
the job thread:

```text
DOS-10001 · Dual steer (<@a> + <@b>) without claim — last footer wins; claim the job to own the lane.
```

No storm. No second JobPool. No graph editor (AMBIPOM/OrchVis lesson — attribution
only).

## Reuse

- Lineage event / node step `steer` (existing) — body includes the footer bit.
- Board `claim <DOS-*>` still owns the lane when set.

## Limits

Single JobPool. Phone Discord-native only. Brand: board + brain lakes.
