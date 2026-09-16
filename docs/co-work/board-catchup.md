# Board catch-up (Wave 4)

Cron / Catch-up honesty that **scans the message-board state** for ADR/PR
coordination tax — not a second JobPool, not a Durable Objects board.

## What it does

1. While HOST **Off**, overdue schedules still post one Catch-up with
   `skipped_while_disarmed` (unchanged) **plus** a Conflicts section when
   Need/Live jobs share ADR or PR refs.
2. While HOST **On**, schedules whose prompt looks like a board digest
   (`board catch-up:…`, `digest:…`, `[board-catchup]`) post the conflict
   scan **without** starting a cook (no storm).

## Swim-lane relationships

HOST Jobs last-job line may append `Lanes: DOS-12 ↔ DOS-15 via ADR-003 …`
when two active jobs share an ADR/PR/checkout. Forum tags stay manual.

## Limits

- Heuristic text scan of intake/summary (+ task metadata).
- Single-host SQLite. No multi-host brain-lake sync.
