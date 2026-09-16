# Discord OS — Wave 6 arXiv + OSS audit (board + brain lakes)

**Audience:** Cary Palmer  
**Date:** 2026-09-16 (America/Chicago)  
**Status:** Research audit only — **no implementation, no commit, no PyPI, no GitHub push, no Mac machineId touch.**  
**Baseline (product brief):** tip **0.5.76** board + brain lakes through **Wave 5 shipped**.  
**Box tip note:** `/workspace/discord-os-tip` still at **0.5.72** / `bdca6ed` (Wave 4 close) as of this audit — Wave 5 surfaces assumed shipped per brief; do **not** re-propose Wave 5 as P0.  
**Brand:** **board + brain lakes** only — never Graham / Marionette-era share claims.  
**Sister:** Puppetmaster = worker kernel. Discord = free shared board/IRC/IAM; one Mac host = computer.  
**Phone posture:** Discord-native mobile is enough — **NO** Tailscale / ttyd / filebrowser companion strip.

**HARD parks (never reverse):** CU/docker; mailbox/IRC peer plane; multi-host DO brain lakes; second JobPool; multi-gateway; auto forum tags; silent local ssh cook; phone companion terminal/files.

---

## Already shipped (Waves 1–5) — do NOT re-propose as P0

| Band | Shipped surface |
|---|---|
| Waves 1–3 | Share kit, recipes, overnight brief compose, screenshots, cross-host RO, forum-tags lock |
| Wave 4 | Board catch-up ADR/PR digest; swim-lane `↔`; `add brain --dri`; meat-proxy handoff |
| Wave 5 P0 | Typed handoff envelope + `already_claimed`; board + brain lakes share strip/demo |
| Wave 5 P1 | Compact recall pack; progress ledger strip; plan gallery; write-key conflicts; `claim` |
| Wave 5 P2 | Compensation NOTE; DRI `--role` SOP; cross-DRI HOST lanes |
| Validation | Live Discord mostly green; plan gallery live poke optional/skipped |

---

## A) Academic / arXiv findings (≥8 **new** vs Wave 5)

Wave 5 already mined Magentic-One/UI, LbMAS, ACP, CodeCRDT, SagaLLM, MemGPT, MetaGPT, OpenHands/CrewAI/LangGraph patterns. Wave 6 digs **HITL multi-operator**, **spend/cost governance**, **recovery**, **ROE escalation**, **transcript addressability**, **shared-room conflict**.

For each: **title · id · finding · Discord OS lift (or no-lift)**.

### 1. OrchVis — hierarchical multi-agent orchestration for human oversight — `2510.24937`
- **URL:** https://arxiv.org/abs/2510.24937  
- **Finding:** Hierarchical goal alignment + interactive planning panel; conflicts expand a two-layer viz (goals ↔ task workflows); only **affected branches** pause; users pick system-proposed repairs with predicted progress/risk/**cost**.  
- **Lift:** Dual-operator / Catch-up conflict UX — when two operators steer or ADR/PR conflicts fire, surface a **spoken conflict panel** (reuse Catch-up digest chrome) with ≤3 alternatives + cost hint from session spend — not a new canvas.  
- **No-lift:** Full OrchVis GUI planning studio / multi-agent fleet viz.

### 2. AMBIPOM / Human–LLM collaborative planning — `2605.23023`
- **URL:** https://arxiv.org/html/2605.23023v1  
- **Finding:** Taxonomy of steer types (semantic vs structural; global vs targeted; low vs high). Users prefer **hybrid**: targeted feedback + direct local edits; bottleneck is **verification/integration**, not authoring. Global feedback wins quality but humans avoid it.  
- **Lift:** Dual-operator **steer attribution** on Live cards + optional “global vs local” steer receipt line; reduce friction when operator B steers A’s job (who/when/clip).  
- **No-lift:** AMBIPOM plan editor UI / structural graph editor in Discord.

### 3. BoardroomAI — evolving decision graphs — `2608.13046`
- **URL:** https://arxiv.org/html/2608.13046v1  
- **Finding:** Typed decision DAG (evidence, claims, objections, alternatives, risks); human interventions compile to node/edge updates; **selective propagation** recomputes ~14.6% of nodes vs exhaustive.  
- **Lift:** Weak product — reinforces Wave 4/5 Catch-up + write-key as selective impact; COMPARISON foil for “decision graph desks.”  
- **No-lift:** Full decision-DAG runtime beside JobPool.

### 4. Decoupled HITL system for agentic workflows — `2604.23049`
- **URL:** https://arxiv.org/pdf/2604.23049v1  
- **Finding:** HITL as **independent system component** with four dimensions: intervention conditions, role resolution, interaction semantics, communication channel — protocol-level concern, not embedded app spaghetti.  
- **Lift:** Document Discord gates / Pair / ROE as the decoupled HITL plane; optional **role-resolved escalate** wording on gate cards (who can Allow). Already mostly true — polish receipts.  
- **No-lift:** Separate HITL microservice / second gateway.

### 5. Organizational Control Layer (OCL) — `2606.04306`
- **URL:** https://arxiv.org/abs/2606.04306  
- **Finding:** Governance at the **execution boundary**: intercept proposed actions → approve / revise / block / escalate against role+policy+economic constraints **before** env mutation. Unsafe executions 88%→0% with structured recovery.  
- **Lift:** Deepen gate/ROE **pre-tool** honesty + spend-aware Halt as economic constraint (already Halt exists); escalate path when policy soft-fails → spoken Need, not silent continue.  
- **No-lift:** AgenticPay-style multi-tenant OCL fleet; hard-cap product marketing (policy lock 7).

### 6. INTENT — budget-constrained agentic tool use — `2602.11541`
- **URL:** https://arxiv.org/pdf/2602.11541  
- **Finding:** Hard monetary budgets for tool-augmented agents; intention-aware hierarchical world model + risk-calibrated **expected cost** (geometric retry inflation). Soft penalties breach; architectural gates hold.  
- **Lift:** **Phone spend meter** on HOST + status digest: session spent / cap / Halt with ASCII bar (`progress_bar`); Done receipts already have Cost line — make HOST glance filmable. Retry-aware “unknown ≠ $0” stays.  
- **No-lift:** INTENT Monte-Carlo planner inside Puppetmaster; fleet FinOps dashboard as product.

### 7. Green SARC — predictive cost & carbon governance — `2606.15954`
- **URL:** https://arxiv.org/html/2606.15954  
- **Finding:** Four enforcement sites in the agent loop; “State Snowball” Θ(n²); soft Lagrangian penalties breach ~91%; architectural gates breach 0%; scope-cap + routing drive 47–55% savings.  
- **Lift:** Prefer **gate-at-admission** (Halt / max-live / analyze-vs-implement) over post-hoc digests; quiet status when spend signature unchanged. Carbon = no-lift.  
- **No-lift:** Carbon accounting product; multi-tenant SARC library dependency.

### 8. Irreversibility Budget — fleet risk admission — `2609.00275`
- **URL:** https://arxiv.org/abs/2609.00275  
- **Finding:** Per-principal cumulative residual value-at-risk across agents; deny marginal irreversible effects when aggregate would overdraw; local gates alone allow fleet overdraw.  
- **Lift:** Conceptual only for single-host — session Halt ≈ irreversibility soft budget for **this Mac**. COMPARISON: Discord OS is principal=desk, not fleet.  
- **No-lift:** Fleet irreversibility accounting / multi-tenant risk ledger.

### 9. ParaRecover — process-level recovery benchmark — `2609.12345`
- **URL:** https://arxiv.org/abs/2609.12345  
- **Finding:** 14 error types across planning/tool/args; SDE rubric (structural / diagnostic / evolutionary); SOTA still weak on multi-turn error propagation.  
- **Lift:** After failed Live → spoken **recovery beat** (diagnostic + next Allow/Retry/Dismiss) using lineage — extends Wave 5 compensation NOTE toward human-readable recovery, not a new pool.  
- **No-lift:** Full ParaRecover eval harness as product dependency.

### 10. ReflexGrad — progress-gated within-episode recovery — `2511.14584`
- **URL:** https://arxiv.org/html/2511.14584v3  
- **Finding:** Fast refine every k steps + slow causal replan when m consecutive low-progress scores fire; emits trigger / diagnostic / verified fix artifacts.  
- **Lift:** Optional stall signal on Live cards when lineage shows repeated steers without Done progress — **quiet** (one line), not spam.  
- **No-lift:** TextGrad dual-process inside Discord OS cook loop.

### 11. ARC — Addressable Recall Compaction — `2607.25066`
- **URL:** https://arxiv.org/abs/2607.25066 · https://ar5iv.labs.arxiv.org/html/2607.25066  
- **Finding:** Lossless compaction via append-only ID-addressable observation store + citation stubs (`§id`) in active view; on-demand `_recall`; Needle ~99.4% vs best lossy ~88%. Separates archive vs presentation.  
- **Lift:** Beyond Wave 5 compact recall pack — **cite** artifact sha / DOS-* / journal ids in brain inject + Done narrative so shared-desk humans can expand without re-pasting full transcripts. SQLite = ObsStore.  
- **No-lift:** Agent-driven `_recall` tool storm; unbounded catalog pages in Discord cards.

### 12. AgentRoom — CRDT shared workspace — `2608.23740`
- **URL:** https://arxiv.org/abs/2608.23740 · https://arxiv.org/pdf/2608.23740  
- **Finding:** Concurrent multi-agent coding via CRDT FS + MCP `room_claim` / `room_release` / broadcast; advisory path ownership.  
- **Lift:** Reinforces Wave 5 `claim` + write-key serialize; COMPARISON foil.  
- **No-lift:** Yjs/CRDT multi-writer same cwd (**HARD** serialize honesty).

### 13. Governed shared memory for multi-agent LLMs — `2606.24535` (supporting)
- **URL:** https://arxiv.org/html/2606.24535v1  
- **Finding:** Provenance, scope, contradiction supersession, conflict-governance for shared memory.  
- **Lift:** Brain-lake journal already scoped per DRI — optional contradiction NOTE when two DRIs write opposing prefs (quiet).  
- **No-lift:** Cross-host governed memory fabric.

### 14. AgentBoard (eval board) — `2401.13178` (supporting, NeurIPS’24)
- **URL:** https://arxiv.org/abs/2401.13178  
- **Finding:** Analytical eval with **progress rates**, subgoal sequences, trajectory boards — success rate alone hides partial progress.  
- **Lift:** **Need→Done narrative** on Done cards: ≤3 subgoal-ish lineage beats (plan → gate → artifact) — story, not another orchestrator. Complements Wave 5 progress ledger strip.  
- **No-lift:** AgentBoard web eval toolkit as product UI.

**Count:** 12 primary + 2 supporting (≥8 new academic satisfied). Intentionally skipped Magentic/LbMAS/ACP/CodeCRDT/Saga/MemGPT rehash.

---

## B) Open-source / products (≥8 **new angles** vs Wave 5)

Wave 5 table already covered OpenHands, Aider (shallow), Continue, Cline/Roo, Goose (shallow), Magentic, AutoGen Studio, CrewAI, LangGraph, smolagents, Discord bridges, file-HANDOVER, CRHQ. Wave 6 mines **recipes, spend firewalls, Spec Kit boards, Linear/PR agents, operator consoles, Cursor Cloud Agents public UX**.

| # | Offering | URL / locus | They do well | Discord OS gap vs tip (≤0.5.76 Wave 5) | Honest single-host limit |
|---|---|---|---|---|---|
| 1 | **Goose (AAIF)** recipes + subagents | https://github.com/aaif-goose/goose · https://goose-docs.ai/docs/tutorials/subagents/ | Portable YAML **recipes** + parallel role subagents; foundation governance | Recipes exist as docs playbooks — not parameterized/shareable YAML with inputs; COMPARISON thin on Goose | Compose recipes via JobPool schedules; **no** Goose runtime / second gateway |
| 2 | **Aider** team/git paper trail | https://github.com/Aider-AI/aider | Repo map + every change → git commit audit | Shared desk ≠ Aider; dual-op lacks “who steered” paper trail on cards | DOS owns board; Aider owns surgical CLI — complementary |
| 3 | **Continue.dev** | https://github.com/continuedev/continue | Conservative IDE assist; slash workflows | No Discord HOST; not phone board | IDE-resident ≠ phone Discord |
| 4 | **Cline** (+ Roo legacy) | https://github.com/cline/cline | Step-level GUI approval | Gates exist; dual-op escalate UX thinner than Cline’s click-through | Cards already = approval surface; no VS Code extension goal |
| 5 | **Mentat / Sweep** (category) | Mentat CI-agent platforms; Sweep hosted/stalled | Autopilot PR loops | DOS is shared desk not autopilot PR mill | Park Devin-like always-on teammates |
| 6 | **GitHub Spec Kit + Linear bridges** | https://github.com/github/spec-kit · e.g. ashbrener/spec-kit-linear-sync, julsgud/spec-kit-linear | Spec→plan→tasks→implement lifecycle mirrored to Linear boards | Need/Live/Done is the board — lifecycle **labels/narrative** thinner than Spec Kit phases | Keep Discord JobPool as SoT; no Linear dependency required |
| 7 | **Vanguard / agentic PR review** | https://github.com/SebaBoler/vanguard | Watch loop claim→run→PR→adversarial self-review; budget guardrails | No AFK PR mill; recovery/review after fail is thin | Optional recipe docs only; CU/docker parked |
| 8 | **Ledger (agent spend policy)** | https://github.com/yashy10/ledger | Slack Block Kit Approve/Deny on spend; SHA-256 audit; learned patterns | HOST Halt exists; **phone meter + filmable spend glance** weak vs Ledger cards | Honesty meter + Halt — **not** fleet spend-firewall product |
| 9 | **Agentic SpendGuard** | https://github.com/m24927605/agentic-spendguard | Pre-call reserve/capture ledger; refuse before provider hit | DOS records post-receipt `cost_usd`; Halt is soft | Keep honesty-only; no Stripe-style multi-tenant ledger |
| 10 | **Cursor Cloud Agents** (public UX) | https://cursor.com/docs/cloud-agent | Launch from Slack/Linear/GitHub/mobile; isolated VM; shared **view** of agent runs; not true multiplayer live memory | COMPARISON must say: DOS = Discord screen + **your** Mac; Cloud Agents = vendor VM teammates | Do not overclaim background fleet / always-on cloud desks |
| 11 | **Notion AI multiplayer** (pattern) | Notion product | Shared doc presence; comments as steer | Discord threads already = shared presence; dual-op steer attribution gap | No Notion clone |
| 12 | **Discord job-board bots** (GOSHA, Oxymoron, etc.) | e.g. Bogzx/gosha-jobs; Oxymoron job tracker | Emoji state machines, Kanban channels, dashboards | DOS JobPool+cards already deeper; they lack lineage/HOST/gates | COMPARISON: thin job trackers vs board+brain lakes |
| 13 | **Operator-console OSS** (Oxymoron-class) | garden writeups / Discord ops bots | Channel workflow as console | HOST panel ≈ console; spend/doctor noise vs “quiet ops” | Discord-native only — **no** companion terminal/files strip |

---

## C) Product gaps vs tip (Wave 6 lens)

Focus: shareability, phone honesty, spend, dual-op friction, Need→Done, doctor spam, overnight brief, recipes.

| Gap | Today (Wave 5 close / tip code) | Wave 6 opportunity | Park |
|---|---|---|---|
| **Spend meter glance** | `format_spend`, Halt, cap, status digest `spend x/y`, Done `Cost:` line; HOST panel has numbers | Filmable **ASCII meter** on HOST + `/status`; session% of cap; unknown≠$0 badge | Hard-cap fleet marketing; SpendGuard product |
| **Dual-operator steer friction** | Steer inbox works; operator/lane on settle; little “B steered A” mid-flight | Live card attribution + conflict NOTE if two operators steer opposing clips | AMBIPOM graph editor |
| **Need→Done narrative** | Progress ledger strip (W5); cards still beat-ish | Done card **story** ≤3 lineage beats (Need→plan/gate→artifact) | AgentBoard web toolkit |
| **Doctor / status spam** | Digest debounced 60s; doctor many WARNs; Cary hates spam | Quiet modes: digest only on **material** signature; doctor `--notify` FAIL-only default; collapse slash/voice WARN noise | Companion HTML push as product |
| **Overnight brief quality** | Recipe = free-text schedule prompt + Catch-up honesty | Structured inject: open Needs / Live / parks / spend snapshot into brief job context | CRHQ fleet / mailbox digest |
| **Shareability depth** | W5 board+brain demo | COMPARISON rows: Goose recipes, Cloud Agents, Spec Kit boards, Ledger spend; phone-only honesty callout | Tailscale/ttyd/filebrowser |
| **Recipe polish** | Markdown playbooks | Goose-like parameterized recipe docs (`inputs: channel, realm`) without new runtime | YAML recipe engine / CI Goose |
| **Transcript cites** | W5 compact recall pack | ARC-lite citations (DOS-*, sha, journal id) in inject + Done | Agent `_recall` tool storm |
| **ROE escalate** | Gates + Pair + meat-proxy ROE hint | OCL-shaped escalate wording when economic/Halt/policy trips | Multi-tenant OCL |

---

## Findings matrix (concept → today → Wave 6 → park)

| Concept | Today (≤0.5.76 Wave 5) | Wave 6 candidate | Park / why |
|---|---|---|---|
| Spend observability | Backend + cryptic digest | HOST phone meter + Halt glance | Fleet FinOps / hard-cap marketing |
| Multi-op HITL steer | Steer works; thin attribution | Steer attribution + conflict NOTE | OrchVis GUI |
| Need→Done story | Ledger strip | Narrative beats on Done | Eval web board |
| Quiet ops | Debounced digest; noisy doctor | FAIL-only notify; material-change digest | Companion terminal |
| Overnight brief | Free-text schedule | Structured Need/Live/spend pack | CRHQ mailbox |
| Addressable recall | Compact pack | Cite ids for expand | Full ARC agent tools |
| Recipes share | Markdown | Parameterized playbook polish | Goose runtime |
| Recovery | Compensation NOTE (W5 P2) | Human recovery beat after fail | ParaRecover harness |
| Cloud Agents foil | Thin COMPARISON | Honest single-Mac vs vendor VM | Claiming background fleet |

---

## Parked vs ship (explicit)

### Ship-shaped (single-host depth)
- HOST / `/status` **spend meter** + Halt honesty (reuse `format_spend` / `progress_bar`)
- Dual-operator **steer attribution** + quiet conflict NOTE
- **Need→Done narrative** on Done cards (lineage reuse)
- Doctor/status **quiet** (spam cut)
- Overnight brief **structured pack** (JobPool schedule + Catch-up)
- ARC-lite **citations** in brain/Done (beyond W5 pack)
- Wave 6 COMPARISON + demo (Goose / Cloud Agents / Spec Kit / Ledger foils; phone-native)
- Recipe parameterization polish (docs)

### Parked (HARD / overclaim)
- CU / docker / Magentic ComputerTerminal  
- Mailbox / IRC always-on peer plane  
- Multi-host DO brain lakes  
- Second JobPool / multi-gateway  
- Auto-create forum `available_tags`  
- Silent local ssh cook for `kind=ssh`  
- **Phone companion terminal / files** (Tailscale, ttyd, filebrowser) — Discord-native enough  
- CRDT multi-writer same cwd  
- Spend hard-cap **fleet** product / SpendGuard clone  
- Cursor Cloud Agents parity claims  

---

## Sources index (top links)

1. https://arxiv.org/abs/2510.24937 — OrchVis  
2. https://arxiv.org/pdf/2602.11541 — INTENT budget-constrained agents  
3. https://arxiv.org/abs/2606.04306 — Organizational Control Layer  
4. https://arxiv.org/abs/2607.25066 — ARC addressable recall compaction  
5. https://arxiv.org/abs/2609.00275 — Irreversibility Budget  
6. https://arxiv.org/html/2605.23023v1 — AMBIPOM collaborative planning  
7. https://arxiv.org/abs/2608.23740 — AgentRoom  
8. https://arxiv.org/html/2606.15954 — Green SARC  
9. https://github.com/aaif-goose/goose — Goose recipes / AAIF  
10. https://cursor.com/docs/cloud-agent — Cursor Cloud Agents (public)  
11. https://github.com/yashy10/ledger — Ledger spend HITL  
12. https://github.com/github/spec-kit — GitHub Spec Kit  

---

## Method notes / blockers

- **Version skew:** Brief says tip **0.5.76** Wave 5 shipped; box `/workspace/discord-os-tip` is still **0.5.72** Wave 4 (`bdca6ed`). Wave 6 haul assumes Wave 5 landed per brief — verify Mac tip before implement.  
- WebFetch timed out on some abs pages (`2606.04306`, `2608.23740`, `2609.00275`); IDs/abstracts confirmed via search + ar5iv for ARC.  
- Did **not** clone new GitHub repos; OSS compare from public docs/search.  
- No Mac / machineId / PyPI / push performed.  
- Live Discord validation of Wave 5 plan gallery poke was optional/skipped — not a Wave 6 blocker.
