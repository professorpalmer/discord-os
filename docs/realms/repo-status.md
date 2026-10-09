# Repo status card

Eighteen of forty-one real asks were "any open PRs/issues on X?". That answer
is two `gh` calls and three `git` calls, so it never buys a worker. The card is
deterministic: no model, no cook, no OpenRouter spend.

## From Discord

Ask in a bound realm, or name a host checkout:

```text
any open PRs on discord-os?
open issues on Puppetmaster
status of marionette
```

One card lands in the job thread and the job settles Completed without a
dispatch.

## What the card says

```text
discord-os · professorpalmer/discord-os
Branch: dev (ahead 5, behind 2 vs origin/dev)
Last commit: 74a01c2 Delete the loopback companion web dashboard
CI on master: green (tests)
Open PRs (2):
- #68 Fold brain lakes into host memory by professorpalmer — checks red
- #70 Morning summary by contributor — checks green
Open issues: 4
- #41 Repo status card
- #40 CI watcher
- #35 Two-tier swarm
```

Check rollup is `green` / `red` / `pending` / `none`, parsed by the same
`github_wake._checks_from_rollup` the PR wake uses. Default-branch CI is
`green` / `red` / `pending` / `unknown` — an unreadable run list stays
**unknown**, never green.

Without `gh`, or with `gh` signed out, the card drops the PR and issue
sections and prints the `discord-os add github` sign-in line plus the git
facts it could still read.

## The matcher is narrow

`host/repo_status.is_repo_status_ask` fires only when the ask reads as a
question about state. Any verb that asks for work wins, so these still cook:

```text
fix the status bar
fix CI on marionette
open a PR against dev
write a status page for the repo
```

The orchestrator also requires a resolved checkout, so a status-shaped ask
that names no repo falls through to a normal cook.

## From the CLI

```bash
discord-os repo status              # every host checkout
discord-os repo status marionette
discord-os repo status --json
```

## Code

- `src/agent_discord/host/repo_status.py` — matcher, collector, card, payload
- `src/agent_discord/orchestration/orchestrator.py` — `_deterministic_repo_status`
  closes the run without a worker; `repo_status_collector` is injected by
  `cli listen`, so an unwired orchestrator still cooks
- `src/agent_discord/cli.py` — `discord-os repo status`
