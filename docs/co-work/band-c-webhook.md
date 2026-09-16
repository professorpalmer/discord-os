# Band C — ops webhook side-channel (discord-webhook)

**Ship:** Discord OS **0.5.84**. HTTP-only alerts. Not JobPool / HOST cards.

Optional `discord-webhook` extra posts ops-style lines to a Discord webhook channel. Interactive cards stay on the bot. Fail soft — a dead webhook never blocks gateway, cards, JobPool, or `host run`.

## Install / disable

```bash
pip install "discord-os[webhook]"   # optional extra; CI mocks HTTP
```

| Knob | Meaning |
|---|---|
| `DISCORD_OS_WEBHOOK_URL` empty / unset | **Off** |
| `DISCORD_OS_WEBHOOK_URLS` | Alias; comma-separated URLs allowed on either key |
| `DISCORD_OS_WEBHOOK=0` | Disable even when a URL is set |
| Default flag | On only when a URL is present and the flag is not `0` / `off` / `false` / `no` |

Empty URL = off. `DISCORD_OS_WEBHOOK=0` = off. Both are documented kill switches.

Fail soft if the extra is missing, HTTP errors, or the URL is wrong. Never crash `host run`.

## Events (ops only)

| Kind | When |
|---|---|
| `host_start` | Tip deploy / version kick / host start. Cheap, **once** per process |
| `job_fail` | Job settles Failed (cook path + thread-bind Need) |
| `halt` | Halt turns on (HOST Halt or spend cap). Once until Resume |
| `rate_limit` | Existing 429 retry signal. Debounced (one alert per ~60s burst) |

Username on the webhook is **Discord OS**. Board + brain lakes — never Graham.

## Wire-in

`host run` / `listen` fires `host_start` once after JobPool is built. Job fail and rate-limit hook from the orchestrator. Halt from `set_spend_halted`. Sync `DiscordWebhook.execute`; call sites are best-effort try/except.

Code: `src/agent_discord/host/webhook.py`. Tests mock HTTP — no live Discord webhook.

## Parks

Board + brain lakes (never Graham). Band D jishaku shipped in 0.5.85 (loop closed). Presence left alone. HARD parks unchanged: CU/docker, mailbox, multi-host DO lakes, second JobPool, multi-gateway, auto forum tags, silent ssh cook, phone companion Tailscale/ttyd/filebrowser.
