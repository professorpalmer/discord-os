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
watermarks — no parallel ticket queue.

```bash
# Fail closed unless the channel is actually a forum + bot can list threads:
discord-os add realm tickets --channel-id FORUM_ID --forum
```

In-channel `bind <name>` on a forum channel auto-marks `forum=true` in
binding metadata after a REST type + active-threads probe. Text channels
stay unmarked.

### Tags-as-tickets (deepen)

When the forum already has `available_tags` whose **names** match conventional
JobPool statuses, Discord OS maps them onto ticket status and `PATCH`es the
post thread's `applied_tags` as the job moves:

| Tag name aliases (case-insensitive) | JobPool `TaskStatus` |
|---|---|
| queued / pending / open / new / todo | `pending` |
| running / working / in-progress / progress / live / active | `running` |
| done / completed / complete / success | `completed` |
| failed / fail / error / need / blocked | `failed` |
| cancelled / canceled / cancel / stopped | `cancelled` |

Honest limits:

- Does **not** create guild `available_tags` — you add the status tags on the
  forum in Discord. Soft-skip when none match.
- Preserves non-status tags already on the post (priority, area, …); swaps
  only the status tag; Discord max **5** applied tags.
- Sync runs best-effort on job start (`running`) and terminal settle
  (completed / failed / cancelled). ACL miss → spoken **Need**, cook continues.
- Catalog `forum-tags` stays **experiment** (not a second desk UI).

| Fail closed (spoken **Need**) | When |
|---|---|
| Not a forum | `--forum` or probe sees type ≠ 15 |
| Missing perms | Cannot `GET …/threads/active` (401/403) |
| Tag apply denied | Cannot `PATCH …/channels/{thread}` `applied_tags` (401/403) |
| Required tags missing | Explicit require + no matching status tags |
| No token | `--forum` without resolvable bot token |

**Also:**

- The forum parent is **not** drained as a message channel; only post threads.
- Categories still may group realms visually later; this does not invent a
  desk-in-Discord or a second JobPool.
- Missing ACL on discovery posts a Need and skips that forum that tick.

Code: `src/agent_discord/host/forum_realm.py` (+ `modify_channel` /
`set_thread_applied_tags` in Discord REST). See [aws map](../aws/README.md).

## Code

- `src/agent_discord/host/realms.py` — parse, seed, bind, listen ids
- `src/agent_discord/host/forum_realm.py` — forum realm + tags-as-tickets (type 15 + JobPool + applied_tags)
- `src/agent_discord/host/repos.py` — catalog, name match, host reach
- `src/agent_discord/orchestration/listen.py` — `_absorb_bind`
- `src/agent_discord/persistence/sqlite.py` — `merge_binding_metadata` (must merge, not wipe)
