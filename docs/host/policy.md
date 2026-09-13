# HARD locks (product policy)

Discord is the screen. This Mac is the computer. These locks are **stamped** —
do not invent around them. Agents and humans: if a request fights a lock, refuse
or park; do not “quietly” ship the opposite.

See also: [host README](README.md), [ask-gate](../cards/ask-gate.md),
[voice](voice.md), [slash](slash.md), [compute](../compute/README.md),
[realms](../realms/README.md).

| # | Lock | Meaning |
|---|---|---|
| 1 | **SSH bridge OPT-IN** | `DISCORD_OS_SSH_GATES=bridge` only when the operator opts in. Default unset = honest gap (write-gate on → spoken Need + remote Deny). Never arm the live reverse hold by accident. |
| 2 | **No forum auto-create tags** | Tags-as-tickets maps JobPool status ↔ existing Discord `available_tags` names. Soft-skip when none match. Discord OS **never** invents / POSTs guild tags. |
| 3 | **Path A never silent local for `kind=ssh`** | Allowlisted SSH cooks via Path A remote cook only. Unreachable / disabled / bridge fail-closed → spoken Deny. Never fall back to a quiet local cook on the control-plane Mac. |
| 4 | **Single gateway** | One Gateway owner per bot token (SQLite lock). Intake is REST; Gateway exists so On/Off buttons work. No second bot process / multi-gateway fan-out. |
| 5 | **Update = PyPI latest** | HOST Update pill compares installed package to **PyPI** `discord-os` latest. Fail soft if PyPI unreachable. No auto-upgrade; no night side-channel. |
| 6 | **Guild voice = local TTS / memo only** | Local Mac `say`/`espeak` TTS + voice memos (whisper CLI). Guild voice **join** stays Deny (DAVE / libdave not shipped). Guild speak/listen parked Deny. |
| 7 | **Spend honesty-only** | Omitted OpenRouter `cost_usd` → **unknown**, never `$0`. Optional Halt / env cap may exist for operator control — not a product “spend caps” fleet. No invented hard-cap marketing. |
| 8 | **Desk single-user OK** | Default soft first-armed-human seed. `DISCORD_OS_REQUIRE_OPERATORS=1` (or allowlist alias) hardens for shared / public interactions. Desk Mac with interactions off stays workable. |
| 9 | **Slash self-heal when interactions exposed** | `AGENT_DISCORD_INTERACTIONS=http` → listen host version-aware re-registers slash (fail soft). Manual `--register` optional. Default interactions **off**. |
| 10 | **CU / docker PARKED** | Computer-use, discord-os-computer, Automaton, Cursor compute, docker desktop fantasy — **not** implemented. Do not ship half-wired CU. |

## Also refuse (folds into the table)

- **No Automaton / Cursor** as product compute (OpenRouter / puppetmaster agentic only) — locks 10 + compute docs.
- **No guild voice join** unlock via `DISCORD_OS_VOICE_JOIN=1` (intent only) — lock 6.
- **No spend hard-cap product** — lock 7.
- **No multi-gateway** — lock 4.

## Ship honesty

Bump / tag / PyPI only when the cut’s tidy items are landed and Actions are
green. Live host: install into `~/discord-os/.venv`, bounce LaunchAgent, run
`discord-os host doctor`.

Code touchpoints: `ssh_gate.py`, `forum_realm.py`, `runners.py` /
`remote_cook.py`, `gateway.py` + `gateway_health.py`, `update_check.py`,
`tts.py` / `voice.py`, `service.py` spend helpers, `interactions.py` self-heal,
docs under `docs/host/` + `docs/compute/`.
