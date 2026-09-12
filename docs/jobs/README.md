# Jobs

Each ask is an OS thread **and** a Discord job thread. Channel-parent asks (typed message or HOST **Ask** modal) always bind a thread when `thread_id` is empty: start from the user message when present, otherwise post a channel starter then open the thread. That thread is the cowork space — Need/Jobs stay findable; cards and progress live there. Existing thread steers are untouched (no nested thread). If Discord thread create fails (including rate limit), the run fails closed with a spoken **Need** — no silent channel-only cook, no retry storm. The parent channel stays the ask plus the thread starter. HOST stays in the channel and briefs parked / failed / live jobs before last Done. A **failed** Need can be **Dismiss**ed (or Ack) from the job card / Jobs select — marks cancelled so it leaves Need ranking without Continue/Retry. Bulk hygiene: `discord-os jobs clear-needs --failed` (optional `--older-than`, `--channel-id`, `--dry-run`) and HOST More → **Clear failed Needs** (confirm) use the same dismiss semantics, then refresh the HOST Jobs panel. Dismiss and cancel settle refresh the HOST Jobs panel immediately (recover/repaint when the panel message id is missing; otherwise spoken Need once). Up to eight live jobs by default (`DISCORD_OS_MAX_LIVE`). SQLite holds the DAG. Puppetmaster is the worker. Same machine. Not a cloud VM. A follow-up in a **live** job thread steers that worker. A follow-up in an **idle** (Done) thread starts a new job in the same thread, parented at the prior tip — threads are live sessions, not one-shots.
Job action buttons mint restart-safe `dos:<verb>:<jobCode>:<nonce>` when a job code is known (legacy `discord-os:job:` still works). Settle/fail cards may attach a size-capped File for the last log/diff. Cards use Need / Live / Done Section chrome.

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

- `src/agent_discord/orchestration/orchestrator.py` — `_ensure_job_thread` always-bind on channel-parent asks
- `src/agent_discord/orchestration/jobs.py` — `JobPool`, `resolve_max_live`, `resolved_write_key`
- `src/agent_discord/orchestration/listen.py` — claim, submit, per-destination watermark; `listen_destinations`
- `src/agent_discord/persistence/sqlite.py` — session thread ids, parent channel, tip run, DOS-* mint
- `src/agent_discord/orchestration/github_wake.py` — PR/CI wake into the owning thread
- `src/agent_discord/orchestration/github_rules.py` — unbound GitHub events as job threads
- `src/agent_discord/orchestration/job_briefing.py` — Need / Waiting / Live / Last (failed → Need; dismissed/cancelled → Last)
- `src/agent_discord/host/panel.py` — `refresh_host_jobs_panel` after dismiss/cancel ranking flips
- `src/agent_discord/orchestration/lineage.py` — DAG nodes, stacked descendants
- `src/agent_discord/cli.py` — host / listen loop / lineage
- Tests: `tests/test_jobs.py`, `tests/test_bind_job_thread.py`, `tests/test_host_jobs_panel_refresh.py`, `tests/test_dismiss_failed_need.py`, `tests/test_clear_failed_needs.py`, `tests/test_e2e_host.py`, `tests/test_orchestration.py`, `tests/test_lineage.py`, `tests/test_github_wake.py`, `tests/test_github_rules.py`