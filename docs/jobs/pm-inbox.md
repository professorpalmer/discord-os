# Puppetmaster job inbox

Turn it on or off with `/features`, HOST More > Features, or
`discord-os features on pm-inbox`. See [features](../host/features.md).

Work the operator starts somewhere else on this Mac — Marionette, the Claude
Code MCP server, a bare `puppetmaster` shell — gets one live Discord card so it
finds the phone. See [jobs](README.md).

Observe is **read-only**. Discord OS never cooks an observed job: the JobPool
and HARD lock 3 are not in this path. The only writes are the three Puppetmaster
verbs an operator asks for from the card or its thread.

## Turn it on

OFF until a channel is named:

```bash
discord-os add pm-inbox --channel-id 123456789
```

That writes `DISCORD_OS_PM_INBOX_CHANNEL` into the host `.env` and records the
moment the inbox opened. The env var alone is also honored, so a LaunchAgent can
carry it. `discord-os host doctor` prints `OK pm-inbox off …` or
`OK pm-inbox on channel=… state_dirs=N`, and warns when it can see no other
Puppetmaster state dir on the machine. `discord-os add list` shows the channel.

Jobs that were already running when the inbox opened are **not** carded: opening
the inbox is not a request to replay every job this Mac has ever run.

## What a card shows

One card per job, in its own thread in the inbox channel, edited in place on
every status change — never a second post. Clipped goal preview (redacted
through `redaction.py`), status, task count, delivery verdict, and the job id.

Buttons appear only while Puppetmaster is holding the job for a human:
**Approve** → `puppetmaster approve <job_id>`, **Reject** →
`puppetmaster reject <job_id>`. Replying in the job's thread sends
`puppetmaster steer <job_id> <text>`.

There is no **Cancel** button. Puppetmaster 1.27.39 has no cancel verb, and this
product does not invent one.

Every button and every steer requires a paired operator
(`orchestration/service.py` `author_may_operate`). A non-operator tap gets an
ephemeral Denied and the card does not move.

## How discovery works

The observe tick runs in the listen loop next to the GitHub wake tick, at most
once every 20 s. Each pass:

1. List candidate Puppetmaster state dirs (`candidate_state_dirs`):
   `~/.puppetmaster`, then every immediate child of
   `~/Library/Application Support/puppetmaster/projects` — the per-project dirs
   Marionette and the MCP server use. Discord OS's own state dir
   (`puppetmaster/backend.py` `resolved_state_dir`) is dropped; those jobs
   already have job cards.
2. Per dir: `puppetmaster --state-dir DIR job-summaries --json --limit 25`.
3. A job id that is new gets `puppetmaster status <job_id> --compact` once, for
   `created_at` (to date it against the enable moment) and the human label.
4. A job id that is known is repainted only when its `status` or `revision`
   moved. Both are persisted in SQLite `pm_inbox_jobs`, keyed by job id, so a
   restart repaints nothing.
5. Thread replies newer than the stored `steer_after` watermark become steers.
   That watermark is seeded with the card's own message id when the thread is
   opened, so the first reply is steerable and nothing older than the card ever
   is. A row that somehow has no anchor seeds instead of steering — thread
   history is not a steer queue. `seen_messages` claims each reply, so a reply
   steers exactly once.

Subprocess env is `puppetmaster/backend.py` `worker_env`; the executable comes
from the one resolver, `config.py` `resolve_puppetmaster_cli`. Every CLI call is
best-effort: a failure, a timeout, or a state dir Puppetmaster rejects yields
nothing and never breaks the listen loop.

### Limits

- **Two roots only.** A state dir outside `~/.puppetmaster` and the projects
  root is invisible until it is listed in `DISCORD_OS_PM_INBOX_STATE_DIRS`
  (comma separated). Discord OS does not scan the disk looking for one.
- **Full summaries, not deltas.** Each tick re-reads up to 25 summaries per
  state dir rather than using `job-summary-changes --after-revision R`. At one
  pass per 20 s that is cheap, and it needs no per-dir revision bookkeeping to
  stay correct across restarts. A machine with many project dirs is the case
  that would want the delta verb.
- **Status words are a guess.** Approve / Reject show for the statuses in
  `PARKED_STATUSES`. A Puppetmaster release that renames a parked status hides
  the buttons; it does not post a wrong one.
- **No cost, no artifacts.** The card is label, status, task count, delivery.
  Spend receipts and artifacts stay with the tool that started the job.
- **One Discord OS.** The inbox is single-host, like the rest of the product.

## Code

- `src/agent_discord/orchestration/pm_inbox.py` — observe tick, card, buttons, steer
- `src/agent_discord/orchestration/listen.py` — `_tick_pm_inbox_best_effort`
- `src/agent_discord/host/panel.py` — `discord-os:pm-inbox:` button routing
- `src/agent_discord/host/add.py` — `add_pm_inbox`
- `src/agent_discord/host/doctor.py` — `_check_pm_inbox`
- `src/agent_discord/persistence/sqlite.py` — `pm_inbox_jobs`
- Tests: `tests/test_pm_inbox.py`
