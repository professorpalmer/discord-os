# Setup

First run is three facts: bot token, application id, one staff channel. Then `discord-os setup`. After that the host is the computer: SQLite, JobPool, Puppetmaster, Discord as the screen.

There is no setup wizard. A 20-prompt walk fights the product (Discord is the screen). `setup` does invite + login helper + HOST card once. Everything else is `discord-os add` or an in-channel `bind`.

## First run

Browser (once):

1. Developer Portal → New Application → Bot → Reset Token → `DISCORD_BOT_TOKEN`
2. Enable Message Content Intent
3. Application ID → `DISCORD_APPLICATION_ID`
4. Copy a private channel ID

Machine:

```bash
pip install discord-os puppetmaster-ai
discord-os bootstrap
# edit .env
discord-os setup --channel-id YOUR_CHANNEL_ID
```

Open the invite. Press On.

## After setup (`add`)

```bash
discord-os add realm puppetmaster --channel-id ID
discord-os add memory --channel-id ID
discord-os add repo dugout --path ~/Projects/dugout
discord-os add wiki --url https://portablellm.wiki/you --token …
discord-os add github --token ghp_...
# or on this Mac: gh auth login
discord-os add tool aws --bin aws --hint "aws sts get-caller-identity"
discord-os add list
```

Realm and memory also write SQLite so a running host sees them on the next poll. Wiki, repo, tool, and github write `.env` — restart the host so the process sees them.

From Discord: `bind puppetmaster`, `bind memory`. Same SQLite rows. No slash `/add`.

### Slash (opt-in)

Discord OS stays text-first. Slash is **opt-in** and default **off** (`AGENT_DISCORD_INTERACTIONS=off`). Text bind / power / open verbs and the HOST panel remain the supported path.

When you opt in (`AGENT_DISCORD_INTERACTIONS=http`), the listen host **self-heals**
slash registration (version-aware — re-registers when the installed package
version or command-set stamp changes). Missing application id / token / public
key fails soft (doctor WARN; host does not crash). Optional manual re-register
remains. Serve still needs a public HTTPS tunnel:

```bash
# .env: AGENT_DISCORD_INTERACTIONS=http  DISCORD_PUBLIC_KEY=…  DISCORD_APPLICATION_ID=…
# Host listen self-heals registration; optional manual:
discord-os interactions --register   # guild or global thin aliases
discord-os interactions --serve      # loopback /interactions; tunnel → Developer Portal URL
```

Registered aliases (same verbs as text; no `/add`): `/bind`, `/status`, `/on`, `/off`, `/stop` (alias of `/off`), plus existing `/open` and `/connect`. Phone autocomplete only — listen message-prefix is unchanged. See [slash](../host/slash.md).

## Code

- `src/agent_discord/cli.py` — `cmd_setup`, `cmd_add`
- `src/agent_discord/host/add.py` — dotenv upsert + binds
- `src/agent_discord/bootstrap.py` — workspace + `.env` template
- `src/agent_discord/host/install.py` — login helper
