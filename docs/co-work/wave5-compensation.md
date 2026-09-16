# Wave 5 — Handoff compensation NOTE (SagaLLM-lite)

When a **peer/handoff** JobPool cook settles **failed** or **cancelled**, Discord OS posts a parent-thread **NOTE** and records a lineage edge. This is **not** a distributed saga.

## Behavior

- Trigger: intake metadata has `peer_task` / `handoff_id` / meat-proxy cut, and run status is `failed` or `cancelled`.
- Posts: `NOTE: handoff compensation id=… status=…` on the parent thread (or channel).
- Lineage: step `handoff_compensation`.
- Honest limit: single-host JobPool notification — no multi-host compensating transactions.

## Filmable check

1. `handoff @peer …` with JobPool live.
2. Cancel or fail the peer cook.
3. Parent thread shows the compensation NOTE; HOST lineage / progress ledger may surface the edge.

## Wave 6 extension

Failed Live (not only handoff peers) also get a human **recovery beat** — see [wave6-recovery-beat](wave6-recovery-beat.md).
