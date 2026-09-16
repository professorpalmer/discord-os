# Wave 5 — blackboard `claim <job_code>`

Volunteer take on an existing Need / live JobPool task:

```text
claim DOS-A1B2
```

- Operator-only (`author_may_dispatch`)
- JobPool required
- Sets metadata `claimed_by` + `lane` (default `board`)
- If another operator already claimed while live → `already_claimed`

Not a second JobPool. Not a CRDT multi-writer board.
