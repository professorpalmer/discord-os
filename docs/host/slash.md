# Slash progressive enhancement (P2.9 / Discord-half P2)

Phone autocomplete for bind / job / status / stop without replacing text listen.

## Default off

| Knob | Default |
|---|---|
| `AGENT_DISCORD_INTERACTIONS` | `off` — no slash registration, no Interactions HTTP |
| Text listen + HOST panel | Always the poverty path |

Two opt-in modes. `gateway` is the cheap one: no public URL, no public key.

### `gateway` — slash on the Gateway the host already owns

When the app has **no** Interactions Endpoint URL, Discord delivers
APPLICATION_COMMAND (type 2) and AUTOCOMPLETE (type 4) as `INTERACTION_CREATE`
on the Gateway. The panel listen socket already reads that event, so slash
needs no second process and no tunnel. Still **one** Gateway (HARD lock 4).

```bash
AGENT_DISCORD_INTERACTIONS=gateway
DISCORD_APPLICATION_ID=…      # registration POSTs against this; no public key
# Host self-heals slash registration on listen (version-aware).
discord-os listen --channel-id ID --announce-host
```

Leave the Developer Portal Interactions Endpoint URL **empty** — setting it
flips Discord to HTTP delivery and the Gateway stops seeing commands.

### `http` — public HTTPS endpoint

```bash
AGENT_DISCORD_INTERACTIONS=http
DISCORD_PUBLIC_KEY=…          # Developer Portal → General Information
DISCORD_APPLICATION_ID=…
# Host self-heals slash registration on listen (version-aware).
# Optional manual: discord-os interactions --register
discord-os interactions --serve
# paste YOUR public HTTPS URL into Interactions Endpoint URL (not a chat paste)
```

Either exposed mode hardens the operator allowlist (`require_operators`):
state-changing slash commands need a paired operator. `discord-os host doctor`
prints the resolved mode.

## Self-heal (policy #7)

When `AGENT_DISCORD_INTERACTIONS` is exposed (`http` / public / `gateway`), the listen host
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
| `/ask` | HOST Ask modal | Required `prompt`; optional `realm` with **autocomplete**. Dispatch rule + `requester_id` match the modal. Ephemeral `On it.` receipt |
| `/job` | (read-only) | Required `code` with **DOS-*** autocomplete; richer ephemeral (task/run/intake/settle/dest) |
| `/clear-needs` | HOST More / `jobs clear-needs --failed` | Requires `failed=True` (fail-closed); optional `dry_run` |
| `/status` | `/status` | Read-only digest; never mutates power |
| `/on` | `/on` | Arms channel; may seed owner if empty |
| `/off` | `/off` | Disarms |
| `/stop` | `/off` | Phone alias — same disarm |
| `/open` | `/open` | Existing |
| `/connect` | `/connect` | Existing; never accepts a secret option |
| `/features` | HOST More > Features / `discord-os features` | Optional `feature` and `state` choices. No options lists the opt-ins. See [features.md](features.md) |

**Not registered:** `/add`. Use `discord-os add …` or in-channel `bind`.

## Message context menu

`Send to Discord OS` is an application command of **type 3** (MESSAGE):
right-click a message on desktop, long-press on phone. Discord puts the
picked message in `data.resolved.messages[target_id]`, so the host reads its
content and attachments without a channel fetch. The ask it enqueues starts
with a `from <author> in <#channel>` provenance line and lists the
attachments by filename and URL. Operator-only; the receipt is ephemeral.

After `pip install -U discord-os` (and host bounce), self-heal re-registers on
the next listen when the package version / command stamp drifts. Manual
`--register` is still fine (updates the same stamp). Skipping both leaves the
phone on the old command set until the next successful heal.

## User-install (commands that follow you)

Registered commands declare `integration_types [0, 1]` (GUILD_INSTALL,
USER_INSTALL) and `contexts [0, 1, 2]` (GUILD, BOT_DM, PRIVATE_CHANNEL), so
`/ask` and `Send to Discord OS` work in a guild the bot was never added to,
in the bot DM, and in a group DM.

Developer Portal steps (once per app):

1. **Installation** → **Installation Contexts**: tick **User Install** (keep
   **Guild Install** for the host server).
2. **Install Link**: choose **Discord Provided Link**. Copy it.
3. **Default Install Settings** → **User Install** → scopes:
   `applications.commands`. Guild Install keeps `bot` + `applications.commands`
   and the bot permissions the host channel needs.
4. Open the copied link yourself and **Add to my apps**.
5. Re-register so Discord sees the new fields: bounce `discord-os listen`
   (self-heal is stamp-aware) or run `discord-os interactions --register`.

How Discord OS answers one of these:

- The interaction carries `authorizing_integration_owners`. No guild-install
  key (or `context` 2) means the bot is not where the command was typed, so
  the reply goes out on the **interaction webhook** — never channel REST.
- There is no channel of ours to cook in, so the ask lands in the **home
  channel** from the store's bindings (first bound realm / memory channel).
  `/ask realm:<name>` still picks a specific bound channel.
- The gate is the **operator allowlist, fail closed**: only a paired operator,
  even on an unpaired desk where the in-server panel is still open (lock 8).
  No first-armed-human seed from outside the server.
- The ephemeral receipt carries a jump link to the channel the job thread
  opens in, when the binding knows its guild.

## Autocomplete

Discord type-4 focus events return up to 25 choices:

- `/bind name` — host repos + aliases, `memory`, allowlisted `host <id>`
- `/ask realm` — same source as `/bind name`
- `/job code` — recent `DOS-*` codes from workspace SQLite (channel-scoped when known)

`/ask` needs the listen host: the enqueue hook is the listen process's ask
queue, so a bare `discord-os interactions --serve` answers with an honest
"needs the listen host queue" instead of pretending to cook.

Self-heal (or `discord-os interactions --register`) after upgrading so Discord
sees `autocomplete: true` on those options.

## Wiring

Handlers open workspace SQLite and reuse power/bind parse + absorb helpers. HOST card paint stays on the Gateway listen loop. Slash ACK is ephemeral. `/job` never mutates job state.

In `gateway` mode `cli.py` `on_dispatch` sends type 2 / 4 payloads to
`route_gateway_interaction`, which calls the same
`handle_interaction_payload` the HTTP server uses and POSTs the returned
callback dict to `/interactions/{id}/{token}/callback`. Component and modal
interactions still fall through to the HOST panel's `custom_id` routing.

Code: `src/agent_discord/discord/interactions.py`
(`route_gateway_interaction`, `maybe_self_heal_slash_registration`).
