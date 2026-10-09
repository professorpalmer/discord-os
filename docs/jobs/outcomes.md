# Recorded outcomes

A reaction on a settled job card is the operator's verdict on that run. The host
reads those reactions and stores them, so "did this job actually help" becomes
queryable instead of living in someone's memory.

| Reaction | Label |
|---|---|
| thumbs up (`U+1F44D`) | `good` |
| shrug (`U+1F937`) | `partial` |
| thumbs down (`U+1F44E`) | `bad` |

## How it is read

REST, not the Gateway. The one Gateway this product opens exists so On/Off
buttons work ([lock 4](../host/policy.md)); a reaction event would need another
intent and another socket. Instead the listen loop asks Discord who reacted to
the Done cards of runs that settled in the last **7 days**, at most once every
**300 s** (`DISCORD_OS_OUTCOMES_INTERVAL_S`, floor 30). The next slot is stored
in SQLite, so a restart does not burst the reaction endpoint.

Cards are found by the `card_message_id` / `card_channel_id` the live card left
in task metadata. A run whose card id was never recorded has nothing to read.

## What counts

- One label per operator per run. Changing your reaction changes the label; polling again does not duplicate it.
- Non-operators are ignored. With no operators paired the desk stays single-user open ([lock 8](../host/policy.md)); once anyone is paired, only paired operators label.
- The bot's own reactions are ignored.

## Where it shows

- HOST card body: `Outcomes 7d: 5 good, 1 bad`. Absent when nothing is labeled.
- `discord-os lineage RUN_ID` prints an `outcomes:` line, and `--json` carries an `outcomes` array.
- `discord-os eval` replays labeled runs against them. See [eval](eval.md).

## Code

- `src/agent_discord/orchestration/outcomes.py` — emoji map, `collect_outcomes`, tally lines
- `src/agent_discord/discord/rest.py` — `list_message_reactions` (GET reactions)
- `src/agent_discord/orchestration/listen.py` — `_tick_outcomes_best_effort`, `_poll_due` throttle
- `src/agent_discord/persistence/sqlite.py` — `run_outcomes`, `list_settled_cards`, `outcome_tally`
- Tests: `tests/test_outcomes.py`
