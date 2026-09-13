# Slash progressive enhancement (P2.9 / Discord-half P2)

Phone autocomplete for bind / job / status / stop without replacing text listen.

## Default off

| Knob | Default |
|---|---|
| `AGENT_DISCORD_INTERACTIONS` | `off` — no slash registration, no Interactions HTTP |
| Text listen + HOST panel | Always the poverty path |

Opt in only when you want Discord application-command autocomplete on phone:

```bash
AGENT_DISCORD_INTERACTIONS=http
DISCORD_PUBLIC_KEY=…          # Developer Portal → General Information
DISCORD_APPLICATION_ID=…
discord-os interactions --register
discord-os interactions --serve
# paste YOUR public HTTPS URL into Interactions Endpoint URL (not a chat paste)
```

## Registered aliases

| Slash | Same as text | Notes |
|---|---|---|
| `/bind` | `bind` / `/bind` | Optional `name` with **autocomplete** (realms, `memory`, `host <id>`) |
| `/job` | (read-only) | Required `code` with **DOS-*** autocomplete; richer ephemeral (task/run/intake/settle/dest) |
| `/clear-needs` | HOST More / `jobs clear-needs --failed` | Requires `failed=True` (fail-closed); optional `dry_run` |
| `/status` | `/status` | Read-only digest; never mutates power |
| `/on` | `/on` | Arms channel; may seed owner if empty |
| `/off` | `/off` | Disarms |
| `/stop` | `/off` | Phone alias — same disarm |
| `/open` | `/open` | Existing |
| `/connect` | `/connect` | Existing; never accepts a secret option |

**Not registered:** `/add`. Use `discord-os add …` or in-channel `bind`.

After `pip install -U discord-os` (and host bounce), re-run:

```bash
discord-os interactions --register
```

so Discord picks up new commands (`/job` autocomplete, `/clear-needs`, richer
option flags). Skipping re-register leaves the phone on the old command set.

## Autocomplete

Discord type-4 focus events return up to 25 choices:

- `/bind name` — host repos + aliases, `memory`, allowlisted `host <id>`
- `/job code` — recent `DOS-*` codes from workspace SQLite (channel-scoped when known)

Re-run `discord-os interactions --register` after upgrading so Discord sees
`autocomplete: true` on those options.

## Wiring

Handlers open workspace SQLite and reuse power/bind parse + absorb helpers. HOST card paint stays on the Gateway listen loop. Slash ACK is ephemeral. `/job` never mutates job state.

Code: `src/agent_discord/discord/interactions.py`.
