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

## Forum-as-realm (Discord-half EXTRAS — scoped experiment)

**Experiment, not a second job system.** Bind a Discord **forum** channel
(type 15 / `GUILD_FORUM`) as a normal realm checkout. New forum **posts**
become JobPool intake with `thread_id = post thread` and
`channel_id = forum parent` (cwd / bind key). Reuses `JobPool` + listen
watermarks — no parallel ticket queue, no forum-tags-as-types product.

```bash
# Fail closed unless the channel is actually a forum + bot can list threads:
discord-os add realm tickets --channel-id FORUM_ID --forum
```

In-channel `bind <name>` on a forum channel auto-marks `forum=true` in
binding metadata after a REST type + active-threads probe. Text channels
stay unmarked.

| Fail closed (spoken **Need**) | When |
|---|---|
| Not a forum | `--forum` or probe sees type ≠ 15 |
| Missing perms | Cannot `GET …/threads/active` (401/403) |
| No token | `--forum` without resolvable bot token |

**Limits (honest):**

- Forum tags are **not** ticket types (catalog `forum-tags` = experiment for
  post→JobPool intake only — not tag taxonomy).
- The forum parent is **not** drained as a message channel; only post threads.
- Categories still may group realms visually later; this does not invent a
  desk-in-Discord or a second JobPool.
- Missing ACL posts a Need and skips that forum's discovery that tick.

Code: `src/agent_discord/host/forum_realm.py`. See [aws map](../aws/README.md).

## Code

- `src/agent_discord/host/realms.py` — parse, seed, bind, listen ids
- `src/agent_discord/host/forum_realm.py` — forum experiment (type 15 + JobPool)
- `src/agent_discord/host/repos.py` — catalog, name match, host reach
- `src/agent_discord/orchestration/listen.py` — `_absorb_bind`
- `src/agent_discord/persistence/sqlite.py` — `merge_binding_metadata` (must merge, not wipe)
