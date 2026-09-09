# Jobs

Each ask is an OS thread **and** a Discord thread on the user message. That thread is the cowork space: describe an outcome, step away, come back to a spoken deliverable or a named failure — never a green OK with no answer. The parent channel stays the ask plus the thread starter. Job cards and answers stay in the thread. HOST stays in the channel and briefs parked / failed / live jobs before last Done. Two cooks at once. SQLite holds the DAG. Puppetmaster is the worker. Same machine. Not a cloud VM. Follow-ups in that Discord thread stay there (steer) with thread history.

Analyze work overlaps. Implement and swarm writes serialize per resolved realm cwd so two channels do not fight one working tree.

Cap is 8 live jobs. The listen loop does not block at that cap.

## Listen path

`drain_inbound` claims the inbound message, submits, then advances the watermark. An inbound message in a live job thread calls `orchestrator.steer` (flush into the running worker) instead of submitting a sibling. The host loop REST-polls those thread ids too. Idle-thread follow-ups still start a new job in that thread. `--once` waits the pool. The host loop reaps finished receipts without blocking the next channel.

Each run writes a SQLite lineage DAG (`node_key = sha256(step, input, parents)`). Done cites artifact sha256. Retry starts a new run parented at the previous tip. Query: `discord-os lineage [RUN_ID|DOS-10001]`.

A job that opened a GitHub PR (or is bound as last pusher) gets check conclusions and human review comments in **that job thread**. HOST ranks a failing check as Need. In-flight checks are Waiting, which is not failed. Speakable ids are `DOS-` codes next to the Discord snowflake. A stacked PR whose base is another job's head is a child in that lineage DAG (`discord-os lineage DOS-10001` lists the child). Stored GitHub rules cook a stored prompt: `new` mints a job thread when no bind exists, `single` enqueues into the owning job (steer if live, otherwise a cook in that thread). Bound PRs still wake in place.

## Code

- `src/agent_discord/orchestration/jobs.py` — `JobPool`, `resolved_write_key`
- `src/agent_discord/orchestration/listen.py` — claim, submit, watermark; `listen_destinations`
- `src/agent_discord/orchestration/github_wake.py` — PR/CI wake into the owning thread
- `src/agent_discord/orchestration/github_rules.py` — unbound GitHub events as job threads
- `src/agent_discord/orchestration/job_briefing.py` — Need / Waiting / Live / Last
- `src/agent_discord/orchestration/lineage.py` — DAG nodes, stacked descendants
- `src/agent_discord/cli.py` — host / listen loop / lineage
- Tests: `tests/test_jobs.py`, `tests/test_e2e_host.py`, `tests/test_lineage.py`, `tests/test_github_wake.py`, `tests/test_github_rules.py`
