# Discord OS — Wave 6 ranked implement haul (board + brain lakes)

**Audience:** Cary Palmer — approve without a meeting  
**Date:** 2026-09-16 (America/Chicago)  
**Baseline:** tip **0.5.76** Wave 5 close (product brief); box tip still **0.5.72** — sync before code  
**Companion audit:** `/workspace/discord-os-wave6-audit.md`  
**Brand:** **board + brain lakes** — never Graham  
**Phone:** Discord-native only — **NO** Tailscale / ttyd / filebrowser companion strip  
**Policy:** HARD locks unchanged (CU/docker, mailbox/IRC, multi-host DO lakes, second JobPool, multi-gateway, auto tags, silent ssh cook, phone companion terminal/files — **parked**)

---

## Gap TLDR

| Thread / need | Today (≤0.5.76 Wave 5) | Wave 6 close | Honest limit |
|---|---|---|---|
| Spend glance on phone | Halt/cap/`format_spend`/Done Cost; cryptic digest | **HOST spend meter** + `/status` bar; unknown≠$0 | Honesty meter — not fleet hard-cap product |
| Dual-op steer friction | Steer inbox; settle operator/lane | **Live steer attribution** + quiet conflict NOTE | Single JobPool; no AMBIPOM editor |
| Need→Done story | Progress ledger strip (W5) | **Narrative ≤3 beats** on Done | Lineage reuse — not AgentBoard web |
| Doctor/status spam | Debounced digest; noisy WARNs | **Quiet ops**: material-change digest; FAIL-only notify | Discord-native; no companion strip |
| Overnight brief quality | Free-text schedule recipe | **Structured pack** inject (Needs/Live/parks/spend) | Catch-up honesty; no CRHQ mailbox |
| Share / COMPARISON depth | W5 board+brain demo | Goose / Cloud Agents / Spec Kit / Ledger foils + phone honesty | Single-Mac desk — not vendor VM fleet |
| Transcript cites | Compact recall pack (W5) | ARC-lite **citations** (DOS-*/sha/journal) | SQLite store; no recall-tool storm |
| Recipes | Markdown playbooks | Parameterized recipe docs polish | No Goose YAML runtime |
| Recovery UX | Compensation NOTE (W5 P2) | Human **recovery beat** after fail | Saga-lite; not ParaRecover harness |

**Do not re-propose as P0:** typed handoff envelope, already_claimed, W5 share strip, compact recall pack, progress ledger, plan gallery, write-key conflicts, claim, compensation NOTE, DRI --role, cross-DRI HOST lanes.

---

## Ranking rules applied

- Prefer **shareable** README/COMPARISON demos (Puppetmaster-grade).  
- Prefer **reuse** JobPool, HOST, Catch-up, brain lake, lineage, `format_spend`, `progress_bar` — no new planes.  
- Cap **P0 to one PR band**.  
- Prefer single-host depth over fleet fantasy.  
- Explicit HARD parks.

---

## P0 — one PR band (approve → ship)

### P0a — HOST phone spend meter + Halt honesty *(product depth)*

**Why:** INTENT / Green SARC / Ledger / SpendGuard all say cost must be **glanceable at the control surface**, not buried in post-hoc dashboards. Tip already records `cost_usd` and Halt — Wave 6 makes the **phone HOST** filmable. Policy lock 7: honesty-only, unknown ≠ $0, **not** hard-cap fleet marketing.

**Acceptance criteria**
1. HOST panel (and `/status` digest) shows session spend as ASCII meter via existing `progress_bar` when cap known; else `spent · cap none · known|unknown` — never invent `$0` for missing `cost_usd`.  
2. Halt state visible in same strip (`halted` badge); toggling Halt still works.  
3. Done/receipt Cost line remains; Live card may show job-level cost when usage known (clipped).  
4. Docs: `docs/co-work/wave6-spend-meter.md` + COMPARISON paragraph “spend honesty vs Ledger/SpendGuard (we meter, we don’t sell a firewall)”.  
5. Tests: `tests/test_wave6_spend_meter.py` — unknown path, cap path, halt path; reuse `test_spend_honesty.py` fixtures.  
6. **No** new JobPool; **no** companion HTML as product path.

**Files likely touched**
- `src/agent_discord/host/panel.py` (HOST spend strip)
- `src/agent_discord/host/status_digest.py` / `dashboard.py` (RO parity)
- `src/agent_discord/discord/layout.py` (`progress_bar` reuse)
- `src/agent_discord/orchestration/service.py` / `receipts.py` (display helpers only)
- `docs/COMPARISON.md`, `docs/co-work/wave6-spend-meter.md` (new)
- `tests/test_wave6_spend_meter.py` (new)

**Test ideas**
- Missing `cost_usd` → `unknown`, not `0.0000`.  
- Cap set → meter fills; Halt on → badge.  
- Digest signature includes spend bits without terminal-job churn.

---

### P0b — Wave 6 share / COMPARISON strip *(shareability; same PR if small)*

**Why:** Puppetmaster-tier share needs fresh foils beyond W5: Goose recipes, Cursor Cloud Agents (public), Spec Kit boards, Ledger spend — plus **phone Discord honesty** (no companion strip).

**Acceptance criteria**
1. `docs/COMPARISON.md` gains short rows/sections: Goose recipes, Cloud Agents (vendor VM vs your Mac), Spec Kit/Linear boards, Ledger spend firewall — brand **board + brain lakes**.  
2. `docs/co-work/wave6-board-brain-demo.md` — &lt;15 min loop extending W5: desk-pack → brain DRI → dual ask → handoff envelope → **spend meter glance** → Catch-up; explicit “Discord-native phone only — no Tailscale/ttyd/filebrowser.”  
3. `docs/recipes/README.md` indexes the demo.  
4. Optional: `tests/test_public_copy.py` asserts no companion-strip / Graham / fleet overclaim phrases.

**Files likely touched**
- `docs/COMPARISON.md`, `docs/co-work/README.md`, `docs/recipes/README.md`
- `docs/co-work/wave6-board-brain-demo.md` (new)
- `tests/test_public_copy.py`

**P0 cut recommendation:** Land **P0a + P0b** together (meter is M-small; docs ride along). If meter swells, ship P0b docs-first same day — still one approval band.

---

## P1 — next product band

### P1a — Dual-operator steer attribution + conflict NOTE (AMBIPOM / OrchVis)

**Acceptance:** Live card footer shows last steer `by:<operator_id> · <clip>`; if two distinct operators steer within window without claim ownership, one quiet NOTE (no storm). Lineage event `steer` already exists.  
**Files:** `orchestration/orchestrator.py` (`steer`), `orchestration/cards.py` / `reactive.py`, `docs/co-work/wave6-dual-steer.md`, tests.  
**Limit:** Single JobPool; no graph editor.

### P1b — Quiet doctor / status (Cary hates spam)

**Acceptance:** Status digest posts only on **material** signature change (spend/power/live jobs/Halt) — already partly true; tighten terminal exclusion + raise default interval OK. `doctor --notify` defaults to FAIL-only (WARN collapsed unless `--verbose`). Slash/voice WARN not channel-posted.  
**Files:** `host/status_digest.py`, `host/doctor.py`, `docs/host/doctor.md`, `tests/test_host_doctor.py` / digest tests.  
**Limit:** No companion strip productization.

### P1c — Overnight brief structured pack

**Acceptance:** Schedule prompts tagged `overnight brief:` / recipe helper inject structured context: open Needs (≤5), Live (≤5), gate parks, spend snapshot, Catch-up skipped count — then one JobPool ask. Off → still one Catch-up, no storm.  
**Files:** `orchestration/job_briefing.py` or schedule compose path, `docs/co-work/overnight-brief.md`, `docs/co-work/wave6-overnight-pack.md`, tests.  
**Limit:** No mailbox / CRHQ fleet.

### P1d — Need→Done narrative beats (AgentBoard lesson)

**Acceptance:** Done card appends ≤3 lineage beats (`plan_approved` → `gate_allowed` → `artifact_sha…`) as spoken story under progress ledger — not a second board.  
**Files:** `orchestration/cards.py`, `orchestration/lineage.py`, `docs/cards/README.md`, tests.  
**Limit:** Complements W5 ledger; don’t re-ship ledger as new P0.

### P1e — ARC-lite citations in brain / Done

**Acceptance:** Compact recall pack + Done narrative cite `DOS-*` / artifact sha8 / journal ids; HOST `brain show` lists cites; no agent `_recall` tool loop.  
**Files:** `host/brain.py`, receipts/cards, `docs/co-work/brain-lake.md`, tests.  
**Limit:** Single-host SQLite ObsStore.

---

## P2 — stretch / park-adjacent

| ID | Item | Notes |
|---|---|---|
| P2a | Human recovery beat after failed peer/Live (ParaRecover/ReflexGrad-lite) | Diagnostic + Retry/Dismiss; extends W5 compensation NOTE |
| P2b | Parameterized recipe docs (Goose-shaped inputs table) | Docs only — no YAML runtime |
| P2c | Spec Kit lifecycle labels as optional forum **manual** tags map | Never auto-create tags |
| P2d | OCL-shaped ROE escalate copy on Halt / gate Deny | Wording + receipt; no new control plane |
| P2e | Stall one-liner on Live after N steers w/o progress | Quiet; opt-in |
| P2f | External mailbox / IRC peer | **PARKED** |
| P2g | Multi-host DO brain lakes | **PARKED** |
| P2h | CU/docker / companion terminal-files | **PARKED** |

---

## Intended `docs/co-work/wave6-*.md` sketches

### `wave6-spend-meter.md` (P0a)
Schema: spent / cap / known / halted; ASCII meter rules; unknown≠$0; Halt semantics; COMPARISON vs Ledger/SpendGuard; park hard-cap fleet.

### `wave6-board-brain-demo.md` (P0b)
1. `REQUIRE_OPERATORS=1`; Pair×2.  
2. Desk-pack + `add brain --dri`.  
3. Dual ask/steer; show W5 envelope if handoff.  
4. **Point camera at HOST spend meter**.  
5. Off→On Catch-up.  
6. Callout: Discord phone only — no Tailscale/ttyd/filebrowser.  
7. Film &lt;15 min.

### `wave6-dual-steer.md` (P1a)
Attribution fields; conflict NOTE rules; operators only; JobPool-only.

### `wave6-overnight-pack.md` (P1c)
Structured inject keys; Catch-up honesty table; example schedule line.

---

## Recommended approval (no meeting)

**Approve Wave 6 P0 band = P0a HOST phone spend meter + Halt honesty + P0b Wave 6 COMPARISON/demo strip.**

Defer P1a–P1e until P0 green on tip (≥0.5.76).  
Do not open P2f–P2h.

---

## Out of scope reminder

No GitHub push from this research; no Mac `machineId`; no PyPI; research + `/workspace` docs only.
