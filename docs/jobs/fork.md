# Fork from a lineage step

A reply in a job thread can branch the work instead of continuing it:

```text
fork from 2: try it with the cache off
fork from a1b2c3d4: redo the diff without the rename
```

Discord OS opens a **sibling** thread in the parent channel and starts a new run
there whose lineage parent is that step, not the thread's tip. The original
thread keeps its own tip, so the two lines of work do not step on each other.
The first card in the new thread says what it forked from:
`Forked from step 2 of DOS-10001 (node abcdef12).`

## Picking the step

`N` is the number `discord-os lineage RUN_ID` prints in its first column. One to
three digits is read as a step number; anything longer is read as a node key
prefix, and a prefix that matches two nodes is refused rather than guessed. An
unknown step is a spoken **Need** naming how many steps the job has.

The run forked from is the thread's most recent run, the same one `lineage`
answers for.

## Who may fork

Minting a job is a dispatch, so forking is operator-only
(`author_may_dispatch`). A non-operator reply is absorbed and ignored, like any
other dispatch from an unpaired user.

## Not a steer and not a retry

| Reply | What happens |
|---|---|
| anything, live thread | steers the running worker |
| anything, idle thread | new run in the same thread, parented at the tip |
| `fork from N: …` | new run in a **new** thread, parented at step N |

A fork is checked before the live-thread steer, so it works whether the job is
still cooking or already Done.

## Code

- `src/agent_discord/orchestration/fork.py` — parse, resolve the node, metadata, card note
- `src/agent_discord/orchestration/listen.py` — `_absorb_fork` in the drain loop
- `src/agent_discord/orchestration/orchestrator.py` — `FORK_PARENT_META` replaces the thread tip as lineage parent
- `src/agent_discord/orchestration/lineage.py` — `node_at_step`, `node_by_key_prefix`, numbered `format_nodes`
- Tests: `tests/test_fork.py`
