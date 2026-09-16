# Discord OS — Wave 4 (board + brain lakes)

**Audience:** Cary Palmer  
**Date:** 2026-09-16 (America/Chicago)  
**Baseline tip:** 0.5.71 (`bc587e1`)  
**HARD policy:** CU/docker parked; SSH gates opt-in; voice local TTS only; REQUIRE_OPERATORS when sharing; spend honesty; forum tags manual never auto-create; no multi-gateway; no second JobPool; no silent local ssh cook; do **not** overclaim multi-host brain lakes / Durable Objects clones.

## Gap matrix (thread need → today → remaining gap → honest limit)

| # | Thread need | Discord OS today (≤0.5.71) | Remaining gap | Honest limit |
|---|---|---|---|---|
| 1 | Swim lanes / features with **technical relationships** | JobPool serialize per cwd; realm binds; forum tags-as-tickets; operator/lane on receipt cards | Jobs briefing does not surface *why* two live lanes relate (shared ADR/PR/cwd) | Single-host lanes; forum tags never auto-created |
| 2 | Per-DRI **brain** workspaces (repos + transcripts + strategy docs + journaling) | desk-pack = realm+memory(+wiki/github); think-tank; preferences; lineage NOTE | No first-class per-DRI brain bind / prompt inject for strategy docs + transcripts + journal | One Mac SQLite — not multi-host DO brain lakes |
| 3 | **Cut meat proxy**: lakes talk; escalate humans on ROE | handoff/peer JobPool; swarm; write/ask/plan gates | Handoff is thin text — does not carry lake context; ROE escalate wording soft | Agents do not auto-cross lakes; humans Pair + gates |
| 4 | Cron agents wake, **catch up on board state**, push work | schedules + Catch-up `skipped_while_disarmed` + overnight brief | Catch-up lists skipped prompts only — does not scan board for ADR/PR conflicts or push digest work | No Off→On job storm; digest is briefing/analyze-shaped |
| 5 | Reduce **coordination tax** (X conflicts with Y ADR) | github wake on bound PRs; analyze overlap serialize | No “X ↔ Y via ADR-N” surface on Catch-up / HOST | Heuristic text+PR-table scan, not a second ADR product |

## Ranked Wave 4 haul

### P0 — closes #1+#4+#5 (product depth)
- **P0a Board catch-up conflict digest** — Catch-up + `board catch-up:` / `digest:` schedules scan Need/Live jobs for shared ADR/PR refs; one briefing card; no storm.
- **P0b Swim-lane relationships** — HOST/Jobs briefing appends `↔` lines when jobs share ADR/PR/cwd.

### P1 — closes #2+#3 (swim-lane + meat-proxy)
- **P1a Brain lake bind** — `discord-os add brain --dri …` (+ desk-pack story); prompt inject strategy docs path + transcripts channel + journal notes.
- **P1b Meat-proxy cut on handoff** — handoff/peer prepends lake context + ROE escalate hint so lakes talk via JobPool cards, not human copy-paste.

### P2 — park-adjacent
- IRC-style always-on peer agents / mailbox protocol — **parked** (multi-gateway / second plane risk).
- Multi-host replicated brain lakes / DO clones — **parked** (overclaim).

## Already shipped (do not re-do)
Share kit, COMPARISON, shared-desk demo, recipes, overnight brief, handoff/peer JobPool, desk-pack, schedule list/every, Catch-up skipped_while_disarmed, operator/lane attribution, cross-host RO, forum-tags lock, screenshots 0.5.71.

---

## Ship status (2026-09-16 ~00:47 CT)

- **Version:** 0.5.72
- **Commit:** `4584b2b130c28f24b3ba219e7ccbe72aecb10bf6` on branch `haul/wave4-board-brain`
- **Bundle:** `/workspace/discord-os-0.5.72-wave4.bundle`
- **Patch:** `/workspace/discord-os-0.5.72-wave4.patch`
- **Tests:** `tests/test_wave4_board_brain.py` + co-work / Catch-up — green in box venv
- **Push/PR/PyPI:** blocked from this executor — no GitHub credentials; Shell `machineId` not exposed on subagent tool surface. Apply on Mac:

```bash
cd /Users/carypalmer/Projects/discord-os
git fetch /path/to/discord-os-0.5.72-wave4.bundle haul/wave4-board-brain:haul/wave4-board-brain
# or: git am /path/to/discord-os-0.5.72-wave4.patch
git checkout haul/wave4-board-brain
git push -u origin HEAD
gh pr create --title "Ship Discord OS 0.5.72 — Wave 4 board + brain lakes" --body "Board catch-up + brain lake + meat-proxy cut. See docs/co-work/wave4-board-brain.md"
# PyPI if TWINE/PYPI token in ~/.zshrc
```
