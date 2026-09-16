# Wave 5 — typed handoff envelope

Board + brain lakes handoff is a **schema on JobPool**, not free-text paste.

## Envelope fields (task metadata)

| Field | Required | Notes |
|---|---|---|
| `handoff_id` | yes | Explicit `id=…` / `handoff_id=…` or stable hash of from\|to\|prompt |
| `from` / `to` | yes | Operator Discord ids (`handoff_from` / `handoff_to` aliases) |
| `constraints` | optional | e.g. `constraints=no-push` |
| `expecting` | optional | Success signal the peer aims for |
| `freshness` | yes | Default `ms:<epoch_ms>` |
| `supersedes` | optional | Prior handoff id |
| `roe_hint` | optional | When to escalate to humans (gates) |
| `brain_dri` | optional | Brain-lake DRI label |

## Idempotent claim

Re-dispatch of the **same** `handoff_id` while a live/parked cook exists → spoken
`Need: handoff already_claimed … — no second live cook.`

## Example

```text
handoff <@PEER>: finish tests | constraints=no-push | expecting=ci-green | brain_dri=alex
handoff <@PEER> id=abc123: same work again   # → already_claimed if abc123 still live
```

Preamble still includes `[meat-proxy-cut]` + brain block + `[handoff-envelope]`.
