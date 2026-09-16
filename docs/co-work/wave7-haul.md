# Discord OS — Wave 7 ranked implement haul (board + brain lakes)

**Audience:** Cary Palmer — approve without a meeting  
**Date:** 2026-09-16 (America/Chicago)  
**Baseline:** tip **0.5.79** Wave 6 fully closed + EoW validated (`discord-os-w6p2` @ `09e37c1`)  
**Companion audit:** `/workspace/discord-os-wave7-audit.md`  
**Brand:** **board + brain lakes** — never Graham  
**Phone:** Discord-native only — **NO** Tailscale / ttyd / filebrowser companion strip  
**Policy:** HARD locks unchanged (CU/docker, mailbox/IRC, multi-host DO lakes, second JobPool, multi-gateway, auto tags, silent ssh cook, phone companion terminal/files — **parked**)

**EoW validation (mandatory after ship):** tip version bump green + `pytest` green + **live Discord** poke (Pair / ask / gate or Halt path as touched). Do not call a band closed without all three.

---

## Gap TLDR

| Thread / need | Today (≤0.5.79 Wave 6) | Wave 7 close | Honest limit |
|---|---|---|---|
| Cold-start TTFP | Setup + Portal dance; demos assume warm desk | Timed first-Done checklist + HOST empty-state tip + Wave 7 filmable demo | No wizard; Discord-native only |
| Halt delight | Meter + `halted` badge + ROE Need | Soft-warn ≥80% + “next admit **not run**” + Resume clarity | Honesty meter — not fleet firewall |
| Need density (phone) | Long Jobs select labels; thin Need counts | Compact Jobs chrome + bucket counts | Still one HOST Jobs select — not second board |
| Gate ROE glance | Escalate copy on Halt/Deny | `who` / `why` one-liner on park card | Wording — not OCL fleet |
| Recipe find | Markdown `docs/recipes/` index | Discord-native recipes tip / spoken index | No Goose YAML runtime |
| COMPARISON | W6 Goose/Cloud/Spec/Ledger | W7 BAGEN/TokenOps, AgentTrails, Harness-MU, Agent-Harness, Goose skills | Single-Mac desk |
| Desk regression | Unit + e2e_host | Golden desk scenarios (FakeDiscord) | Local pytest — no SaaS eval |
| Pair #2 friction | Pair=owner; op via CLI/Roles role | Phone **Pair operator** Confirm | Single allowlist |
| Lineage find | Dump one run | `--search` across events/artifacts/DOS-*/sha | SQLite — not AgentTrails GUI |

**Do not re-propose as P0:** spend meter existence, dual-steer attribution, quiet doctor, overnight pack, Done Story, ARC cites, recovery beat, parameterized recipe *docs*, Spec Kit manual tags, ROE escalate *existence*, stall signal, handoff envelope, claim, plan gallery, progress ledger, compensation NOTE, DRI role, cross-DRI lanes.

---

## Ranking rules applied

- Prefer **shareable** README/COMPARISON demos (Puppetmaster-grade).  
- Prefer **reuse** JobPool, HOST, spend meter/Halt, gates, lineage, recipes docs, FakeDiscord — no new planes.  
- Cap **P0 to one PR band**.  
- Prefer single-host depth over fleet fantasy.  
- Explicit HARD parks.  
- **EoW (tip+pytest+live Discord) mandatory** after ship.

---

## P0 — one PR band (approve → ship)

### P0a — Cold-start TTFP + Wave 7 filmable demo *(shareability)*

**Why:** LLM-HAS survey + Terminal-Is-All-You-Need + onboarding UX bar all say the aha is **first successful task in the medium**, not “bot is installed.” Tip demos assume a warm desk; Wave 7 makes cold→first-Done **filmable under a stopwatch** without a wizard.

**Acceptance criteria**
1. `docs/co-work/wave7-ttfp-demo.md` — camera-beat script (&lt;15 min warm **or** &lt;25 min cold): Portal→bootstrap→setup→`REQUIRE_OPERATORS`→Pair×2→desk-pack→first Ask→Done; timestamps; what to point camera at (HOST empty-state tip → first Need → Done Story/cites). Explicit: Discord phone only — no Tailscale/ttyd/filebrowser.  
2. HOST empty-state / unpaired tip line when no jobs + not paired: one spoken/Section tip (“Pair → Ask → Done”) — no wizard.  
3. `docs/setup/README.md` gains a **TTFP stopwatch** subsection linking the demo (first Done = success metric).  
4. `docs/COMPARISON.md` Wave 7 shareability bar updated: TTFP + Halt soft-warn (if P0b lands same PR) + desk harness mention.  
5. Tests: `tests/test_public_copy.py` (or new) asserts brand + no companion-strip / Graham / fleet overclaim; optional assert demo doc exists.  
6. **No** new JobPool; **no** companion HTML.

**Files likely touched**
- `docs/co-work/wave7-ttfp-demo.md` (new)
- `docs/setup/README.md`, `docs/co-work/README.md`, `docs/recipes/README.md`
- `docs/COMPARISON.md`
- `src/agent_discord/host/panel.py` / `orchestration/cards.py` (empty-state tip only)
- `tests/test_public_copy.py`

**Test ideas**
- Unpaired empty HOST payload includes tip substring.  
- Public copy grep parks.

---

### P0b — Wave 7 COMPARISON freshness *(shareability; same PR if small)*

**Why:** W6 foils are already mined; share kit needs **new** foils from this audit.

**Acceptance criteria**
1. `docs/COMPARISON.md` gains short Wave 7 rows: **BAGEN/TokenOps Halt UX** (we soft-warn + Halt honesty, don’t sell firewall), **AgentTrails** (we search SQLite lineage, not a provenance GUI), **Harness-MU** (Pair allowlist hooks, not multi-tenant gatekeeper product), **Agent-Harness** (local desk goldens, not SaaS eval), **Goose skills catalog** (markdown recipes discoverable in Discord tip — not YAML runtime).  
2. Brand **board + brain lakes**; phone-native honesty callout retained.  
3. Optional: `docs/co-work/wave7-audit.md` pointer or leave audit on box only.

**Files:** `docs/COMPARISON.md`, maybe `docs/co-work/README.md`, `tests/test_public_copy.py`

**P0 cut recommendation:** Land **P0a + P0b** together (docs-heavy; empty-state tip is M-small). If tip code swells, ship P0b docs-first same day — still **one approval band**.

---

## P1 — next product band

### P1a — Halt soft-warn + next-admit-not-run + Resume clarity (BAGEN / TokenOps)

**Acceptance:** When cap known and spend ≥ soft threshold (default 80%, env `DISCORD_OS_SPEND_SOFT_PCT`), meter/digest shows amber-ish marker (ASCII e.g. `!` / `warn`) before Halt; on Halt (manual or cap), spoken/NOTE/ROE line includes **“next JobPool admit was not run”**; HOST Halt control / strip makes **clear Halt / Resume** obvious (reuse toggle; document in `wave6-spend-meter.md` → `wave7-halt-ux.md`). unknown ≠ $0 unchanged.  
**Files:** `orchestration/service.py` (`format_spend_meter`), `host/panel.py`, `host/status_digest.py`, `orchestration/roe_escalate.py`, docs, `tests/test_wave7_halt_ux.py`.  
**Limit:** Honesty-only; no fleet SpendGuard.

### P1b — Phone Pair operator (Harness-MU-lite friction cut)

**Acceptance:** After owner paired, HOST offers **Pair operator** (ephemeral Confirm) that `add_operator(user_id, role=operator)` for the tapping user (or modal user snowflake if required by Discord constraints); refuses non-owner; CLI `discord-os pair` remains. Dual-op demo no longer requires Mac CLI for op #2.  
**Files:** `host/panel.py`, `orchestration/service.py` / sqlite operators, `docs/co-work/wave7-pair-operator.md`, tests.  
**Limit:** Single allowlist; no multi-tenant Harness-MU.

### P1c — Need / Jobs compact density (phone)

**Acceptance:** Jobs select labels prefer `Need|Live|Done · DOS-xxxxx` (prose in description only); HOST Jobs Need line shows bucket counts `N:n L:n D:n` when dense; no second board.  
**Files:** `host/panel.py` (`_job_select_options`), cards/panel chrome, docs/cards, tests.  
**Limit:** Discord select 25-option ceiling unchanged.

### P1d — Gate ROE who/why glance (PAuth-lite)

**Acceptance:** Parked gate / write / Halt cards append one clipped line `ROE · who: operators · why: <klass|write|spend Halt>`; complements W6 escalate Need (don’t duplicate storms).  
**Files:** `ask_gate.py`, `roe_escalate.py`, cards, `docs/co-work/wave6-roe-escalate.md` or `wave7-roe-glance.md`, tests.  
**Limit:** Wording only.

### P1e — Recipe Discord discoverability

**Acceptance:** Spoken `recipes` / HOST More tip lists ≤10 playbook titles from a static index (mirrors `docs/recipes/README.md`); points to docs paths — **no** YAML engine.  
**Files:** small `host/recipes_index.py` or listen verb, `docs/recipes/README.md`, tests.  
**Limit:** Docs compose; Goose runtime parked.

### P1f — Lineage search CLI (AgentTrails-lite)

**Acceptance:** `discord-os lineage --search <needle>` queries events/artifacts/job codes/sha8/DOS-* ; prints ≤20 hits with run/job; existing dump path unchanged.  
**Files:** `orchestration/lineage.py`, `cli.py`, `persistence/sqlite.py` (query helper), docs, tests.  
**Limit:** Single-host SQLite; no provenance GUI.

---

## P2 — stretch / park-adjacent

| ID | Item | Notes |
|---|---|---|
| P2a | Desk scenario golden harness (`tests/desk_scenarios/`) | FakeDiscord: Pair→ask→gate→Done; Halt soft-warn; already_claimed; pytest markers |
| P2b | Wave 7 overnight / Catch-up film beat in demo only | Docs — no new pack format |
| P2c | Soft contradiction NOTE when two DRI journals oppose (ReTree-lite) | Quiet; opt-in |
| P2d | External mailbox / IRC peer | **PARKED** |
| P2e | Multi-host DO brain lakes | **PARKED** |
| P2f | CU/docker / companion terminal-files | **PARKED** |
| P2g | Goose YAML recipe runtime / second JobPool | **PARKED** |

---

## Intended `docs/co-work/wave7-*.md` sketches

### `wave7-ttfp-demo.md` (P0a)
1. Cold: Portal token + app id + channel (clock start).  
2. `pip install` → `bootstrap` → edit `.env` → `setup --channel-id`.  
3. Open invite → On → Pair owner → Pair operator (P1b when shipped; else CLI).  
4. Desk-pack bind → Ask “say hello in one sentence” → Done. **Stop clock = TTFP.**  
5. Optional share beats: spend meter / soft-warn, gate who/why, `lineage --search`, recipes tip.  
6. Callout: Discord phone only; board + brain lakes; single-host.

### `wave7-halt-ux.md` (P1a)
Soft threshold; meter markers; next-admit-not-run copy; Resume; vs TokenOps/BAGEN/Ledger; park fleet firewall.

### `wave7-pair-operator.md` (P1b)
Owner-only; Confirm chrome; CLI parity; REQUIRE_OPERATORS; park multi-tenant.

### `wave7-lineage-search.md` (P1f)
Needles; hit format; Q-style examples (PROV-AGENT-inspired); park AgentTrails GUI.

---

## Recommended approval (no meeting)

**Approve Wave 7 P0 band = P0a cold-start TTFP + filmable demo + empty-state tip + P0b Wave 7 COMPARISON freshness.**

Defer P1a–P1f until P0 green on tip (≥0.5.79 + Wave 7 bump).  
Do not open P2d–P2g.  
**After ship: EoW = tip + pytest + live Discord — mandatory.**

---

## Out of scope reminder

No GitHub push from this research; no Mac `machineId`; no PyPI; research + `/workspace` docs only.
