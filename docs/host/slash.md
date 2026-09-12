# Slash progressive enhancement (P2.9)

Phone autocomplete for bind / status / stop without replacing text listen.

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
| `/bind` | `bind` / `/bind` | Optional `name`: realm, `memory`, or `host <id>` |
| `/status` | `/status` | Read-only digest; never mutates power |
| `/on` | `/on` | Arms channel; may seed owner if empty |
| `/off` | `/off` | Disarms |
| `/stop` | `/off` | Phone alias — same disarm |
| `/open` | `/open` | Existing |
| `/connect` | `/connect` | Existing; never accepts a secret option |

**Not registered:** `/add`. Use `discord-os add …` or in-channel `bind`.

## Wiring

Handlers open workspace SQLite and reuse power/bind parse + absorb helpers. HOST card paint stays on the Gateway listen loop. Slash ACK is ephemeral.

Code: `src/agent_discord/discord/interactions.py`.
