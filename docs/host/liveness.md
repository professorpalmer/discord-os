# Host liveness

P0.2. Desk `doctor` and the loopback dashboard stay on the Mac. Unhealthy
digest ranks as a HOST **Need**. Discord OS does **not** post doctor / liveness
lines to the host channel. Discord mobile pushes on channel posts — that
vendor is removed (0.5.87). 0.5.60 debounce was not enough.

## What the phone sees

| Surface | Behavior |
|---|---|
| HOST Jobs / card description | Unhealthy digest ranks as **Need: HOST power … · pid … · doctor …** (same Need ranking as parked / failed jobs). |
| Host channel post | Never. Listen tick and `doctor --notify` refresh state only. |
| `doctor --notify` | Same. `--notify` / watchdog / cron do not send a Discord message. |

Spoken format (Need / CLI / tests only — not a channel post):

```text
Discord OS host · power OK · pid DEAD · doctor FAIL · host.pid dead · Discord OS
```

No bot tokens, SSH targets, or credentials in Need lines.

## Debounce

Listen-loop checks are rate-limited (default 60s). State updates on that
interval. No Discord announce.

## Code

- `src/agent_discord/host/liveness.py` — digest, Need line, tick, `--notify`
- Listen poll: `drain_inbound` → `tick_host_liveness` (state only)
- HOST panel Jobs: `merge_host_need_jobs`
- Companion dashboard JSON may include a read-only `liveness` field (no write API)

## Desk usage

```bash
discord-os host doctor           # print coherence lines
discord-os host doctor --notify  # refresh Need state; never posts
```

HOST card Need is how the phone sees a dead pid / bad gateway while looking
at HOST. Channel mute is not required for doctor flaps.

## Listen-dead watchdog

`setup` / `host start` / `discord-os host doctor --install-watchdog` may still
install `com.discord-os.doctor-notify` (StartInterval, not KeepAlive). That
job runs `host doctor --notify` and does **not** post. Intentional Off stays
quiet once `host.pid` is cleared.

Helpers: `install_doctor_notify_watchdog` / `render_doctor_notify_plist` /
`write_doctor_notify_example` / `doctor_notify_cron_example` in
`src/agent_discord/host/install.py`.

## Gateway WS ACK liveness

On/Off buttons need the Discord Gateway heartbeat ACK path. REST-up ≠
receiving. Discord OS tracks READY + last op-11 ACK age (Hermes-shaped).
Unhealthy ACK age / closed socket ranks as HOST **Need** (`gateway BAD`) and
doctor **FAIL**. Cold start / intentional REST-only stays quiet (low FP).
Once the panel gateway is **expected** (`note_gateway_expected` on listen
start), never-READY past grace → Need (quiet forever is a fault).

When READY + connected but heartbeat ACK is stale (zombie WS: TCP up, Discord
not ACKing), `run_discord_gateway` raises reconnectable `GatewayClosed` so the
panel loop opens a fresh socket. `note_connected` clears prior READY/ACK so
reconnect does not thrash as ACK-stale before the next READY.

A socket that finishes the handshake and takes Hello but never dispatches
**READY** is the same fault with no ACK to go stale. `run_discord_gateway`
arms a READY deadline (30s after Hello, `ready_deadline_s`) and raises
reconnectable `GatewayClosed`.

Never-READY past grace is `ok=False, ready=False`. Doctor and the liveness
digest read **`ok`**, not `ready` — a gateway that never came up is FAIL /
`gateway BAD`, never a quiet OK line. Only a process that expects a panel
gateway (`gateway_is_expected`) persists `gateway_health.json`, so the
`doctor --notify` LaunchAgent cannot stamp its own never-READY-but-quiet
snapshot over the host's verdict.

Code: `src/agent_discord/discord/gateway_health.py` + `realtime.py` + listen
digest / doctor.

## Panel Gateway reconnect

One Gateway per bot token (HARD lock 4) — this is the single panel socket
reconnecting, not a second gateway.

* **Backoff.** `gateway_backoff_delay(attempt)` is exponential with full
  jitter, base 1s, cap 60s, floor 0.25s. The old flat 0.4s/1.0s sleep wrote
  thousands of `gateway URL lookup failed` lines an hour on a sleeping or
  offline Mac. A session that reaches READY/RESUMED resets the ladder.
* **RESUME.** `GatewaySession` carries `session_id`, last `s`, and
  `resume_gateway_url` across sockets. Reconnect dials the resume URL and
  sends op 6; no session, or a refused resume, falls back to op 2 IDENTIFY.
* **op 7** closes and resumes. **op 9** waits 1-5s, then resumes (`d=true`)
  or re-identifies with a fresh session (`d=false`). op 9 is never fatal —
  it used to disarm the channel and exit the host with code 1.
* **Close codes.** `WebSocketError.close_code` carries the peer's RFC 6455
  code. Fatal (disarm + `discord_down`): 4004, 4010, 4011, 4012, 4013, 4014.
  4007 / 4009 reconnect but re-identify. Everything else resumes.
* **Write lock.** The heartbeat thread and the dispatch thread share one
  socket; both `WebSocketClient` and the gateway's `send` serialize behind a
  lock so frames cannot interleave (Discord closes 4002).

## Not this

- Not a second product / status board
- Not Activities
- Not Puppetmaster (cook backend) — liveness is inline
- Dashboard stays read-only
- Status digest (`/status`, On) is a separate RO facts post — not doctor FAIL

## Quiet listen drain (timeout / Errno 49)

REST intake retries transient network errors (HTTP 502/503/504, `TimeoutError`,
macOS **Errno 49** `EADDRNOTAVAIL`, connection reset / refused / unreachable).
The listen loop **quiet-logs** those after REST retries — it does **not** invent
Gateway **READY** and does not escalate a Need storm every poll tick. Real
non-transient drain failures still print `listen drain failed: …`.

Panel Gateway READY still requires a real Discord WS `READY` event
(`note_ready`). `note_gateway_expected` alone is not READY.
