# Discord OS — Discord-native modules audit

**Audience:** Cary Palmer / Discord OS  
**Scope:** Discord-specific packages & academic HCI that can bolt onto an existing Python Discord host (`discord.py` / interactions-style), **not** generic multi-agent frameworks.  
**Date:** 2026-09-16 (America/Chicago)  
**Hard parks (out of scope here):** CU/docker, mailbox/IRC peer plane, multi-host DO lakes, second JobPool, multi-gateway, auto forum tags create, silent ssh, phone companion Tailscale/ttyd. Voice guild join remains parked until DAVE.

---

## Legend

| Field | Meaning |
| --- | --- |
| **Tack-on** | Can it be imported as a module without rewriting Discord OS gateway? **yes** / **partial** / **no** |
| **Ship** | Reasonable to try in tip (≥0.5.80) soon |
| **Park** | Interesting later, dead, rewrite-forcing, policy risk, or wrong shape |
| **Stars** | GitHub stargazers as of research day (activity signal, not quality) |

---

## A) Catalog (≥12 candidates)

### A1. UI / Components V2 / pagination (highest relevance to JobPool cards)

#### 1. `discord-kagekit` (PyPI: `discord-kagekit`)
| | |
| --- | --- |
| **Repo** | https://github.com/VorEdgeJP/kagekit |
| **Stars / activity** | 0★; pushed 2026-08-18; PyPI 0.1.0 |
| **Lang / license** | Python / MIT |
| **Tack-on** | **yes** — pure discord.py 2.7+ LayoutView helpers; no gateway ownership |
| **Gap closed** | Declarative **Components V2** panels: TabBar, Card, SettingRow, Pager, ActionBar, Theme/Labels — maps directly onto Discord OS JobPool/cards HOST UI without hand-rolling layout budget bugs |
| **Risk** | Brand-new / unproven (0★); API may churn; requires discord.py ≥2.7 |
| **Verdict** | **SHIP candidate #1** (spike first) |

#### 2. `discord-pager` (PyPI: `discord-pager`)
| | |
| --- | --- |
| **Repo** | https://github.com/zprix/discord-pager |
| **Stars / activity** | 0★; pushed 2026-08-14; PyPI 0.1.2 |
| **Lang / license** | Python / MIT |
| **Tack-on** | **yes** — drop-in paginator; optional PagerCV2 for LayoutView |
| **Gap closed** | Embed + **Components V2** pagination for long JobPool lists / logs |
| **Risk** | Very new / low adoption; overlaps kagekit pager; copy-folder install option is fine |
| **Verdict** | **SHIP candidate #2** if kagekit spike fails or only need pagination |

#### 3. `discord-ext-pager` (PyPI: `discord-ext-pager`)
| | |
| --- | --- |
| **Repo** | https://github.com/thegamecracks/discord-ext-pager |
| **Stars / activity** | 5★; pushed 2026-09-13; PyPI 1.1.5 |
| **Lang / license** | Python / MPL-2.0 |
| **Tack-on** | **yes** — menus-shaped PageSource API on Views |
| **Gap closed** | Mature View pagination for pre-CV2 or hybrid UIs; familiar if anyone used Danny’s menus |
| **Risk** | Author notes pre-CV2; suggests writing LayoutView yourself for newest UI |
| **Verdict** | **SHIP** as fallback / familiarity bridge; prefer CV2-native above |

#### 4. `discord-ext-modal-paginator` (PyPI: `discord-ext-modal-paginator`)
| | |
| --- | --- |
| **Repo** | https://github.com/Soheab/modal-paginator |
| **Stars / activity** | 7★; last release 2025-05-02; PyPI 1.3.0 |
| **Lang / license** | Python / MPL-2.0 |
| **Tack-on** | **yes** |
| **Gap closed** | Multi-page **modals** (forms that exceed one modal) — useful for complex Job create / HOST config |
| **Risk** | Niche; quiet since May 2025 |
| **Verdict** | **SHIP** only if modal forms are a pain point; else park |

#### 5. `dpy-paginator` (PyPI: `dpy-paginator`)
| | |
| --- | --- |
| **Repo** | https://github.com/OnceYT/dpy-paginator |
| **Stars / activity** | 4★; pushed 2024-10-28 |
| **Lang / license** | Python / MIT |
| **Tack-on** | **yes** |
| **Gap closed** | Simple embed pagination + jump-to modal |
| **Risk** | Stale relative to CV2; superseded by discord-pager / kagekit |
| **Verdict** | **PARK** |

#### 6. `discord-ui` (archived)
| | |
| --- | --- |
| **Repo** | https://github.com/discord-py-ui/discord-ui |
| **Stars / activity** | 36★; **archived**; last push 2022-02 |
| **Lang / license** | Python / MIT |
| **Tack-on** | **no** (obsolete vs native `discord.ui`) |
| **Gap closed** | Historically buttons/slash before discord.py 2.0 |
| **Risk** | Dead; conflicts with modern discord.py |
| **Verdict** | **PARK — dead** |

#### 7. `discord-ext-menus` / `discord-ext-hybrid-menus`
| | |
| --- | --- |
| **Repos** | https://github.com/Rapptz/discord-ext-menus (235★, last 2022); hybrid https://github.com/regulad/discord-ext-hybrid-menus (**archived**) |
| **Tack-on** | **partial** (reaction menus conflict with modern View UX) |
| **Verdict** | **PARK** — use `discord-ext-pager` or CV2 instead |

---

### A2. Presence / webhooks / HTTP interactions (bolt-on utilities)

#### 8. `pypresence` (PyPI: `pypresence`)
| | |
| --- | --- |
| **Repo** | https://github.com/qwertyquerty/pypresence |
| **Stars / activity** | 740★; pushed 2026-07-08; PyPI 4.6.2 |
| **Lang / license** | Python / MIT |
| **Tack-on** | **yes** — IPC Rich Presence; **separate** from bot gateway |
| **Gap closed** | Mac process “Discord OS is the computer” — show current Job / HOST state on Cary’s Discord client presence |
| **Risk** | Client-side only (not guild presence); needs Discord desktop running; not a bot feature |
| **Verdict** | **SHIP candidate #3** for product feel (presence as OS status) |

#### 9. `discord-webhook` (PyPI: `discord-webhook`)
| | |
| --- | --- |
| **Repo** | https://github.com/lovvskillz/python-discord-webhook |
| **Stars / activity** | 539★; pushed 2026-08-16; PyPI 1.4.1 |
| **Lang / license** | Python / MIT |
| **Tack-on** | **yes** — HTTP only; no gateway |
| **Gap closed** | Side-channel alerts / Job completions without burning bot rate limits; sync+async |
| **Risk** | Webhook channel UX ≠ interactive cards; don’t use for primary JobPool UI |
| **Verdict** | **SHIP** for ops notifications; keep cards on bot interactions |

#### 10. `discord-interactions` (official) (PyPI: `discord-interactions`)
| | |
| --- | --- |
| **Repo** | https://github.com/discord/discord-interactions-python |
| **Stars / activity** | 116★; last push **2024-04-30** (quiet) |
| **Lang / license** | Python / MIT |
| **Tack-on** | **partial** — Ed25519 verify + PING; for **HTTP interaction endpoint**, not gateway bots |
| **Gap closed** | If Discord OS ever adds serverless slash/button endpoints beside gateway host |
| **Risk** | Stale; discord.py already covers gateway interactions; dual path adds complexity |
| **Verdict** | **PARK** unless HTTP-only edge is planned |

---

### A3. Devtools / cogs / rate-limit infrastructure

#### 11. `jishaku` (PyPI: `jishaku`)
| | |
| --- | --- |
| **Repo** | https://github.com/scarletcafe/jishaku (also Gorialis/jishaku) |
| **Stars / activity** | 579★; PyPI 2.7.5; requires discord.py ≥2.4 |
| **Lang / license** | Python / MIT |
| **Tack-on** | **yes** — load as cog/extension |
| **Gap closed** | Owner REPL, diagnostics, Python/shell introspection while developing Discord OS on tip |
| **Risk** | Extremely powerful (eval); **must** stay owner-only; not end-user product surface |
| **Verdict** | **SHIP** for Cary-dev only, not product users |

#### 12. `nirn-proxy` (Go)
| | |
| --- | --- |
| **Repo** | https://github.com/germanoeich/nirn-proxy |
| **Stars / activity** | 183★; **archived**; last push 2026-03-20 |
| **Lang / license** | Go / GPL-3.0 |
| **Tack-on** | **partial** — HTTP proxy in front of Discord REST; not a Python import |
| **Gap closed** | Multi-bot shared rate-limit bucket coordination |
| **Risk** | Archived; GPL; multi-bot is near **multi-host/multi-gateway** park territory; discord.py already handles single-process limits well |
| **Verdict** | **PARK** (conflicts with single-host Discord OS posture) |

#### 13. `discord-ext-ipc` (archived)
| | |
| --- | --- |
| **Repo** | https://github.com/Ext-Creators/discord-ext-ipc |
| **Stars / activity** | 92★; **archived** 2021 |
| **Tack-on** | **partial** historically |
| **Verdict** | **PARK — dead**; Discord OS already has Mac process ↔ Discord as the plane |

#### 14. `discord-ext-voice-recv`
| | |
| --- | --- |
| **Repo** | https://github.com/imayhaveborkedit/discord-ext-voice-recv |
| **Stars / activity** | 231★; PyPI 0.5.2a179 experimental; pushed 2025-06 |
| **Lang / license** | Python / MIT |
| **Tack-on** | **partial** — needs voice client; guild join **HARD PARK until DAVE** |
| **Gap closed** | Receive audio sinks once voice is unparked |
| **Risk** | Experimental alpha; DAVE policy park |
| **Verdict** | **PARK until DAVE** (note only) |

---

### A4. Alternate Python Discord libraries (fitness vs rewrite)

| # | Name | Repo | Stars | License | Tack-on | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | **discord.py** (baseline) | Rapptz/discord.py | 16187 | MIT | n/a (host) | Stay |
| 16 | **py-cord** | Pycord-Development/pycord | 2956 | MIT | **no** | Full fork rewrite; active but no tack-on win |
| 17 | **nextcord** | nextcord/nextcord | 1260 | MIT | **no** | Fork rewrite |
| 18 | **disnake** | DisnakeDev/disnake | 772 | MIT | **no** | Fork rewrite |
| 19 | **interactions.py** | interactions-py/interactions.py | 874 | MIT | **no** | Different bot framework; rewrite |
| 20 | **hikari** (+ crescent/lightbulb/miru) | hikari-py/hikari | 920 | MIT | **no** | Excellent typed microframework but **forces rewrite**; miru/yuyo only help *inside* hikari |
| 21 | **hikari-crescent** | hikari-crescent/hikari-crescent | 50 | MPL-2.0 | **no** | Hikari-only command plugins |

**Brief note (allowed):** Hikari + Crescent/Lightbulb/Miru is the strongest *rewrite* ecosystem if Discord OS ever abandoned discord.py — but that is **not** a bolt-on. Skip unless a greenfield host is desired.

---

### A5. “Framework / dashboard / panel” packages

#### 22. Beacon
| | |
| --- | --- |
| **Repo** | https://github.com/DopamineStudios/beacon |
| **Stars / activity** | 1★; Apache-2.0; pushed 2026-08-08 |
| **Tack-on** | **partial/no** — wants to own Bot bootstrap (“4 lines”); in-Discord owner dashboard interesting |
| **Gap closed** | Diagnosis graphs / owner dashboard patterns |
| **Risk** | Tiny; framework-shaped (competes with HOST); cherry-pick ideas, don’t adopt whole |
| **Verdict** | **PARK** as dependency; **mine UX ideas** |

#### 23. `pydiskit` / `discea`
| | |
| --- | --- |
| **PyPI** | pydiskit 3.0.0 (Aug 2026); discea 0.1.2 |
| **Tack-on** | **no** — thin Bot wrappers that own run/sync |
| **Verdict** | **PARK** — reinvent HOST poorly |

#### 24. `discord-ext-dashboard` / `discordbotdash` / `discord-insight`
| | |
| --- | --- |
| **Repos** | mak0226/discord-ext-dashboard (8★, 2022); sachinraja/discordbotdash (archived 2021); rugved-danej/discord-insight (PyPI 0.0.1) |
| **Tack-on** | **partial** (web dashboards beside bot) |
| **Gap closed** | External analytics panels |
| **Risk** | Stale or newborn; Discord OS screen is Discord itself — web dashboards fight the product thesis |
| **Verdict** | **PARK** (product philosophy conflict) |

#### 25. `ahnaf-zamil/discord.py-bot-dashboard`
| | |
| --- | --- |
| **Repo** | https://github.com/ahnaf-zamil/discord.py-bot-dashboard |
| **Stars** | 10★; last 2021 |
| **Verdict** | **PARK — dead tutorial** |

---

### A6. Activities / Embedded App SDK (adjacent plane)

#### 26. Official Embedded App SDK + examples
| | |
| --- | --- |
| **Repos** | https://github.com/discord/embedded-app-sdk (1402★, TS); https://github.com/discord/embedded-app-sdk-examples (124★) |
| **Lang / license** | TypeScript / MIT |
| **Tack-on** | **no** as Python module — **yes** as optional Activity iframe product surface |
| **Gap closed** | Rich canvases beyond message components (job board Activity, visual JobPool) |
| **Risk** | New stack (web/TS); separate OAuth/token exchange; not a cog |
| **Verdict** | **PARK for Python host**; **SHIP-later product bet** if cards hit Discord UI ceiling |

#### 27. Colyseus / Phaser / Robo.js Activity templates
| | |
| --- | --- |
| **Repos** | colyseus/discord-activity (52★); phaserjs/discord-multiplayer-template (47★); Wave-Play/robo.js (91★) |
| **Tack-on** | **no** (TS game/Activity frameworks) |
| **Verdict** | **PARK** — note as Activity demos only; Robo.js is Discord-first but not Python |

---

### A7. Forum / thread / AutoMod / scheduled events

**Finding:** No strong standalone “forum helper” PyPI package worth adopting.  
`discord.py` already exposes:

- `ForumChannel.create_thread`, tags (manual — auto-create tags is **HARD PARK**)
- `Guild.create_scheduled_event` + event listeners
- `Guild.create_automod_rule` / `on_automod_action`

**Verdict:** Prefer native discord.py APIs. Academic work (ApoloBot CHI’25) shows **threads + modals + buttons** as the right Discord-native workflow pattern — implement in HOST, don’t import a dead forum lib.

---

## B) arXiv / academic (2023–2026)

Discord-specific HCI/ops literature exists but is **sparse relative to Slack/Reddit**; most useful papers are **moderation / education / collaborative bot design**, not packaging.

| Paper | Year | Link | Relevance to Discord OS |
| --- | --- | --- | --- |
| **ApoloBot — Design Space for Online Restorative Justice Tools** (CHI ’25) | 2025 | https://arxiv.org/abs/2502.18861 | Discord-native: slash + private threads + modals + log channel. Design lesson: bolt restorative/ops workflows onto bots mods already trust; mid-size social servers fit best |
| **Botender — Collaborative LLM bot design via case-based provocations** | 2025–26 (CHI’26 track) | https://arxiv.org/abs/2509.25492 | Discord field study: proposals + threads + voting + test cases. Pattern for community-shaped Job/HOST behavior without coding — **UX inspiration**, not a Python dep |
| **Interactive Learning… Discord Chatbot** (CS1 feedback bot) | 2024 | https://arxiv.org/abs/2407.19266 | Continuous feedback via components; attendance keyword; used **Pycord**. Validates Discord-as-classroom-ops screen |
| **ConvEx** (Discord mod visual explorer) | CSCW 2023 | ACM 10.1145/3610053 | Moderation HCI for Discord conversation exploration (cite for panel design) |
| VIP-Bot usability (Discord academic chatbot, SUS 76.36) | 2024 | Strathclyde / ITS 2024 | `/chat` + public threads UX for academic help |

**Scarcity note:** Few papers on Discord **Components V2**, Activities SDK, or Python library ecosystems. Ops insights are stronger from CHI/CSCW Discord bot deployments than from arXiv systems papers.

---

## Parked vs ship (rollup)

### SHIP (tack-on now)
1. **discord-kagekit** — CV2 card/tab/pager contract for JobPool  
2. **discord-pager** — CV2/embed pagination fallback  
3. **pypresence** — Mac client Rich Presence for live Job/HOST  
4. **discord-webhook** — side-channel ops alerts  
5. **jishaku** — Cary-only debug cog  
6. **discord-ext-pager** / **modal-paginator** — optional if gaps remain  

### PARK
- All discord.py **forks** & hikari stack (rewrite)  
- Archived: discord-ui, discord-ext-ipc, hybrid-menus, nirn-proxy (archived), old dashboards  
- voice-recv until DAVE  
- Web dashboard frameworks (fight Discord-as-screen thesis)  
- Activities SDK (separate TS product surface)  
- Framework wrappers: Beacon, pydiskit, discea (own the Bot)  
- Auto forum-tag creation (hard park)  

### Ideas to steal without deps
- Beacon in-Discord owner dashboard patterns  
- ApoloBot thread+modal apology/ops flows  
- Botender proposal/vote/thread governance for HOST config changes  

---

## Coverage checklist

- [x] discord-ext-* pagination/modals  
- [x] slash/app_commands era note: native discord.py 2.x owns this; old slash libs dead  
- [x] hikari/crescent/interactions/nextcord/py-cord/disnake compared  
- [x] webhook-only libs  
- [x] components/UI kits + menus successors  
- [x] discord-interactions HTTP  
- [x] Embedded App SDK OSS  
- [x] forum helpers (none strong; use native)  
- [x] rate-limit / gateway resilience (native + parked nirn)  
- [x] job board / panel / dashboard frameworks  
- [x] ≥12 concrete candidates evaluated with yes/partial/no tack-on  

