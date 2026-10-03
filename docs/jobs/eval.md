# `discord-os eval`

Replay the runs an operator labeled ([outcomes](outcomes.md)) and see whether
the current pin still answers them. Read-only: every replay is an ANALYZE ask,
never an implement, whatever the original text asked for.

```text
discord-os eval                          # plan only: what it would replay
discord-os eval --limit 10 --yes         # replay 10, print win/loss/same
discord-os eval --limit 10 --yes --json  # same, as the JSON report
discord-os eval --limit 10 --yes --out artifacts/eval.json
discord-os eval --limit 10 --yes --pin openrouter/auto
```

## Spend gate

Eval spends OpenRouter money — one analyze ask per labeled run. Without both
`--limit N` and `--yes` it prints the plan and the count it would replay, then
exits 0. Nothing is dispatched.

## Rubric

No LLM judge; none is wired in this product, and inventing one would make the
number unfalsifiable. A replay **passes** when it settles `completed`, its
summary is at least 40 characters, and the summary carries no failure marker
(`need:`, `could not`, `cannot`, `failed`, `no answer`). The label is the
baseline.

| Labeled | Replay passes | Replay fails |
|---|---|---|
| good | same | loss |
| bad | win | same |
| partial | win | loss |

## Pin

`--pin` is exact-allowlist, like every other model pin in this product. A pin
outside the allowlist is refused with the allowed values and exit 2 — there is
no silent fallback to the default.

## Isolation

Replays carry `eval=True` metadata. The orchestrator forces ANALYZE on them and
the JobPool does not take a realm write lock for them. The command builds its
orchestrator with no Discord facade and progress posting off, so an eval cannot
land a card in a channel or react to a message. Replays go one at a time through
JobPool.

## Report

```json
{
  "pin": "openrouter/auto",
  "rubric": "...",
  "replayed": 2,
  "totals": {"win": 1, "loss": 0, "same": 1},
  "results": [
    {
      "run_id": "...", "job_code": "DOS-10001", "label": "bad",
      "replay_run_id": "...", "replay_status": "completed",
      "replay_summary_chars": 184, "replay_passed": true,
      "verdict": "win", "error": null
    }
  ]
}
```

## Code

- `src/agent_discord/orchestration/evaluate.py` — rubric, plan, verdicts, `run_eval`
- `src/agent_discord/cli.py` — `cmd_eval`, the `--limit` / `--yes` gate
- `src/agent_discord/orchestration/orchestrator.py` — eval metadata forces ANALYZE
- `src/agent_discord/persistence/sqlite.py` — `list_labeled_runs`
- Tests: `tests/test_eval.py`
