# Discord OS — Discord-native haul (honest verdict)

**For:** Cary Palmer  
**Date:** 2026-09-16 (America/Chicago)  
**Companion catalog:** `/workspace/discord-os-discord-native-modules-audit.md`  
**Actionability:** Do this without a meeting.

---

## TLDR verdict

**There are a few good bolt-ons — not “nothing.”**  
The Discord OSS surface for *modules you import beside an existing discord.py gateway* is thin: most “frameworks” either rewrite the client (hikari/pycord/nextcord/disnake/interactions.py) or are dead pre-2.0 UI shims.  

**What is actually worth tacking on in the next tip cycle:** Components V2 UI kits (especially **kagekit**), a CV2-aware paginator, **pypresence** for Mac-side “OS status,” and **discord-webhook** for non-interactive alerts. Everything else is park, steal-ideas-only, or rewrite-forcing.

**Do not** migrate Discord OS off discord.py for library fashion. Stay on Rapptz; bolt UI.

**Loop status (0.5.85):** Bands A–D shipped. Discord-native prioritized tack-on loop **closed**. Wave 7 P1 not opened.

---

## Top tack-on candidates (ranked)

| Rank | Package | Tack-on | Why it wins for Discord OS | Act |
| --- | --- | --- | --- | --- |
| **1** | [`discord-kagekit`](https://pypi.org/project/discord-kagekit/) · [repo](https://github.com/VorEdgeJP/kagekit) | **yes** | Declarative CV2 **cards/tabs/pagers/action bars** matching JobPool/HOST panels; layout budget checks; discord.py 2.7+ only | Spike 1 afternoon: rebuild one JobPool card; if API feels right, adopt |
| **2** | [`discord-pager`](https://pypi.org/project/discord-pager/) · [repo](https://github.com/zprix/discord-pager) | **yes** | Lightweight embed + **PagerCV2**; copy-folder friendly | Use if kagekit is too opinionated or only need list paging |
| **3** | [`pypresence`](https://pypi.org/project/pypresence/) · [repo](https://github.com/qwertyquerty/pypresence) | **yes** | Rich Presence on the **Mac Discord client** — “Discord is the screen / Mac is the computer” made visible | Wire Job title + HOST state to presence; no gateway change |
| **4** | [`discord-webhook`](https://pypi.org/project/discord-webhook/) · [repo](https://github.com/lovvskillz/python-discord-webhook) | **yes** | Ops/side-channel without burning interactive rate limits | Job done / fail / tip alerts only — not primary UI |
| **5** | [`jishaku`](https://pypi.org/project/jishaku/) · [repo](https://github.com/scarletcafe/jishaku) | **yes** | Owner debug cog for tip development | Load for Cary only; never ship to end users |

**Honorable (optional):** [`discord-ext-pager`](https://pypi.org/project/discord-ext-pager/) (menus-shaped Views), [`discord-ext-modal-paginator`](https://pypi.org/project/discord-ext-modal-paginator/) (multi-step modals).

**Explicitly not in top 5:** hikari/crescent, pycord/nextcord/disnake, interactions.py, Beacon/pydiskit, Activities SDK (TS), voice-recv (DAVE park), nirn-proxy (archived + multi-bot smell), web dashboards.

---

## Immediate action plan (no meeting)

1. **Spike kagekit (90–180 min)**  
   - `pip install discord-kagekit` on a tip branch.  
   - Reimplement **one** existing JobPool / HOST settings message as `Page` + `Card` + `TabBar`.  
   - Pass/fail: fewer layout bugs, same interaction IDs/JobPool wiring, no gateway fork.  
   - Fail → fall back to `discord-pager` + hand LayoutView.

2. **Add pypresence beside the Mac process (60 min)** — **shipped 0.5.82**  
   - Presence details = current Job / idle; state = HOST mode.  
   - Independent of bot token path. Flag `DISCORD_OS_PRESENCE=0`.

3. **Webhook channel for ops (30 min)** — **shipped 0.5.84**  
   - Tip deploy, Job failure, rate-limit storms → webhook. Keep interactive cards on the bot.  
   - Extra `discord-os[webhook]`. `DISCORD_OS_WEBHOOK=0` or empty URL = off.

4. **Load jishaku behind owner check** for local tip debugging only. — **shipped 0.5.85** (loop closed)  
   - Extra `discord-os[debug]`. Default off. `DISCORD_OS_JISHAKU=1` **and** owner / allowlisted operator.  
   - Cog attach parked (REST host; no `commands.Bot` / second gateway).

5. **Do not** open PRs to swap discord.py → hikari/pycord this quarter.

---

## If the spike fails (“nothing good enough”)

Still Discord-OS-shaped alternate directions (prefer these over multi-agent frameworks):

### Alt A — Own a thin `discord_os.ui` CV2 kit
Steal kagekit’s **layout contract** (tabs outside, cards by intent, pager row, action bar outside) and implement 200–400 lines in-tree. Zero dependency risk; matches JobPool vocabulary. Academic backup: ApoloBot’s thread+modal+button flows ([arXiv:2502.18861](https://arxiv.org/abs/2502.18861)).

### Alt B — Activity as second screen (when cards hit the wall)
Use official [Embedded App SDK](https://github.com/discord/embedded-app-sdk) + [examples](https://github.com/discord/embedded-app-sdk-examples) for a Job board / visual pool. Keep Python host on gateway; Activity is iframe only. Not a cog — a deliberate product surface.

### Alt C — Governance UX, not libraries
Borrow **Botender** patterns ([arXiv:2509.25492](https://arxiv.org/abs/2509.25492)): proposal → Discord thread discussion → vote → deploy HOST config. Implement with existing JobPool/cards; no new framework.

---

## Academic takeaway (one paragraph)

Discord-specific HCI 2023–2026 is scarce but pointed: **ApoloBot (CHI’25)** shows mods accept bots that extend familiar slash/mute workflows via private threads and modals; **Botender** shows communities will collaboratively shape bot behavior when design lives *inside* Discord (threads + cases + votes); education bots show continuous component feedback works as the course “screen.” None yield a Python package to install — they validate Discord OS’s thesis and UI patterns.

---

## File paths

| Deliverable | Path |
| --- | --- |
| Full catalog | `/workspace/discord-os-discord-native-modules-audit.md` |
| This verdict | `/workspace/discord-os-discord-native-haul.md` |

---

## Top links (bookmark)

- https://github.com/VorEdgeJP/kagekit  
- https://pypi.org/project/discord-kagekit/  
- https://github.com/zprix/discord-pager  
- https://github.com/qwertyquerty/pypresence  
- https://github.com/lovvskillz/python-discord-webhook  
- https://github.com/scarletcafe/jishaku  
- https://github.com/Rapptz/discord.py  
- https://github.com/discord/embedded-app-sdk  
- https://arxiv.org/abs/2502.18861 (ApoloBot)  
- https://arxiv.org/abs/2509.25492 (Botender)  

**Recommendation Cary can act on:** Bands A–D shipped (kagekit spike FAIL→Page; pypresence; webhooks; jishaku owner-only). Discord-native prioritized loop **closed**. Stay on discord.py; park forks/Activities/voice until a deliberate bet. Wave 7 P1 not opened.
