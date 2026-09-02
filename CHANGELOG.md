# Changelog

## 0.5.15

Approve write and Done stay in the job thread.

- Write-gate park edits the live thread card. It does not post Approve write in the parent channel.
- Approve resumes the same thread and the same card.
- HOST stays in the channel.

## 0.5.14

The job stays in the thread. The parent channel does not get a leftover line.

- No parent-channel TLDR. The channel stays the ask plus the thread starter.
- The live card keeps the start of the current beat so the thought chain stays readable.
- A stream phase change resets the token buffer. Done uses the start of the answer, not a mid-word tail.

## 0.5.13

The job thread is the cowork space. Done is a deliverable or a named failure.

- OpenRouter 401 no longer settles as OK plus "Worker finished without a written answer." The card speaks the dead key and the run is FAILED.
- FINDING lines keep the body. Scaffolding memories do not poison the next prompt.
- The live 3:21 AM 5thnode ask was this bug: provider died, Discord painted green.

## 0.5.12

Public copy names the host computer, not a harness UI.

- GitHub, PyPI, README, CLI `--help`, and feature docs lead with Discord as the screen and this Mac as SQLite + JobPool + Puppetmaster.
- Artifacts stay snowflake IDs plus sha256. Phone is the remote.

## 0.5.11

SQLite execution lineage. Retry parents a new run. Activities stay never.

- Each run records intake / dispatch / finding / diff / settle nodes. Done cites sha256. `discord-os lineage` dumps the DAG.
- Steer appends a lineage node. Retry queues `replay_of` at the previous tip. A dead process still fails closed; this is not Temporal.
- The live Components v2 card is the console. Discord Activities stay never.

## 0.5.10

Steer, claim-before-watermark, analyze-without-implement, cwd write lock, and REST-poll of live job threads.

- Live-thread follow-ups flush into the Cursor CLI worker (sidecar + stdin). Analyze omits `--implement --allow-dirty`.
- Claim inbound before advancing the listen watermark. Duplicate claims do not spawn a second job.
- Implement and swarm serialize on resolved realm cwd. The listen loop drains live job thread ids over REST. Gateway stays buttons-only.
- CLI cost/tokens survive the safe summary filter. The 3.11 job-pool timing assert is 2.5s, not 0.45s.

## 0.5.9

AWS names as Discord OS analogs, queryable from the host.

- `discord-os map` reads packaged JSON (`S3` is snowflake objects, not a CDN URL). Text and JSON both include world lifts.
- Ranks are shipped / now / next / never. World lifts (arxiv lineage, OpenHands durable handles, Restate approve-and-wait) sit in the same catalog.
- Docs: [docs/aws](docs/aws/README.md).

## 0.5.8

Live-thread follow-ups steer the running worker. Long Done answers split; the channel gets one TLDR line.

- A message in a live job thread calls `orchestrator.steer` instead of starting a sibling. Idle-thread follow-ups still start a new job.
- Long public Done answers settle as 2–3 thread messages at sentence boundaries. Short answers stay one message.
- Parent channel gets a one-line TLDR. Start and Done reactions land on the user message.
- Public card text drops mid-sentence scaffolding and repeated bodies.

## 0.5.7

README shots are the live HOST card plus a job thread, and two asks cooking.

## 0.5.6

PyPI listing leads with `pip install discord-os`. Doc links on the package page go to GitHub, not pypi.org paths.

## 0.5.5

Reply-first job threads, persist-then-settle, and host GitHub auth.

- New channel asks open a Discord thread on the user message and post the live card ("On it.") before the worker starts.
- Token flushes edit that one card. Meaningful beats settle as normal thread messages so history survives edits.
- In-thread follow-ups stay in the same thread (steer) and keep thread history.
- Worker monologue and host-reach / `gh auth login` dumps never reach Discord.
- `discord-os add github` writes `GH_TOKEN` into the host `.env`. Workers inherit host PATH + tokens.
- Unauthenticated `gh` paints a one-line how-to and Done. No worker essay.
- HOST card shows a github row (ok / sign-in). More includes GitHub.
