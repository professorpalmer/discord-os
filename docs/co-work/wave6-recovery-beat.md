# Wave 6 — Human recovery beat (ParaRecover-lite)

After a **failed peer/Live** JobPool settle, Discord OS posts a spoken **recovery beat**:
diagnostic tip + **Retry / Dismiss** controls. Extends the Wave 5 handoff
compensation NOTE toward human-readable recovery.

## Behavior

- Trigger: run status `failed` / `cancelled` (any Live, including peer handoff).
- Posts: `Recovery (Live|peer/Live) … · Diagnostic — … · Controls: Retry or Dismiss`.
- Lineage: step `recovery_beat`.
- Card actions: Continue + **Retry** + **Dismiss** (JobPool-only).
- Honest limit: not a ParaRecover eval harness; single-host notification.

## Filmable check

1. Fail a Live cook (or cancel a peer handoff).
2. Parent thread / channel shows the recovery beat; failed card offers Retry/Dismiss.
3. Compensation NOTE (handoff peers) may still appear alongside.

Brand: **board + brain lakes**. HARD parks unchanged.
