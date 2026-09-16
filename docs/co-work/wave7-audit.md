# Discord OS — Wave 7 arXiv + OSS audit (board + brain lakes)

**Audience:** Cary Palmer  
**Date:** 2026-09-16 (America/Chicago)  
**Status:** Research audit only — **no implementation, no commit, no PyPI, no GitHub push, no Mac machineId touch.**  
**Baseline:** tip **0.5.79** Wave 6 fully closed + EoW validated (product brief). Box tree: `/workspace/discord-os-w6p2` @ `09e37c1` / `0.5.79`. (`/workspace/discord-os-tip` still **0.5.72** — use **w6p2** as tip for Wave 7.)  
**Brand:** **board + brain lakes** only — never Graham / Marionette-era share claims.  
**Sister:** Puppetmaster = worker kernel. Discord = free shared board/IRC/IAM; one Mac host = computer.  
**Phone posture:** Discord-native mobile is enough — **NO** Tailscale / ttyd / filebrowser companion strip.

**HARD parks (never reverse):** CU/docker; mailbox/IRC peer plane; multi-host DO brain lakes; second JobPool; multi-gateway; auto forum tags; silent local ssh cook; phone companion terminal/files.

---

## Already shipped (Waves 1–6) — do NOT re-propose as P0

| Band | Shipped surface |
|---|---|
| Waves 1–3 | Share kit, recipes index, overnight brief, screenshots, cross-host RO, forum-tags lock |
| Wave 4 | Board catch-up ADR/PR digest; swim-lane `↔`; `add brain --dri`; meat-proxy handoff |
| Wave 5 | Typed handoff envelope/`already_claimed`; share strip; compact recall; progress ledger; plan gallery; write-key conflicts; `claim`; compensation NOTE; DRI `--role`; cross-DRI HOST lanes |
| Wave 6 P0 | HOST phone spend meter + Halt honesty; COMPARISON Goose/Cloud Agents/Spec Kit/Ledger + `wave6-board-brain-demo` |
| Wave 6 P1 | Dual-steer attribution + conflict NOTE; quiet doctor/status; overnight structured pack; Need→Done Story beats; ARC-lite cites |
| Wave 6 P2 | Recovery beat; parameterized recipe docs; Spec Kit manual tags map; ROE escalate copy; stall one-liner |
| Validation | EoW = tip + pytest + live Discord — **mandatory after every Wave 7 ship** |

---

## Lens (Wave 7 — past W5–W6)

Shareability + **operator delight** on tip: onboarding **TTFP**, demo **filmability**, spend **Halt UX polish**, Need board **density on phone**, gate **ROE clarity**, recipe **discoverability**, **COMPARISON freshness**, Discord-desk **eval/regression harness**, operator **Pair friction**, **lineage search**.

Intentionally **not** rehashing W6: INTENT/Green SARC meter productization, dual-steer attribution, quiet doctor, overnight pack, Done Story, ARC cites, recovery beat, Spec Kit tags, ROE escalate *existence*, stall signal.

---

## A) Academic / arXiv findings (≥8 **new** vs Wave 5–6)

Wave 5–6 already mined Magentic/LbMAS/ACP/CodeCRDT/Saga/MemGPT/MetaGPT, OrchVis, AMBIPOM, BoardroomAI, Decoupled HITL, OCL, INTENT, Green SARC, Irreversibility Budget, ParaRecover, ReflexGrad, ARC, AgentRoom, AgentBoard. Wave 7 mines **TTFP/onboarding collaboration metrics**, **budget-aware early alert (post-meter)**, **multi-user Pair governance**, **provenance search**, **terminal/ACI design for filmable desks**, **task-scoped auth**.

For each: **title · id · finding · Discord OS lift (or no-lift)**. Note **overlap** when adjacent to W6.

### 1. LLM-Based Human-Agent Collaboration and Interaction Systems (survey) — `2505.00753`
- **URL:** https://arxiv.org/abs/2505.00753 · https://arxiv.org/html/2505.00753v5  
- **Finding:** LLM-HAS survey; calls out **inadequate eval** that ignores human workload — time spent giving feedback, mental effort across **initial setup → post-execution review**. Success-rate-only benches hide coordination cost.  
- **Lift:** Define Discord-desk **TTFP** = cold bootstrap → first Done (or first Allow→Done) under a stopwatch; add a tiny **desk scenario harness** measuring human taps + wall-clock, not just agent accuracy.  
- **No-lift:** Full academic HAS taxonomy product.  
- **Overlap:** Complements AgentBoard (`2401.13178`, W6 supporting) — new angle is **human-phase metrics / onboarding**, not Need→Done narrative (already shipped).

### 2. Terminal Is All You Need — design properties for Human–AI–UI — `2603.10664`
- **URL:** https://arxiv.org/abs/2603.10664 · https://arxiv.org/html/2603.10664v1  
- **Finding:** Effective agent tools converge on three properties: representational compatibility, **transparency of actions in the medium**, low barrier for humans to enter. Terminal is exemplar; any modality (incl. Discord cards) must engineer the same.  
- **Lift:** Demo filmability = make the **phone Discord medium** the transparent log (HOST strip + gate Allow/Deny + lineage ids visible without leaving Discord). Tighten Wave 7 demo script to camera beats that prove those three properties.  
- **No-lift:** Companion terminal/ttyd product (**HARD park**). Reinforces Discord-native-only.

### 3. BAGEN — Are LLM Agents Budget-Aware? — `2606.00198`
- **URL:** https://arxiv.org/abs/2606.00198 · https://arxiv.org/html/2606.00198 · https://ragen-ai.github.io/bagen/  
- **Finding:** Budget as **active control**: progressive remaining-budget intervals + **alert when completion unlikely**. Agents over-optimistic; early-stop saves 28–64% tokens on failed trajectories.  
- **Lift:** Beyond W6 meter — **Halt UX polish**: soft-warn before cliff (e.g. ≥80% of cap), Halt spoken banner that **next JobPool admit was not run**, clear Resume/clear-Halt path on phone HOST. Honesty-only; unknown ≠ $0.  
- **No-lift:** SFT/RL budget estimators inside Puppetmaster; fleet FinOps.  
- **Overlap:** INTENT (`2602.11541`) + Green SARC (`2606.15954`) mined in W6 for **meter existence**; BAGEN is the **alert / soft-warn / early-stop UX** delta.

### 4. Harness-MU — multi-user LLM agent harness — `2606.21856`
- **URL:** https://arxiv.org/abs/2606.21856 · https://arxiv.org/html/2606.21856v1 · https://github.com/YuanJrShiuan/Harness-MulUser  
- **Finding:** Multi-principal governance must be **deterministic runtime hooks** (Gatekeeper/Mediator), not prompt hope. Who is authorized / whose instructions win — infrastructure, not model.  
- **Lift:** Operator **Pair friction**: today Pair seeds **owner** only; second operator is CLI `discord-os pair` or Roles **role** modal (snowflake). Wave 7: phone path to Pair **operator** (user snowflake) with same ephemeral Confirm chrome — still single allowlist, no multi-tenant Harness-MU clone.  
- **No-lift:** Muses-Bench adversarial multi-tenant fabric; second gateway.

### 5. PAuth — task-scoped authorization via NL slices — `2603.17170`
- **URL:** https://arxiv.org/html/2603.17170v1 · https://arxiv.org/html/2603.17170v2  
- **Finding:** Broad OAuth/operator grants → high residual risk + HITL fatigue; **task-scoped** signed slices cut friction while keeping consent.  
- **Lift:** Gate **ROE clarity** polish — gate card states **who can Allow** (paired operators) + **why parked** (tool class / write / spend Halt) in one glance line; complements W6 ROE escalate copy.  
- **No-lift:** Cryptographic task envelopes / AgenticPay.

### 6. AgentTrails — trust and reuse for agentic trajectories — `2607.18816`
- **URL:** https://arxiv.org/abs/2607.18816 · https://arxiv.org/html/2607.18816  
- **Finding:** Chronological logs hide dataflow; convert trajectories → provenance graphs; **search/align** across runs for debug + reuse.  
- **Lift:** `discord-os lineage` today dumps **one** run by id/job code. Wave 7: **lineage search** — keyword / `DOS-*` / sha8 / event-type filter over SQLite events+artifacts (CLI + optional HOST NOTE), reuse existing store.  
- **No-lift:** Joined multi-run canvas GUI / AgentTrails product dependency.  
- **Overlap:** ARC (`2607.25066`, W6) = cite stubs in cards; AgentTrails = **search/query** across the DAG.

### 7. PROV-AGENT — unified provenance for agent workflows — `2508.02866`
- **URL:** https://arxiv.org/abs/2508.02866 · https://arxiv.org/html/2508.02866v1 · Flowcept: https://github.com/ORNL/flowcept  
- **Finding:** W3C-PROV + MCP-shaped records; queryable Q1–Q5 (decision→input lineage, prompt/response on surprise, forward impact).  
- **Lift:** Shape lineage-search answers as short Q-style lines (`who steered`, `which gate`, `artifact sha`) — docs + CLI `--ask`-ish filters, not Flowcept dependency.  
- **No-lift:** MCP provenance sidecar service.

### 8. SearchAtlas — evidential query graphs for search agents — `2609.10901`
- **URL:** https://arxiv.org/abs/2609.10901  
- **Finding:** Process graphs beat raw trajectories for diagnosing **fragmented support** / unconstrained claims; process failures correlate with wrong answers.  
- **Lift:** Weak product — COMPARISON foil: Discord OS lineage+cites ≈ process honesty without claiming search-agent graphs. Optional: Done Story already ships beats — don’t rebuild.  
- **No-lift:** Evidential query-graph runtime.

### 9. ReTree — tree-structured memory for long-horizon search — `2608.10676`
- **URL:** https://arxiv.org/abs/2608.10676  
- **Finding:** Bounded per-step context + source-linked evidence + revise/prune on contradiction.  
- **Lift:** Reinforces brain-lake compact pack + cites; optional quiet contradiction NOTE already floated W6 — stay P2.  
- **No-lift:** ReTree memory engine inside Discord OS.

### 10. Supporting UX industry (non-arXiv, cited for TTFP bar)
- **Zylos / agent onboarding first 5 minutes (2026):** activation = first successful task; guided first task > blank canvas; progressive autonomy.  
  https://zylos.ai/research/2026-03-29-ai-agent-onboarding-ux-first-five-minutes/  
- **Lift:** Cold-start recipe that reaches **first Done** without a 20-prompt wizard (product already refuses wizards — keep that; add timed checklist + HOST empty-state tip).

**Count:** 9 primary academic + 1 UX supporting (≥8 new satisfied). Explicitly skipped INTENT/Green SARC/OCL/OrchVis/AMBIPOM/ARC rehash except where noted as overlap.

---

## B) Open-source / products (≥8 **new angles** vs Wave 5–6)

Wave 5–6 covered OpenHands, Aider, Continue, Cline/Roo, Goose recipes (shallow→W6 docs), Magentic, AutoGen Studio, CrewAI, LangGraph, Spec Kit, Ledger, SpendGuard, Cursor Cloud Agents, Discord job-board bots. Wave 7 mines **Halt soft UX**, **skills/recipe catalogs**, **eval harnesses**, **token governance polish**, **Pair/multi-user**, **Components V2 density**.

| # | Offering | URL / locus | They do well | Discord OS gap vs tip **0.5.79** | Honest single-host limit |
|---|---|---|---|---|---|
| 1 | **TokenOps** run-aware ledger | https://github.com/theagentplane/tokenops | In-path HALT/MUTATE; shared run ledger; dashboard film | Meter+Halt exist; missing soft-threshold warn + explicit “next step not run” Halt banner + phone Resume clarity | Honesty Halt — not TokenOps control plane |
| 2 | **pi-usage-dashboard** | https://github.com/Jaraxxxx/pi-usage-dashboard | Live footer gauge; amber→red; `/budget` | HOST strip is filmable but no amber soft-warn tier | Keep ASCII `progress_bar`; no HTML footer companion |
| 3 | **fork-open-agents budget issue UX** | https://github.com/dennisonbertram/fork-open-agents/issues/108 | Soft 80% warn; hard stop; “Raise budget / Continue” | Halt toggles silently; ROE escalate speaks Need but card doesn’t teach Resume | Copy patterns only |
| 4 | **Goose skills + recursive discovery** | https://goose-docs.ai/docs/guides/context-engineering/using-skills/ · AAIF goose PRs · https://github.com/gooseworks-ai/goose-skills | Nested SKILL.md catalog; searchable install | Recipes = markdown index only; **no Discord-native discover** (`recipes` browse / HOST tip) | Docs + optional ephemeral list — **no** Goose YAML runtime |
| 5 | **Agent-Harness** (pytest trace asserts) | https://github.com/Suirotciv/Agent-Harness | Trace assertions: tool order, approval gates, cost_under | tip has rich unit tests + `test_e2e_host` — **no** versioned desk golden scenarios / regression pack | pytest-local harness; no SaaS eval platform |
| 6 | **EvalView / TrustBench pattern** | https://github.com/hidai25/evalview-support-automation-template · https://github.com/Umarfarook1/trustbench | Golden baselines; catch TOOLS_CHANGED / policy slice regressions | No committed Discord-desk scenario baselines (Pair→ask→gate→Done) | Local golden JSON fixtures |
| 7 | **SupportDesk OpenEnv** | https://github.com/Mayank29903/Damnenv | Deterministic `/reset` `/step` support env | Inspires **FakeDiscord** scenario runner for desk regression | Not a Discord product |
| 8 | **Harness-MU OSS** | https://github.com/YuanJrShiuan/Harness-MulUser | Runtime Gatekeeper for multi-user | Pair second-op friction (see academic #4) | Single-desk allowlist only |
| 9 | **OpenClaw-style pairing docs** | e.g. pairing allowlist patterns in agent desk docs | Device/sender Pair as first-class | Dual-op demo still CLI-heavy for operator #2 | Keep REQUIRE_OPERATORS; ease phone Pair |
| 10 | **Discord Components V2 kits** | https://docs.discord.com/developers/components/reference · SoulDevs/components-v2 · demondevx/discord-container-kit | Section/Container density; ≤40 comps; phone stacks | Jobs select labels long (`Need · DOS-… · prose`); Need chrome can feel sparse/noisy on phone | Compact label mode + denser HOST Jobs chrome — still V2, no Activities |
| 11 | **BAGEN code/bench** | https://github.com/mll-lab-nu/BAGEN | Early-stop alert eval | Foil for Halt soft-warn acceptance tests | No BAGEN dependency |
| 12 | **Flowcept / PROV-AGENT** | https://github.com/ORNL/flowcept | Queryable agent provenance | Lineage search gap (academic #6–7) | SQLite only |

---

## C) Product gaps vs tip (Wave 7 lens)

| Gap | Today (0.5.79 Wave 6 close) | Wave 7 opportunity | Park |
|---|---|---|---|
| **Onboarding TTFP** | `setup` + Developer Portal; demos assume warm desk; no stopwatch to first Done | Cold-start checklist + HOST empty-state tip + timed `<N min` first-Done path in Wave 7 demo | 20-prompt wizard; companion onboarding app |
| **Demo filmability** | `wave6-board-brain-demo.md` ~20 lines; spend meter glance | Camera-beat script (timestamps, what to point at: Pair, HOST meter/Halt soft-warn, gate Allow who, lineage cite, recipe tip) | Tailscale/ttyd filming companion |
| **Halt UX polish** | Meter + `· halted` badge + ROE escalate Need; CLI `--halt`/`--resume` | Soft-warn ≥80% cap; Halt banner “next admit **not run**”; phone clear-Halt / Resume affordance visible | Fleet hard-cap / SpendGuard product |
| **Need board density (phone)** | Jobs select `bucket · code · label` ≤80 chars; Section Need/Live/Done | Compact density: shorter select labels; denser HOST Jobs Need line (counts by bucket); optional clip prose | Second Kanban board / Activities |
| **Gate ROE clarity** | Allow/Deny/Always + W6 ROE escalate wording | One-glance `who: operators · why: <klass|write|halt>` on gate/park card | Multi-tenant OCL |
| **Recipe discoverability** | `docs/recipes/README.md` + parameterized.md | Discord-native `recipes` / HOST More tip listing playbook titles → jump or spoken index | Goose runtime / CRHQ skills clone |
| **COMPARISON freshness** | Wave 6 foils (Goose/Cloud Agents/Spec Kit/Ledger) | Wave 7 rows: BAGEN/TokenOps Halt UX, AgentTrails lineage search, Harness-MU Pair, Agent-Harness desk eval, Goose **skills catalog** | Claiming fleet / CU |
| **Desk eval harness** | Unit + e2e_host; no golden desk scenarios | `tests/desk_scenarios/` golden: Pair→ask→gate→Done; spend Halt soft-warn; already_claimed — pytest, FakeDiscord | SaaS eval platform; live Discord in CI |
| **Operator Pair friction** | Pair = seed owner; op #2 = CLI `pair` or Roles **role** snowflake | Ephemeral **Pair operator** (user id) Confirm path on HOST | Multi-gateway ACL; hostile multi-tenant |
| **Lineage search** | `discord-os lineage [run\|DOS-*]` dump | `--search` / keyword over events+artifacts+cites; print ≤N hits with job codes | AgentTrails GUI; multi-host PROV fabric |

---

## Findings matrix (concept → today → Wave 7 → park)

| Concept | Today (≤0.5.79) | Wave 7 candidate | Park / why |
|---|---|---|---|
| TTFP / cold start | Setup docs; warm demos | Timed first-Done checklist + empty-state | Wizard / companion app |
| Filmable demo | W6 short loop | Camera-beat Wave 7 demo + COMPARISON | ttyd companion film |
| Budget alert UX | Meter + Halt badge | Soft-warn + next-step-not-run + Resume | Fleet FinOps |
| Phone Need density | Long select labels | Compact Jobs chrome | Second board |
| Gate ROE glance | Escalate copy | who/why one-liner | OCL fleet |
| Recipe findability | Markdown index | Discord browse tip | Goose YAML engine |
| Desk regression | Unit/e2e | Golden scenario harness | Cloud eval SaaS |
| Pair #2 | CLI / Roles role | Phone Pair operator | Multi-tenant harness |
| Lineage query | Dump one run | Search across DAG | PROV GUI fabric |

---

## Parked vs ship (explicit)

### Ship-shaped (single-host depth)
- Cold-start **TTFP** checklist + HOST empty-state + Wave 7 filmable demo
- Halt **soft-warn** + next-admit-not-run + Resume clarity (reuse meter/Halt)
- Need/Jobs **compact density** on phone (V2 labels/counts)
- Gate card **who/why** ROE glance line
- Discord-native **recipe index** tip (docs compose)
- Wave 7 **COMPARISON** foils (BAGEN/TokenOps, AgentTrails, Harness-MU, Agent-Harness, Goose skills)
- **Desk scenario** pytest harness (FakeDiscord goldens)
- Phone **Pair operator** friction cut
- **Lineage search** CLI (+ optional NOTE)

### Parked (HARD / overclaim)
- CU / docker / Magentic ComputerTerminal  
- Mailbox / IRC always-on peer plane  
- Multi-host DO brain lakes  
- Second JobPool / multi-gateway  
- Auto-create forum `available_tags`  
- Silent local ssh cook for `kind=ssh`  
- **Phone companion terminal / files** (Tailscale, ttyd, filebrowser)  
- CRDT multi-writer same cwd  
- Spend hard-cap **fleet** / SpendGuard / TokenOps control-plane clone  
- Goose YAML recipe runtime  
- AgentTrails / Flowcept product dependency  

---

## Sources index (top links)

1. https://arxiv.org/abs/2505.00753 — LLM-HAS survey (human-phase / TTFP metrics)  
2. https://arxiv.org/abs/2603.10664 — Terminal Is All You Need (medium transparency)  
3. https://arxiv.org/abs/2606.00198 — BAGEN budget-aware agents  
4. https://arxiv.org/abs/2606.21856 — Harness-MU multi-user harness  
5. https://arxiv.org/html/2603.17170v1 — PAuth task-scoped authorization  
6. https://arxiv.org/abs/2607.18816 — AgentTrails provenance / reuse  
7. https://arxiv.org/abs/2508.02866 — PROV-AGENT  
8. https://arxiv.org/abs/2609.10901 — SearchAtlas  
9. https://github.com/theagentplane/tokenops — TokenOps Halt/ledger  
10. https://github.com/Suirotciv/Agent-Harness — pytest agent harness  
11. https://goose-docs.ai/docs/guides/context-engineering/using-skills/ — Goose skills discoverability  
12. https://docs.discord.com/developers/components/reference — Components V2 density  

**Overlap callouts:** INTENT + Green SARC + Ledger (W6) → meter shipped; BAGEN/TokenOps/pi-dashboard → **Halt soft UX**. ARC cites (W6) → AgentTrails/PROV-AGENT → **search**. OCL escalate copy (W6) → PAuth → **who/why glance**.

---

## Method notes / blockers

- Tip for this audit: `/workspace/discord-os-w6p2` **0.5.79** (`09e37c1`). `/workspace/discord-os-tip` lagging at **0.5.72** — sync/ignore for Wave 7 implement.  
- Did **not** clone new GitHub repos; OSS from public docs/search.  
- No Mac / machineId / PyPI / push performed.  
- **EoW validation (tip + pytest + live Discord) is mandatory after every Wave 7 ship band** — do not skip.

