# Handoff / peer-task (JobPool-only)

From a live host channel (JobPool running):

```text
handoff <@peer_user_id>: please finish the tests
peer 223512539240202240 triage this Need
handoff <@peer>: finish tests | constraints=no-push | expecting=ci-green | brain_dri=alex
```

- Both author and peer must be operators (`author_may_dispatch`)
- Without JobPool → spoken Need refuse
- Submits via **JobPool only** with typed **handoff envelope** metadata
  (`handoff_id`, from/to, optional constraints/expecting/freshness/supersedes/roe_hint/brain_dri)
- Same `handoff_id` while live → `already_claimed` (no second cook)
- Receipt cards show clipped envelope + operator/lane; preamble keeps `[meat-proxy-cut]` + brain block

Wave 5 detail: [wave5-handoff-envelope](wave5-handoff-envelope.md).
