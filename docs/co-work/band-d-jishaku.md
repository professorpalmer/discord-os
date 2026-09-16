# Band D — jishaku (Cary tip debugging only)

**Ship:** Discord OS **0.5.85**. Not a product feature. Discord-native prioritized loop (Bands A–D) **closed**.

Optional `jishaku` extra for Cary tip debugging on a private desk. Default **off**. Owner / allowlisted operator only. Shared `REQUIRE_OPERATORS` demos stay off unless both gates pass.

## Install / enable

```bash
pip install "discord-os[debug]"   # optional extra; CI mocks the load path
export DISCORD_OS_JISHAKU=1        # explicit; unset / 0 / off = off
```

| Knob | Meaning |
|---|---|
| Default | **Off.** Unset, empty, `0`, `off`, `false`, `no` |
| `DISCORD_OS_JISHAKU=1` | Flag on. Still insufficient without an owner / allowlisted operator |
| Invoker | Must already be owner or allowlisted operator. Flag does not seed owner |
| Shared demos | `REQUIRE_OPERATORS=1` does **not** turn this on |

## Architecture park

Host I/O is REST + a stdlib Gateway so On/Off buttons work. That is not `discord.ext.commands.Bot`. Jishaku's cog cannot attach without a second gateway (HARD lock: single gateway). The extra may import when both gates pass; the cog stays parked. `jsk` / `jishaku` in-channel is intercepted only while the flag is on (Denied or a short parked line — never a cook).

No gateway rewrite. Stay on the existing discord.py-era REST host. kagekit / presence / webhook left as-is.

## Parks

Board + brain lakes (never Graham). Wave 7 P1 not opened. HARD parks unchanged: CU/docker, mailbox, multi-host DO lakes, second JobPool, multi-gateway, auto forum tags, silent ssh cook, phone companion Tailscale/ttyd/filebrowser.

Code: `src/agent_discord/host/jishaku.py`. Tests mock the load path — no live jishaku Discord session.
