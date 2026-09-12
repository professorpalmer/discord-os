# Host liveness (phone-visible)

P0.2. Desk `doctor` and the loopback dashboard do not wake the phone when
LaunchAgent / `host.pid` dies mid-cowork. Discord OS keeps a **thin host
digest** and surfaces it where the phone already looks.

## What the phone sees

| Surface | Behavior |
|---|---|
| HOST Jobs / card description | Unhealthy digest ranks as **Need: HOST power … · pid … · doctor …** (same Need ranking as parked / failed jobs). |
| Host channel post | On digest **change** (FAIL or recovery), a short spoken status line is posted. Discord mobile already pushes on channel posts — not a second push vendor. |
| `doctor --notify` | Desk / cron path: when doctor FAIL (or pid dead), post the same digest to the host channel from `host.json`. |

Example post:

```text
Discord OS host · power OK · pid DEAD · doctor FAIL · host.pid dead · Discord OS
```

No bot tokens, SSH targets, or credentials in posts or Need lines.

## Debounce

Listen-loop checks are rate-limited (default 60s) and post **only on signature
change**. Healthy first-boot stays quiet. Recovery after FAIL posts once.

## Code

- `src/agent_discord/host/liveness.py` — digest, Need line, debounced tick, `--notify`
- Listen poll: `drain_inbound` → `tick_host_liveness` (primary channel)
- HOST panel Jobs: `merge_host_need_jobs`
- Companion dashboard JSON may include a read-only `liveness` field (no write API)

## Desk usage

```bash
discord-os host doctor           # print coherence lines
discord-os host doctor --notify  # on FAIL, post digest to host channel
```

When the listen process is already dead, `--notify` (or a cron that runs it) is
how the phone learns. While the host is up but degraded (stale gateway, bad
LaunchAgent workspace, etc.), the listen tick posts on change and the HOST card
shows Need.

## Not this

- Not a second product / status board
- Not Activities
- Not Puppetmaster (cook backend) — liveness is inline
- Dashboard stays read-only
