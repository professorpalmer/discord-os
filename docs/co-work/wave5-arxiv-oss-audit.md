# Discord OS — Wave 5 arXiv + OSS audit (board + brain lakes)

**Audience:** Cary Palmer  
**Date:** 2026-09-16 (America/Chicago)  
**Status:** Research audit only — **no implementation, no commit, no PyPI, no GitHub push, no Mac machineId touch.**  
**Baseline tip (box):** `/workspace/discord-os-tip` @ `bdca6ed` / **0.5.72** (Wave 4 shipped). Brief says product ≤**0.5.73** — treat 0.5.72 tip as current close; Wave 5 = next band.  
**Branding:** domain = **board + brain lakes**. NEVER "Graham thread" in Wave 5 ship copy.  
**Sister:** Puppetmaster = worker kernel. Discord = free shared board/IRC/IAM; one Mac host = computer.

**HARD policy (do not reverse):** CU/docker parked; SSH gates opt-in; voice local TTS only; `REQUIRE_OPERATORS` when sharing; spend honesty (unknown ≠ $0); forum tags manual never auto-create `available_tags`; no multi-gateway; no second JobPool; no silent local ssh cook; no multi-host brain-lake / Durable Objects overclaims.

---

## Already shipped (Waves 1–4) — do not re-propose

| Wave band | Shipped surface |
|---|---|
| Share kit | README/COMPARISON/shared-desk demo, screenshots, recipes |
| Handoff / peer + lanes | JobPool-only `handoff`/`peer`; operator/lane attribution |
| Desk-pack | realm+memory(+wiki/github) inject story |
| Schedules | `skipped_while_disarmed` Catch-up honesty |
| Cross-host RO | Allowlist RO status only |
| Forum tags | GET + refuse create |
| Wave 4 board | Catch-up conflict digest (ADR/PR); swim-lane `↔` relationship lines |
| Wave 4 brain | `add brain --dri`; handoff lake context + ROE hint (`meat_proxy_cut`) |

External mailbox / IRC-style always-on peer protocol = **parked** (`docs/co-work/mailbox-park.md`).

---

## A) Academic / arXiv findings (≥8)

For each: **title · id · finding · Discord OS lift (or no-lift)**.

### 1. Magentic-One — `2411.04468`
- **URL:** https://arxiv.org/abs/2411.04468  
- **Finding:** Lead Orchestrator + specialized agents; **task/progress ledgers** + replan on error; modular add/remove agents without retuning others (AutoGen 0.4).  
- **Lift:** Surface a **progress ledger strip** on Live/Done JobPool cards from existing lineage events (facts already in SQLite) — not a new orchestrator plane.  
- **No-lift:** Magentic docker ComputerTerminal / browser agents (CU/docker parked).

### 2. Magentic-UI — `2507.22358`
- **URL:** https://arxiv.org/abs/2507.22358  
- **Finding:** HITL mechanisms: **co-planning, co-tasking, action guards, plan learning/retrieval, multi-tasking**; user as UserProxy; Docker sandbox for code/browser.  
- **Lift:** (a) **Plan gallery** — persist approved `plan_approve` bodies into brain-lake journal / preferences; retrieve on similar asks. (b) Co-tasking already ≈ steer + gates — deepen **receipt wording** only.  
- **No-lift:** Docker/MCP browser sandboxes; always-on parallel SaaS sessions as product claim.

### 3. LbMAS / Blackboard MAS — `2507.01701`
- **URL:** https://arxiv.org/abs/2507.01701  
- **Finding:** Agents communicate **only via public/private blackboard**; controller selects who acts from board content; shared memory replaces per-agent chat memory; conflict-resolver role.  
- **Lift:** Treat Discord Need/Live board + Catch-up as the **public blackboard**; add voluntary **`claim <job>`** so operators/DRIs take a Need without a second queue (atomic metadata on existing task). Private spaces ≈ per-DRI brain lake (already Wave 4).  
- **No-lift:** LLM-as-control-unit replacing HOST On/Off / JobPool admission.

### 4. LLM Blackboard for data discovery — `2510.01285`
- **URL:** https://arxiv.org/abs/2510.01285 (pdf: https://arxiv.org/pdf/2510.01285)  
- **Finding:** Central agent **posts requests**; subordinates **voluntarily** respond — broadcast request ≠ assigned subtask.  
- **Lift:** Same as #3 — `Need` cards as broadcast requests; claim/volunteer language in handoff docs + optional claim verb. Reinforces board branding.  
- **No-lift:** Autonomous data-lake partition agents across hosts.

### 5. Agent Context Protocols (ACP) — `2505.14569`
- **URL:** https://arxiv.org/abs/2505.14569  
- **Finding:** Structured agent↔agent messages + **persistent execution DAG** + status codes / error schemas for long-horizon fault recovery.  
- **Lift:** **Typed handoff envelope** on JobPool peer tasks: `handoff_id`, constraints, expecting, freshness, supersedes, ROE hint — schema in metadata + spoken card fields. Map status codes → existing Need/Cancel/Done honesty.  
- **No-lift:** Full ACP generalist web-agent stack / multi-modal report factory.

### 6. CodeCRDT — `2510.18893`
- **URL:** https://arxiv.org/abs/2510.18893  
- **Finding:** Observation-driven shared CRDT state enables parallel code gen with character-level convergence, but **semantic conflicts remain (~5–10%)** and speedups are task-dependent (sometimes slowdowns).  
- **Lift:** Extend board-catchup heuristics with **shared write-key / path tokens** (cwd + file hints) → Conflicts section — agent/human mediated, not auto-merge. Documents *why* Discord OS keeps per-cwd serialize.  
- **No-lift:** Yjs/CRDT concurrent writers on same checkout (conflicts HARD serialize + single-host honesty).

### 7. SagaLLM — `2503.11951`
- **URL:** https://arxiv.org/abs/2503.11951  
- **Finding:** Saga-style **checkpoint + compensation** for multi-agent plans; independent validators; context persistence across handoffs.  
- **Lift:** When a peer/handoff job fails or Cancel, post a **compensation NOTE** on parent thread (lineage-linked) — fail-closed honesty, not silent orphan.  
- **No-lift:** Full ACID / distributed saga runtime across hosts.

### 8. MemGPT — `2310.08560`
- **URL:** https://arxiv.org/abs/2310.08560  
- **Finding:** OS-inspired **tiered memory** (fast working vs slow archival) + interrupts for user control; multi-session continuity without stuffing full history.  
- **Lift:** **Brain-lake recall pack** — compact cited pack (strategy docs titles + last N journal + last Done summaries) injected instead of unbounded paste; budget-clipped like meat-proxy preamble.  
- **No-lift:** Autonomous paging agent that mutates memory without operator visibility.

### 9. MetaGPT — `2308.00352`
- **URL:** https://arxiv.org/abs/2308.00352  
- **Finding:** Encode **SOPs / roles** into assembly-line agents; structured artifacts reduce cascading hallucination vs free chat.  
- **Lift:** Optional **role SOP label** on `add brain --dri` (e.g. implementer / reviewer / planner) → prompt inject + lane label; still one JobPool.  
- **No-lift:** Cloning MetaGPT's full company simulation as Discord OS core.

### 10. ChatDev — `2307.07924`
- **URL:** https://arxiv.org/abs/2307.07924  
- **Finding:** Role-specialized chat chain for design→code→test; communicative dehallucination.  
- **Lift:** Weak — Discord OS already has analyze/implement/swarm + gates. Use only as COMPARISON foil ("chat-chain company" vs board+gates).  
- **No-lift:** ChatDev waterfall as product architecture.

### 11. AutoGen — `2308.08155`
- **URL:** https://arxiv.org/abs/2308.08155  
- **Finding:** Conversable agents with LLM/human/tool modes; programmable conversation patterns.  
- **Lift:** Conceptual only — Discord threads + Pair + gates already are the human-in-conversation surface. COMPARISON: AutoGen Studio = lab UI; Discord OS = phone board.  
- **No-lift:** Embedding AutoGen runtime beside JobPool.

### 12. AgentOrchestra / TEA — `2506.12508`
- **URL:** https://arxiv.org/abs/2506.12508  
- **Finding:** Hierarchical planner + localized tool ownership; lifecycle/versioning of agents/tools/env/memory.  
- **Lift:** Weak — keep supervisor thin (policy). Optional: version stamp brain-lake bind + recipe cadence (already recipes).  
- **No-lift:** Hierarchical multi-environment TEA protocol / self-evolving agent fleets.

### 13. CAMEL — `2303.17760` (supporting)
- **URL:** https://arxiv.org/abs/2303.17760  
- **Finding:** Role-playing communicative agents; inception prompting.  
- **Lift:** No product lift — historical pattern cite in audit only.

**Count:** 12 primary + CAMEL supporting (≥8 satisfied). Search also touched GPTSwarm / SwarmAgentic — **no-lift** (graph/PSO system generation ≠ Discord OS desk).

---

## B) Open-source offerings (≥8)

Honest compare: what they do well that Discord OS ≤0.5.72 lacks; **single-host limit** for Discord OS.

| # | Offering | URL / locus | They do well | Discord OS gap vs tip | Honest single-host limit |
|---|---|---|---|---|---|
| 1 | **OpenHands** | https://github.com/All-Hands-AI/OpenHands | Sandboxed agent server, event-sourced conversations, multi-agent workspace patterns (shared vs isolated clones) | No sandboxed remote Agent Server UI; coordination is Discord cards not OH canvas | Discord OS stays one Mac process + JobPool; CU/docker **parked** — do not chase OH DockerWorkspace |
| 2 | **Aider** | https://github.com/Aider-AI/aider | Git-native pair loop; tight commit discipline | Not a multiplayer board; no Discord screen | DOS owns shared desk; Aider owns surgical CLI pair — complementary, not clone |
| 3 | **Continue** | https://github.com/continuedev/continue | IDE chat+autocomplete+agent pane | No Discord HOST / operators | IDE-resident ≠ phone board |
| 4 | **Cline** (+ Roo legacy) | https://github.com/cline/cline | Step approval gates inside VS Code | Gates exist in Discord; IDE-local UX polish not DOS | Approval UX already shippable via cards; no VS Code extension goal |
| 5 | **Goose (Block)** | https://github.com/block/goose | MCP-first extensibility, enterprise allowlists | MCP tools exist as providers; not Goose-shaped desktop | Extend via existing MCP providers; not a second gateway |
| 6 | **Magentic-One / Magentic-UI** | https://aka.ms/magentic-one · https://github.com/microsoft/magentic-ui | Progress ledgers, co-plan, plan gallery, action guards | Ledger/plan-gallery depth thin post–Wave 4 | Lift ledger+plan gallery onto JobPool/brain lake; park Docker |
| 7 | **AutoGen Studio** | Microsoft AutoGen ecosystem | Visual multi-agent lab | Not phone-first shared desk | COMPARISON foil only |
| 8 | **CrewAI** | https://github.com/crewAIInc/crewAI | Role crews + task graphs for apps | In-process crews ≠ Discord board IAM | Keep swarm inside one cook; no CrewAI runtime |
| 9 | **LangGraph** | LangChain LangGraph | Durable graph state / checkpoints | Lineage SQLite is DOS durable state | Optional inspiration for handoff checkpoint fields; no LangGraph dependency |
| 10 | **HuggingFace smolagents** | https://github.com/huggingface/smolagents | Tiny code-agent loops / managed subagents | No shared Discord board | Too small a surface for DOS marketing |
| 11 | **Claude Code / Cursor Background Agents** (patterns) | Anthropic / Cursor products | Background agent teams, cloud desks | DOS = Discord screen + local Mac; no vendor background fleet | Do not overclaim Devin-like always-on teammates |
| 12 | **Discord agent bridges** (OpenAB, Disclaw, Agent4Discord, Kimaki, etc.) | e.g. https://github.com/openabdev/openab | Thread→CLI relay, multi-agent messaging, cron | Thin bridges lack JobPool/cards/lineage/HOST power | COMPARISON already covers; DOS wins on desk depth |
| 13 | **File handoff protocols** (claude-multi-agent-protocol, SMALL, Qarinah-style) | GitHub / docs ecosystems | Append-only HANDOVER/SYNC; cited continuation packs; single-writer honesty | Handoff is free-text + thin metadata | **Typed envelope + recall pack** is the Wave 5 lift |
| 14 | **CRHQ / satellite CoS** | crhq.ai (product) | Skills cadence, overnight briefs, multi-agent roles | Audited — prefer JobPool compose (`docs/co-work/crhq-audit.md`) | No CRHQ clone / satellite mailbox |
| 15 | **BrainDAO mcp-discord** | Already adapted as `braindao` provider | MCP Discord tools | Ingress seam exists | Not a brain-lake product — naming coincidence only |

---

## Findings matrix (concept → today → Wave 5 → park)

| Concept | Today (≤0.5.72 tip) | Wave 5 candidate | Park / why |
|---|---|---|---|
| Blackboard / shared board | Need/Live/Done + Catch-up ADR/PR | Claim verb + write-key conflict hints | CRDT multi-writer |
| Progress ledger | Lineage exists; cards thin | Ledger strip on cards | Second orchestrator |
| HITL co-plan / plan learn | `plan_approve` | Plan → brain journal gallery | Docker Magentic-UI |
| Typed handoff | Preamble + metadata keys | Envelope schema + already_claimed | Always-on IRC mailbox |
| Durable brain memory | `add brain --dri` inject | Compact recall pack (MemGPT-style) | Multi-host DO lakes |
| Compensation on fail | Cancel honesty local | Parent NOTE on failed peer | Distributed saga fleet |
| Role SOPs | Lane labels | Optional DRI role on brain | ChatDev company sim |
| Shareability | Wave 1–3 kit; Wave 4 docs | **board + brain lakes** COMPARISON/demo | Marionette-era claims |

---

## Parked vs ship (explicit)

### Ship-shaped (single-host depth)
- Typed JobPool handoff envelope + idempotent claim  
- Brain-lake compact recall pack  
- Plan gallery into brain journal  
- Progress ledger strip from lineage  
- Board-catchup write-key / path conflict deepen  
- Wave 5 share kit: brand **board + brain lakes**

### Parked (HARD / overclaim)
- CU / docker / Magentic ComputerTerminal  
- Multi-host replicated brain lakes / Durable Objects  
- Second JobPool / external agent mailbox / always-on IRC peer protocol  
- Auto-create forum `available_tags`  
- Multi-gateway / second bot process  
- Silent local ssh cook  
- CRDT concurrent same-cwd implement  
- Spend hard-cap fleet marketing  

---

## Sources index (top links)

1. https://arxiv.org/abs/2411.04468 — Magentic-One  
2. https://arxiv.org/abs/2507.22358 — Magentic-UI  
3. https://arxiv.org/abs/2507.01701 — LbMAS blackboard  
4. https://arxiv.org/abs/2505.14569 — Agent Context Protocols  
5. https://arxiv.org/abs/2510.18893 — CodeCRDT  
6. https://arxiv.org/abs/2503.11951 — SagaLLM  
7. https://arxiv.org/abs/2310.08560 — MemGPT  
8. https://arxiv.org/abs/2308.00352 — MetaGPT  
9. https://github.com/All-Hands-AI/OpenHands — OpenHands  
10. https://github.com/microsoft/magentic-ui — Magentic-UI OSS  

---

## Method notes / blockers

- Tip on box is **0.5.72** (not 0.5.73); no evidence of 0.5.73 on this box — Wave 5 planned against Wave 4 close.  
- WebFetch timed out on some abs pages (`2308.00352`, `2510.01285`); IDs confirmed via search + alternate fetches; MetaGPT/ChatDev/AutoGen IDs are stable community canon.  
- Did **not** clone new GitHub repos; OSS compare is from public docs/search + prior DOS audits.  
- No Mac / machineId / PyPI / push performed.
