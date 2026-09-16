# Handoff / peer-task (JobPool-only)

From a live host channel (JobPool running):

```text
handoff <@peer_user_id>: please finish the tests
peer 223512539240202240 triage this Need
```

- Both author and peer must be operators (`author_may_dispatch`)
- Without JobPool (no live host pool) → spoken Need refuse
- Submits via **JobPool only** with metadata `peer_task` / `handoff_from` / `handoff_to` / `lane=handoff`
- Receipt cards show operator + lane attribution when intake is known
