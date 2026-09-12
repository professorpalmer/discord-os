# Discord RO status digest (phone)

P2.7. The loopback companion dashboard (`host dashboard` / `/api/status`) stays
on the desk. The phone needs the **same read-only facts** — power, spend, jobs,
allowlist ids — as a Discord post (mobile already pushes on channel posts).

## What the phone sees

| Trigger | Behavior |
|---|---|
| HOST **On** (panel or `/on`) | Force-post a spoken RO digest to the host channel (or status thread). |
| `/status` / `!status` | Force-post the same digest (does **not** change power). |
| Listen interval | Debounced on-change only (default 60s check). First baseline stays quiet. |

Example post:

```text
Discord OS status · v0.5.35 · power on · running · spend 0.0123/1.0000 · jobs DOS-10001:running · hosts lab · Discord OS
```

No bot tokens, SSH targets, workdirs, or credentials in posts.

## Debounce

Signature over `power` / running / spend / job code:status / allowlist **ids**.
Posts only on signature change (or force from On / `/status`). Same posture as
[liveness](liveness.md).

Optional:

```bash
# Post into a Discord thread instead of the channel root
DISCORD_OS_STATUS_THREAD_ID=THREAD_SNOWFLAKE

# Interval between checks (seconds). Default 60.
DISCORD_OS_STATUS_DIGEST_INTERVAL_S=60
```

## Fail closed

| Rule | Behavior |
|---|---|
| Read-only | Digest path never calls `set_host_control` / On / Off / Halt. |
| Snapshot | Reuses `build_status_snapshot` (dashboard builder). `readonly: false` payloads are refused. |
| Secrets | Allowlist ids / labels / kinds only — never `target` / ssh user@host. |

## Code

- `src/agent_discord/host/status_digest.py` — signature, format, debounced tick
- Listen poll: after liveness → `tick_status_digest`
- Power text: `/on` and `/status` force-post
- HOST panel On: REST post via bot token
- Dashboard builders unchanged (digest is a consumer)

Puppetmaster is the cook backend — unused here; digest is inline (same as liveness).

## Not this

- Not a second product / status board
- Not Activities
- Not a dashboard write API
- Does not replace thin host liveness Need (P0.2) — that stays for FAIL/pid
