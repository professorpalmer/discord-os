# Realms

One Discord channel is one checkout. Bounce `#puppetmaster` / `#dugout` / `#marionette` on the phone. Same Mac disk. Implement writes serialize on that cwd, not on the channel id.

Hermes steal: platform + channel = room. Not Bot Mode chrome.

## Bind

```text
bind puppetmaster
bind dugout
```

or

```bash
discord-os add realm puppetmaster --channel-id ID
```

or `.env`:

```bash
DISCORD_OS_CHANNELS=puppetmaster:ID,dugout:ID
DISCORD_OS_REPOS=puppetmaster:/Users/you/Projects/Puppetmaster
```

Repos also auto-discover git roots under `~/Projects` for known names (puppetmaster, dugout, marionette, discord-os, wiki).

## Who wins cwd

1. The prompt **names** a repo → that checkout
2. Else the channel bind
3. Else `PUPPETMASTER_CWD` (often the Discord OS runtime — not a product repo)

The host scans GitHub on that checkout before dispatch. The worker prompt starts with `Associated: <name> at <path>`. Do not hunt.

`.agent-discord` is never the subject repository.

## Code

- `src/agent_discord/host/realms.py` — parse, seed, bind, listen ids
- `src/agent_discord/host/repos.py` — catalog, name match, host reach
- `src/agent_discord/orchestration/listen.py` — `_absorb_bind`
- `src/agent_discord/persistence/sqlite.py` — `merge_binding_metadata` (must merge, not wipe)

## Forum-as-realm (Discord-half P2 — skipped)

**Skipped (not S–M).** Discord forum channels as a second realm / job system
would duplicate JobPool + session threads. The AWS catalog ranks
`forum-tags` as **never** for that reason. Categories may later group realms
visually; forums are not a checkout bind surface. See
[aws map](../aws/README.md) and `src/agent_discord/data/aws_catalog.json`.

