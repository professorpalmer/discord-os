# Wave 5 demo — board + brain lakes (&lt;15 min)

Filmable loop. Brand: **board + brain lakes** (product name: board + brain lakes). CU/docker/mailbox parked.

## Loop

1. **Harden** — `DISCORD_OS_REQUIRE_OPERATORS=1`, Pair×2 (2 min)
2. **Desk-pack** — `discord-os add desk-pack --channel-id ID --realm puppetmaster` (1 min)
3. **Brain lake** — `discord-os add brain --channel-id ID --dri alex` (1 min)
4. **Dual ask** — two operators Ask / steer (3 min)
5. **Handoff envelope** — `handoff <@peer>: … | constraints=… | expecting=…` then re-send → `already_claimed` (3 min)
6. **Board Catch-up** — schedule `board catch-up: nightly` or Off→Catch-up Conflicts (2 min)
7. **Gate park** — park one write/ask gate (2 min)

## Done when

- [ ] Brain bind live; handoff receipt shows clipped envelope
- [ ] Same handoff_id refused while live
- [ ] Catch-up / board digest honest (no storm)
- [ ] Brand stays board + brain lakes; no multi-host brain-lake overclaim

See [wave5-handoff-envelope](wave5-handoff-envelope.md), [brain-lake](brain-lake.md), [board-catchup](board-catchup.md).
