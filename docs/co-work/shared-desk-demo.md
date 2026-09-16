# Shared-desk demo (&lt;10 minutes)

Goal: two operators on one Discord OS HOST channel, with realm + memory bound, dual ask/steer, and a gate park — without CU/docker and without inventing screenshots.

## Preconditions

- Live host running (`com.discord-os.host` or `discord-os host run`)
- Bot in a **private** channel you control
- `OPENROUTER_API_KEY` set for the host
- Two Discord user accounts (you + peer)

## 1. Harden operators (1 min)

On the Mac env / `.env`:

```bash
DISCORD_OS_REQUIRE_OPERATORS=1
```

Restart or rely on env reload if your LaunchAgent already injects env. With REQUIRE_OPERATORS, dispatch **refuses** until someone is paired — no silent first-armed seed.

## 2. Pair ×2 (2 min)

1. HOST **On** (if Off).
2. HOST **More → Pair** — complete pairing for operator A.
3. From the peer account, Pair again for operator B.

Confirm both appear under operators / Roles. Only paired operators may ask and confirm Off.

## 3. Bind realm + memory (2 min)

In the HOST channel (as an operator):

```text
bind puppetmaster
bind memory
```

Or CLI:

```bash
discord-os add realm puppetmaster --channel-id YOUR_CHANNEL_ID
discord-os add memory --channel-id YOUR_CHANNEL_ID
```

Realm = checkout cook context. Memory = think-tank channel bind. Keep wiki/github optional for the demo.

## 4. Dual ask / steer (3 min)

1. Operator A: HOST **Ask** (or type a sentence) — a job thread opens.
2. Operator B: in that **live** thread, reply with a steer (or Ask a second parallel job if `DISCORD_OS_MAX_LIVE` allows).
3. Confirm Jobs / Need ranking shows both without token paste in chat.

Cancel on a live card interrupts that cook; Dismiss clears a failed Need.

## 5. Gate park (2 min)

1. Trigger a write-gate or tool-class park (Ask something that needs approval / gated tool).
2. From the job card, **park** / defer rather than “Always allow.”
3. Show the gate card stays spoken and recoverable — shared desks should not widen Always-allow.

## Done when

- [ ] REQUIRE_OPERATORS on; unpaired users cannot dispatch
- [ ] Two paired operators visible
- [ ] Realm + memory bound on the demo channel
- [ ] Two operators can ask/steer without sharing `.env`
- [ ] At least one gate parked (not Always-allow)

## Non-goals (this demo)

- Computer-use / docker CU (**parked**)
- SSH bridge default-on (**opt-in only**)
- Forum `available_tags` auto-create (**never**)
- Screenshots in docs until Cary drops real shots ([docs/screenshots](../screenshots/))

## See also

- [COMPARISON](../COMPARISON.md) — vs Cowork / CLI bridges / supervisor OS
- [host/README](../host/README.md) — On/Off, Pair, REQUIRE_OPERATORS
- [host/policy](../host/policy.md) — HARD locks
