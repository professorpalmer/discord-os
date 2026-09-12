# Jobs

Each ask is an OS thread **and** a Discord thread on the user message. That thread is the cowork space: describe an outcome, step away, come back to a spoken deliverable or a named failure — never a green OK with no answer. The parent channel stays the ask plus the thread starter. Job cards and answers stay in the thread. HOST stays in the channel and briefs parked / failed / live jobs before last Done. A **failed** Need can be **Dismiss**ed (or Ack) from the job card / Jobs select — marks cancelled so it leaves Need ranking without Continue/Retry. Up to eight live jobs by default (`DISCORD_OS_MAX_LIVE`). SQLite holds the DAG. Puppetmaster is the worker. Same machine. Not a cloud VM. A follow-up in a **live** job thread steers that worker. A follow-up in an **idle** (Done) thread starts a new job in the same thread, parented at the prior tip — threads are live sessions, not one-shots.

Analyze work overlaps. Implement and swarm writes serialize per resolved realm cwd so two channels do not fight one working tree.

The host associates before the worker thinks: named checkout from the prompt (else the channel bind), then `gh` on that cwd. The worker prompt leads with that association. GitHub status asks still answer from the host scan. Product asks use the scan as context and cook.

Default live ceiling is **8** (`DISCORD_OS_MAX_LIVE`). Raise it when the machine and OpenRouter budget can take it; do not pretend unbounded — OpenRouter RPM/TPM/spend, CPU/RAM, and Discord rate limits still bite. The listen loop does not block at that cap (extra asks wait for a slot).

## Listen path

`drain_inbound` claims the inbound message, submits, then advances the watermark. An inbound message in a live job thread calls `orchestrator.steer` (flush into the running worker) instead of submitting a sibling. If steer cannot take it, the text is stored in SQLite `inbound_queue` and applied later (retry steer while live, else a tip-parented follow-up in the same thread). Parent-channel asks are not stolen onto a random live cook. Default on; `DISCORD_OS_INBOUND_QUEUE=0` restores steer-or-spoken-miss. The live v2 card shows **Cancel** for a phone interrupt. Cancel must kill the local agentic or SSH remote cook (process group); if interrupt cannot be confirmed the phone hears **Cancel unconfirmed** and the run is not painted Cancelled.

The host loop REST-polls live thread ids and recent idle session threads (from SQLite) too. Idle-thread follow-ups start a new job in that thread, parented at the prior tip. Each session thread keeps its own listen watermark so parent-channel tips (HOST panel paints) cannot hide older unread thread messages. `--once` waits the pool. The host loop reaps finished receipts without blocking the next channel.

Parked write-gate and per-tool / AskUserQuestion gates auto-deny after `DISCORD_OS_APPROVAL_TIMEOUT_MINUTES` (default 20). A live tool-class hold blocks the worker until Allow / Deny / Always or that timeout (local agentic PreToolUse via gate-inject sitecustomize → `discord-os gate-hook`). Path A SSH: live Discord hold does not share the gate queue yet; write-gate on → Need + remote write Deny. See [ask-gate](../cards/ask-gate.md).

Each run writes a SQLite lineage DAG (`node_key = sha256(step, input, parents)`). Done cites artifact sha256. Retry starts a new run parented at the previous tip. Query: `discord-os lineage [RUN_ID|DOS-10001]`.

A job that opened a GitHub PR (or is bound as last pusher) gets check conclusions and human review comments in **that job thread**. HOST ranks a failing check as Need. In-flight checks are Waiting, which is not failed. Speakable ids are `DOS-` codes next to the Discord snowflake. A stacked PR whose base is another job's head is a child in that lineage DAG (`discord-os lineage DOS-10001` lists the child). Stored GitHub rules cook a stored prompt: `new` mints a job thread when no bind exists, `single` enqueues into the owning job (steer if live, otherwise a cook in that thread). Bound PRs still wake in place.

## Code

- `src/agent_discord/orchestration/jobs.py` — `JobPool`, `resolve_max_live`, `resolved_write_key`
- `src/agent_discord/orchestration/listen.py` — claim, submit, per-destination watermark; `listen_destinations`
- `src/agent_discord/persistence/sqlite.py` — session thread ids, parent channel, tip run, DOS-* mint
- `src/agent_discord/orchestration/github_wake.py` — PR/CI wake into the owning thread
- `src/agent_discord/orchestration/github_rules.py` — unbound GitHub events as job threads
- `src/agent_discord/orchestration/job_briefing.py` — Need / Waiting / Live / Last (failed → Need; dismissed/cancelled → Last)
- `src/agent_discord/orchestration/lineage.py` — DAG nodes, stacked descendants
- `src/agent_discord/cli.py` — host / listen loop / lineage
- Tests: `tests/test_jobs.py`, `tests/test_e2e_host.py`, `tests/test_orchestration.py`, `tests/test_lineage.py`, `tests/test_github_wake.py`, `tests/test_github_rules.py`
