# Discord OS vs nearby products

Short positioning for humans deciding whether to share a desk. Not a feature matrix sales sheet.

## One-line

**Discord OS** = Discord is the screen; one Mac (or allowed SSH host) is the computer; Puppetmaster cooks; SQLite is the DAG. Shared-desk cowork is operators + Pair + channel binds — not a second cloud brain.

## Vs Anthropic Cowork / “computer use” desks

| | Discord OS | Typical Cowork / CU desk |
|---|---|---|
| Screen | Discord (phone-first HOST + job threads) | Product UI / desktop session |
| Computer | Your Mac process + optional opt-in SSH cook | Vendor runtime / VM / CU |
| Workers | OpenRouter/agentic Puppetmaster only | Often bundled model + tool runtime |
| Sharing | `REQUIRE_OPERATORS` + Pair allowlist | Account / org seats |
| Computer-use | **Parked** until explicit greenlight | Often the headline |

Discord OS does **not** claim a multi-host brain-lake or silent local fallback for `kind=ssh`. Path A remote cook is opt-in via SSH gates.

## Vs Discord↔CLI bridges (custom bots that shell out)

Many bridges: message in → `subprocess` → paste stdout back.

Discord OS adds:

- **JobPool** — up to `DISCORD_OS_MAX_LIVE` live jobs; analyze may overlap; implement serializes per checkout
- **Cards** — Need / Jobs / Gate / Plan-approve in Discord, not log spam
- **Lineage** — SQLite tasks/runs/events/artifacts; `discord-os lineage`
- **HOST power** — On/Off arms acceptance; schedules and asks respect armed state
- **Realms / memory / wiki / github** — channel binds, not one mega-prompt

If you only need “relay chat to a shell,” a thin bridge is smaller. If you need a **shared desk** with operators, gates, and recoverable jobs, use Discord OS.

## Vs CoWork OS–style supervisors

Supervisor products often own multi-agent routing, fleets, and policy engines as the product.

Discord OS keeps the supervisor thin:

- Discord = ACL + notification + object plane
- One live gateway forever (no multi-gateway)
- Puppetmaster = cook backend (no Cursor compute path)
- Policy locks are explicit (see [host/policy](host/policy.md)) — CU/docker parked, forum tags never auto-created, spend honesty not hard caps

Use a supervisor OS when you want fleet orchestration as the core. Use Discord OS when the **phone Discord channel** is the desk and the Mac is the computer.

## Wave 4 (board + brain lakes — still no fleet)

- **Board catch-up** — Catch-up + `digest:` / `board catch-up:` schedules surface ADR/PR lane conflicts.
- **Brain lake** — `discord-os add brain --dri` (strategy docs + transcripts + journal) on one Mac SQLite.
- **Meat-proxy cut** — handoff/peer carries lake context; humans Pair/gate on ROE only.
- Still **not** multi-host brain lakes / Durable Objects clones.

## Wave 2 shareability (still no fleet)

- **Cross-host RO** — `discord-os host hosts` (+ dashboard/digest reach bits). Allowlist fail-closed; probes never cook; `kind=ssh` unreachable is spoken honestly (no silent local fallback).
- **Forum-tags lock** — tags-as-tickets only maps **existing** `available_tags`; `modify_channel` refuses creating guild tags. Soft-skip when status tags are missing.
- **Mailbox** — external agent inbox stays **parked** (job threads + handoff only).

## Shareability bar (Puppetmaster-tier)

Someone else can:

1. `pip install discord-os` + bootstrap
2. Harden with `DISCORD_OS_REQUIRE_OPERATORS=1` and Pair
3. Bind realm + memory on a channel
4. Dual-operator ask/steer without sharing the bot token casually
5. Park gates instead of Always-allow footguns
6. Optional: schedule an overnight brief with Catch-up honesty; handoff via JobPool-only peer

See [co-work/shared-desk-demo](co-work/shared-desk-demo.md) for a &lt;15 minute filmable recipe (handoff + overnight brief). Playbooks index: [recipes](recipes/README.md).
