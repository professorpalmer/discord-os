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
# Host self-heals slash registration on listen (version-aware).
# Optional manual: discord-os interactions --register
discord-os interactions --serve
# paste YOUR public HTTPS URL into Interactions Endpoint URL (not a chat paste)
```

## Self-heal (policy #7)

When `AGENT_DISCORD_INTERACTIONS` is exposed (`http` / public), the listen host
**self-heals** slash registration — same effect as
`discord-os interactions --register`. It is **version-aware**: re-registers when
the installed `discord-os` package version changes or the opt-in command-set
stamp differs (new slash options / autocomplete flags). State lives in
workspace `slash_registration.json`. Optional `DISCORD_GUILD_ID` (or
`listen --guild-id`) registers guild commands for faster Discord
propagation; unset → application-global.

**Fail soft:** missing `DISCORD_APPLICATION_ID`, bot token, or public key does
**not** crash the host. Doctor prints WARN honesty; listen continues on the
text + HOST path. Optional manual re-register remains:

```bash
discord-os interactions --register
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

After `pip install -U discord-os` (and host bounce), self-heal re-registers on
the next listen when the package version / command stamp drifts. Manual
`--register` is still fine (updates the same stamp). Skipping both leaves the
phone on the old command set until the next successful heal.

## Autocomplete

Discord type-4 focus events return up to 25 choices:

- `/bind name` — host repos + aliases, `memory`, allowlisted `host <id>`
- `/job code` — recent `DOS-*` codes from workspace SQLite (channel-scoped when known)

Self-heal (or `discord-os interactions --register`) after upgrading so Discord
sees `autocomplete: true` on those options.

## Wiring

Handlers open workspace SQLite and reuse power/bind parse + absorb helpers. HOST card paint stays on the Gateway listen loop. Slash ACK is ephemeral. `/job` never mutates job state.

Code: `src/agent_discord/discord/interactions.py` (`maybe_self_heal_slash_registration`).
