# CI watcher and one-tap Fix CI

A bound realm's repo goes red; the channel says so once and offers the fix.
This is the unbound half of the PR wake: [github_wake](../jobs/README.md)
follows PRs a job already owns, the watcher follows the GitHub remotes of host
checkouts that are bound to a channel. Same `claim_github_wake` dedupe table,
no parallel system.

## What is watched

Only repos that are GitHub remotes of a host checkout (`host/repos.py`
`github_slugs_for`). Within those:

- open PRs whose base is `main` or `dev` and whose head has a failed check
- the default branch, when its newest workflow run concluded red

One card per failing **head SHA**. A new push to the same PR is a new SHA and
therefore a new card; a re-poll of the same SHA is silent.

```text
CI red
professorpalmer/discord-os · PR #68 · abc123d
Failing: tests (3.11)
https://github.com/professorpalmer/discord-os/actions/runs/9
[ Fix CI ]
```

## The button

`Fix CI` is **operator-only**. A non-operator tap gets an ephemeral Denied and
the card does not change.

The cook is **not pre-approved**. The button enqueues a fixed get-CI-green
prompt through `on_ask` into JobPool, exactly like a typed ask, so the write
gate holds it the same way. The prompt names the PR, the sanitized failing
check names (`github_wake._check_label`), and the run URL; the PR title rides
along quoted as data, never as instructions.

The prompt is stored in SQLite preferences under `fix_ci:<sha12>` when the
card is posted, so the button survives a restart. A tap whose prompt is gone
returns `fix-ci-expired` and cooks nothing.

## Defaults

| Knob | Default |
|---|---|
| `DISCORD_OS_CI_WATCH` | on; `0` / `off` / `false` / `no` disables |
| Where it runs | the listen tick, parent-channel pass only |
| When it runs | armed channels with a bound realm and a gh-authed host |
| When it posts | only with a failing head; silent otherwise |

Without `gh`, or with `gh` signed out, the collector returns nothing and the
channel stays quiet — this never posts doctor or liveness noise.

## Code

- `src/agent_discord/orchestration/ci_watch.py` — collector, card, dedupe,
  prompt, custom id
- `src/agent_discord/host/panel.py` — `_handle_fix_ci_click`
- `src/agent_discord/orchestration/listen.py` — `_tick_ci_watch_best_effort`
