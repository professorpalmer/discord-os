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

## Listen-dead phone notify (watchdog)

When the listen / host KeepAlive process is already dead, desk
`discord-os host doctor --notify` (or a cron / LaunchAgent that runs it) is
how the phone learns. REST-up on another machine does not help — this posts
from the desk using the bot token + `host.json` channel id.

Example crontab (every 2 minutes):

```cron
*/2 * * * * discord-os host doctor --notify >>/tmp/discord-os-doctor-notify.log 2>&1
```

Real install (not example-only): `setup`, `host start`, and
`discord-os host doctor --install-watchdog` call
`install_doctor_notify_watchdog` — writes
`~/Library/LaunchAgents/com.discord-os.doctor-notify.plist` and best-effort
`launchctl bootstrap` (StartInterval, **not** KeepAlive — intentional Off
stays quiet once `host.pid` is cleared). Also keeps a workspace
`.plist.example` for operators who prefer cron:

```bash
discord-os host doctor --install-watchdog
# or cron:
# */2 * * * * discord-os host doctor --notify >>/tmp/discord-os-doctor-notify.log 2>&1
```

Helpers: `install_doctor_notify_watchdog` / `render_doctor_notify_plist` /
`write_doctor_notify_example` / `doctor_notify_cron_example` in
`src/agent_discord/host/install.py`.

## Gateway WS ACK liveness

On/Off buttons need the Discord Gateway heartbeat ACK path. REST-up ≠
receiving. Discord OS tracks READY + last op-11 ACK age (Hermes-shaped).
Unhealthy ACK age / closed socket ranks as HOST **Need** (`gateway BAD`) and
doctor **FAIL**. Cold start / intentional REST-only stays quiet (low FP).
Once the panel gateway is **expected** (`note_gateway_expected` on listen
start), never-READY past grace → spoken Need (quiet forever is a fault).

Code: `src/agent_discord/discord/gateway_health.py` + listen digest / doctor.

## Not this

- Not a second product / status board
- Not Activities
- Not Puppetmaster (cook backend) — liveness is inline
- Dashboard stays read-only

## Quiet listen drain (timeout / Errno 49)

REST intake retries transient network errors (HTTP 502/503/504, `TimeoutError`,
macOS **Errno 49** `EADDRNOTAVAIL`, connection reset / refused / unreachable).
The listen loop **quiet-logs** those after REST retries — it does **not** invent
Gateway **READY** and does not escalate a Need storm every poll tick. Real
non-transient drain failures still print `listen drain failed: …`.

Panel Gateway READY still requires a real Discord WS `READY` event
(`note_ready`). `note_gateway_expected` alone is not READY.

