# Wave 6 — Spec Kit lifecycle labels as manual forum tags

Optional map from Spec Kit-ish phase names onto **existing** forum
`available_tags`. Composed with `discord-os add forum-tags` refresh.

## Phases (aliases → key)

| Phase key | Example tag names (manual) |
|---|---|
| specify | specify, spec, specification |
| plan | plan, planning |
| tasks | tasks, task, breakdown |
| implement | implement, implementation, impl, coding |
| review | review, revise |

## HARD lock

- **Never** auto-create Discord `available_tags`.
- Missing tags → empty `lifecycle_tag_ids` (soft); add tags in Discord UI, then refresh.
- Status tags-as-tickets map (`status_tag_ids`) is unchanged; lifecycle is additive metadata.

```bash
discord-os add forum-tags --channel-id FORUM_ID
# → created_available_tags=false; may include lifecycle_tag_ids when present
```

Brand: **board + brain lakes**. No Linear dependency.
