# Capture-first intake

A thought is not a job. Default intake treats every armed channel sentence as a
task, which is right for a remote and wrong for a scratchpad: in one production
window 10 of 43 jobs were dismissed, and much of what was dismissed read like
"PM routing should prefer X" or "Freese FAQ still waits" — notes, not work.

Capture-first writes those to host memory instead of cooking them. One
reaction, no card, no job, no spend.

**OFF by default.** The live host keeps "a sentence is a task" until the
operator turns this on.

```bash
discord-os add capture --channel-id CHANNEL_ID   # one channel
DISCORD_OS_CAPTURE_FIRST=1                       # every channel
DISCORD_OS_CAPTURE_CHANNELS=ID,ID                # named channels
```

## What becomes a capture

A top-level channel message on a capture-first channel, when **all** of these
hold:

| Rule | Why |
|---|---|
| Under 140 characters | A long message is a brief, not a note. |
| No imperative verb at the start | `fix`, `ship`, `run`, `build`, `review`, … — the list lives in `IMPERATIVE_VERBS` in `orchestration/capture.py`, and a politeness or request wrapper (`please`, `can you`) is stripped before the check. |
| Not a repo-status question | `is_repo_status_ask` already answers those with a deterministic card, for free. |
| Not in a job thread | A reply in a job thread steers or cooks exactly as before. |
| Not a command | `/` and `!` prefixes, plus `bind`, `schedule`, `claim`, `handoff`, `connect`, `open`, `on` / `off`, memory and jishaku verbs. |

Everything else cooks, unchanged.

## Escape hatch

`do:` or `cook:` at the start always cooks, and the prefix is stripped from the
prompt. There is no "capture this" counterpart — a message that should have
cooked is one tap away on the weekly digest.

## What a capture does

1. `redaction.redact_text_markers` over the text.
2. One `memory_entries` row (`source=capture`) with the author, the channel, and
   the Discord message link as the citation.
3. One bookmark reaction on the message.

Nothing else. No card is posted and nothing is dispatched. Because the row is
ordinary host memory on that channel, the existing recall picks it up: a later
ask in the same channel carries the capture as context.

## Weekly digest

Once a week — `DISCORD_OS_CAPTURE_DIGEST_DAY` (default Monday) at the morning
hour (`DISCORD_OS_MORNING_AT`, default 07:30) — the HOST channel gets one card
listing the week's captures, each with a **Cook this** button. The button is the
shared Cook seam: operator-only, prompt stored in SQLite rather than the custom
id, and admitted through JobPool like a typed ask, so the write gate holds it
exactly as it holds any other cook.

Silent when the week had no captures. The weekly watermark is written whether
or not a card went out, so a quiet week stays quiet and a restart at the digest
hour does not post twice. At most five lines carry buttons (Discord's action-row
ceiling); the rest are counted and stay in memory.

## Code

- `src/agent_discord/orchestration/capture.py` — classifier, memory write, reaction
- `src/agent_discord/orchestration/capture_digest.py` — weekly card and watermark
- `src/agent_discord/orchestration/listen.py` — `_capture_decision` / `_absorb_capture` in the drain, digest tick beside the morning tick
- `src/agent_discord/host/add.py` — `add_capture`
- `tests/test_capture_first.py`, `tests/test_capture_digest.py`
