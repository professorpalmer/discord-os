# Shared-desk demo (&lt;15 minutes)

Goal: filmable dual-operator desk — Pair×2, desk-pack, dual ask/steer, **handoff**,
**overnight brief schedule**, gate park — without CU/docker and without inventing
screenshots. Real shots: [docs/screenshots](../screenshots/).

## Preconditions

- Live host running (`com.discord-os.host` or `discord-os host run`)
- Bot in a **private** channel you control
- `OPENROUTER_API_KEY` set for the host
- Two Discord user accounts (you + peer)

## 1. Harden operators (1 min)

```bash
DISCORD_OS_REQUIRE_OPERATORS=1
```

Restart or rely on LaunchAgent env. Dispatch **refuses** until someone is paired.

## 2. Pair ×2 (2 min)

1. HOST **On** (if Off).
2. HOST **More → Pair** — operator A.
3. Peer account: Pair again for operator B.

Only paired operators may ask and confirm Off.

## 3. Desk-pack bind (2 min)

```bash
discord-os add desk-pack --channel-id YOUR_CHANNEL_ID --realm puppetmaster
```

Or in Discord: `bind puppetmaster` then `bind memory`. Optional wiki/github later.

## 4. Dual ask / steer (3 min)

1. Operator A: HOST **Ask** — a job thread opens.
2. Operator B: steer in that live thread (or Ask a second job if `DISCORD_OS_MAX_LIVE` allows).
3. Confirm Jobs / Need ranking — no token paste in chat.

**Cancel** interrupts a live cook; **Dismiss** clears a failed Need.

## 5. Handoff / peer-task (2 min)

From the HOST channel (JobPool live), as an operator:

```text
handoff <@PEER_USER_ID>: please finish the tests from this thread
```

Both parties must be operators. Without JobPool → spoken Deny. Receipt shows
operator/lane when known. See [handoff](handoff.md).

## 6. Overnight brief schedule (2 min)

```bash
discord-os schedule --every 24h --channel-id YOUR_CHANNEL_ID \
  "Overnight brief: open Needs, live jobs, gate parks — short."
discord-os schedule --list --channel-id YOUR_CHANNEL_ID
```

Call out Catch-up honesty: Off → one `skipped_while_disarmed` Catch-up, not a storm.
Full playbook: [overnight-brief](overnight-brief.md).

## 7. Gate park (2 min)

1. Ask something that needs a write-gate / tool park.
2. **Park** / defer — do not “Always allow.”
3. Gate card stays spoken and recoverable.

## Done when

- [ ] REQUIRE_OPERATORS on; unpaired cannot dispatch
- [ ] Two paired operators
- [ ] Desk-pack (realm+memory) on the demo channel
- [ ] Dual ask/steer without sharing `.env`
- [ ] One handoff/peer line demonstrated (or Deny without pool — honest)
- [ ] One schedule listed with `next_ms`
- [ ] At least one gate parked

## Non-goals

- Computer-use / docker CU (**parked**)
- SSH bridge default-on (**opt-in only**)
- Forum `available_tags` auto-create (**never**)
- External agent mailbox (**parked**)
- Invented screenshots

## See also

- [recipes index](../recipes/README.md) — versioned playbooks
- [COMPARISON](../COMPARISON.md) — vs Cowork / bridges / supervisors
- [host/policy](../host/policy.md) — HARD locks
