# Discord OS — Wave 5 ranked implement haul (board + brain lakes)

**Audience:** Cary Palmer — approve without a meeting  
**Date:** 2026-09-16 (America/Chicago)  
**Baseline:** tip **0.5.72** Wave 4 close (`discord-os-tip`); product brief ≤0.5.73  
**Companion audit:** `/workspace/discord-os-wave5-arxiv-oss-audit.md`  
**Brand:** **board + brain lakes** — never "Graham thread" in ship copy  
**Policy:** HARD locks unchanged (CU/docker, mailbox, multi-host DO lakes, second JobPool, auto tags, multi-gateway, silent ssh cook — **parked**)

---

## Gap TLDR

| Thread / need | Today (≤0.5.72) | Wave 5 close | Honest limit |
|---|---|---|---|
| Board = shared blackboard (voluntary take) | Need/Live/Done; Catch-up ADR/PR conflicts; no claim verb | `claim` / typed Need take on existing JobPool task | Single-host; no CRDT multi-writer |
| Handoff is lake-aware but unstructured | meat-proxy preamble + metadata keys | **Typed handoff envelope** + `already_claimed` | JobPool-only; mailbox stays parked |
| Brain lake inject is blunt | `[brain-lake]` full-ish inject | **Compact recall pack** (budgeted, cited) | One Mac SQLite — not multi-host DO |
| Plans don't learn | `plan_approve` then discard | **Plan gallery** → brain journal / retrieve | No Magentic Docker UI |
| Ledger invisible on phone | Lineage in SQLite | **Progress ledger strip** on Live/Done cards | Thin supervisor — not AutoGen Studio |
| Coordination tax beyond ADR/PR | ADR/PR heuristics only | Write-key / path conflict hints on Catch-up | Heuristic, not semantic CRDT merge |
| Failed peer orphans | Cancel honesty local | **Compensation NOTE** on parent | Saga-lite honesty, not distributed ACID |
| Share kit brand | Wave 1–4 co-work docs | COMPARISON + demo: **board + brain lakes** | No fleet / Devin overclaim |

---

## Ranking rules applied

- Prefer **shareable** README/COMPARISON demos (Puppetmaster-grade).  
- Prefer **reuse** JobPool, Catch-up, brain lake, handoff — no new planes.  
- Cap **P0 to one PR band**.  
- Prefer single-host depth over fleet fantasy.

---

## P0 — one PR band (approve → ship)

### P0a — Typed handoff envelope + idempotent claim *(product depth)*

**Why:** Magentic ACP / Saga / file-HANDOVER literature all say free-text handoffs lose constraints and double-admit work. Wave 4 meat-proxy cut is prose; Wave 5 makes it a **schema on JobPool**.

**Acceptance criteria**
1. `handoff` / `peer` writes metadata envelope: `handoff_id`, `from`, `to`, `constraints?`, `expecting?`, `freshness`, `supersedes?`, `roe_hint`, `brain_dri?`.  
2. Re-dispatch of same `handoff_id` → spoken **already_claimed** / no second live cook.  
3. Receipt card shows envelope fields (clipped); preamble still includes `[meat-proxy-cut]` + brain block.  
4. Docs: `docs/co-work/handoff.md` + new `docs/co-work/wave5-handoff-envelope.md`.  
5. Tests: unit for envelope parse/claim; no second JobPool.

**Files likely touched**
- `src/agent_discord/orchestration/listen.py` (handoff/peer parse)
- `src/agent_discord/host/brain.py` (`format_meat_proxy_handoff_preamble` → envelope-aware)
- `src/agent_discord/orchestration/cards.py` / `receipts.py`
- `src/agent_discord/persistence/sqlite.py` (optional metadata column / JSON on task)
- `docs/co-work/handoff.md`
- `tests/test_wave5_handoff_envelope.py` (new)

**Test ideas**
- Same `handoff_id` twice → one live job.  
- Envelope fields round-trip on card metadata.  
- Non-operator peer still refused (`author_may_dispatch`).

---

### P0b — Board + brain lakes share strip *(shareability; same PR if small)*

**Why:** Puppetmaster-tier share is naming + one filmable loop. Wave 4 shipped features under "Graham" doc name; Wave 5 **rebrands the domain** in COMPARISON/README/co-work index.

**Acceptance criteria**
1. `docs/COMPARISON.md` + `docs/co-work/README.md` use **board + brain lakes**; no "Graham thread" in user-facing Wave 5 paths.  
2. `docs/co-work/wave5-board-brain-demo.md` — &lt;15 min loop: desk-pack → `add brain --dri` → dual ask → handoff envelope → Catch-up digest.  
3. `tests/test_public_copy.py` asserts brand phrase present / forbidden phrases absent (optional strict).  
4. Keep `wave4-graham-thread.md` as historical audit only (or rename note at top: historical).

**Files likely touched**
- `docs/COMPARISON.md`, `docs/co-work/README.md`, `README.md` (short band)
- `docs/co-work/wave5-board-brain-demo.md` (new)
- `tests/test_public_copy.py`

**Test ideas**
- Public copy grep for parked overclaims + brand.

**P0 cut recommendation:** Land **P0a + P0b** together if envelope is M-small; if envelope swells, ship **P0b docs-first** same day and P0a next commit in same band — still one approval.

---

## P1 — next product band

### P1a — Brain-lake compact recall pack (MemGPT-style)

**Acceptance:** `format_brain_prompt_block` gains budgeted pack: DRI label, top strategy filenames, last ≤5 journal notes, last ≤3 Done summaries with task ids; hard byte/token clip; HOST/`discord-os brain show` prints pack.  
**Files:** `host/brain.py`, `host/add.py`, `docs/co-work/brain-lake.md`, `tests/test_wave4_board_brain.py` or `test_wave5_brain_pack.py`.  
**Limit:** Single-host SQLite.

### P1b — Progress ledger strip on Job cards (Magentic-One)

**Acceptance:** Live/Done card footer lists ≤5 lineage facts (`plan_approved`, `gate_allowed`, `handoff_claimed`, `artifact_sha…`) from existing events — no new orchestrator.  
**Files:** `orchestration/cards.py`, `orchestration/lineage.py`, `docs/cards/README.md`, tests.  

### P1c — Plan gallery → brain journal (Magentic-UI plan learn)

**Acceptance:** On plan Allow, optionally `preferences`/`journal` row `kind=plan` keyed by channel+hash; next ask may inject `[plan-gallery]` hit. Opt-in flag OK.  
**Files:** `orchestration/plan_approve.py`, `host/brain.py`, `docs/cards/plan-approve.md`, `docs/co-work/wave5-plan-gallery.md`.  

### P1d — Board-catchup write-key / path conflicts (CodeCRDT lesson)

**Acceptance:** Conflicts section also groups jobs sharing `realm_write_key` / path-like tokens; still one briefing, no storm.  
**Files:** `orchestration/board_catchup.py`, `job_briefing.py`, `docs/co-work/board-catchup.md`, `tests/test_wave4_board_brain.py` extend.  

### P1e — Blackboard `claim <job_code>` verb (LbMAS volunteer)

**Acceptance:** Operator claims a Need → metadata `claimed_by` + lane; already_claimed if live; JobPool only.  
**Files:** `orchestration/listen.py`, `jobs.py`, cards, `docs/co-work/wave5-claim.md`.  

---

## P2 — stretch / park-adjacent

| ID | Item | Notes |
|---|---|---|
| P2a | Compensation NOTE on failed handoff peer (SagaLLM-lite) | Parent thread NOTE + lineage edge; not distributed saga |
| P2b | DRI role SOP label on `add brain` (MetaGPT) | `implementer\|reviewer\|planner` inject only |
| P2c | Cross-DRI relationship lines on HOST | When two brains' jobs share ADR/PR — extend lane lines |
| P2d | External mailbox / IRC peer protocol | **PARKED** — see `mailbox-park.md` |
| P2e | Multi-host brain lakes / DO | **PARKED** — overclaim |
| P2f | CU/docker Magentic sandboxes | **PARKED** |

---

## Intended `docs/co-work/wave5-*.md` sketches

### `wave5-board-brain-demo.md` (P0b)
1. `REQUIRE_OPERATORS=1`; Pair owner+operator.  
2. `discord-os add desk` / desk-pack bind.  
3. `discord-os add brain --dri alice --strategy-docs …`.  
4. Human A Ask; Human B steer same thread.  
5. `handoff @B: finish tests` — show envelope card.  
6. Flip HOST Off → On; show Catch-up Conflicts.  
7. Film &lt;15 min. Honest limit callout: single-host SQLite.

### `wave5-handoff-envelope.md` (P0a)
Schema table; already_claimed behavior; examples; link handoff.md; park mailbox.

### `wave5-plan-gallery.md` (P1c)
How Allow writes journal; retrieve rules; opt-in; not Magentic-UI clone.

### `wave5-claim.md` (P1e)
Blackboard volunteer claim; operators only; JobPool-only.

---

## Recommended approval (no meeting)

**Approve Wave 5 P0 band = P0a typed handoff envelope + P0b board+brain lakes share strip.**  

Defer P1a–P1e to the following band once P0 is green on tip.  
Do not open P2d–P2f.

---

## Out of scope reminder

No GitHub push from this research; no Mac `machineId`; no PyPI; research + `/workspace` docs only.
