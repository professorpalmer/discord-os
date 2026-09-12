# Compute

Not a compute host. Discord OS dispatches Puppetmaster on this Mac. That is the worker plane: analyze uses `--mode analyze`, implement takes the cwd write lock, live-thread steer flushes into the CLI process.

`AGENT_DISCORD_COMPUTE=auto` (default): agentic `openrouter/auto` when an OpenRouter key is in env or the workspace vault; **fail closed** when missing — spoken config Deny / `discord-os connect`. No Cursor fallback. No silent model remap. Requests for any other model fail closed.

Questions: `--mode analyze`. File work: `--mode implement --allow-dirty` on agentic. Spoken change asks (`enable`, `I'd like to`) are implement. Auto writes unless HOST Gate is on.

## Keys

```bash
discord-os connect --from-env
# or /connect in Discord (inherit / ticket / shred)
```

Vault: `{workspace}/keys/`. Key goes into the **subprocess env** as `OPENROUTER_API_KEY`, never argv, never logs. Agentic usage receipts carry `cost_usd` into Halt spend tracking.

Optional Marionette HTTP: `AGENT_DISCORD_BACKEND=marionette` plus `MARIONETTE_BASE_URL`. Unconfigured Marionette fails closed. Marionette uses the same `openrouter/auto` pin (or fails closed).

## Code

- `src/agent_discord/config.py` — `resolve_compute` (agentic-or-fail)
- `src/agent_discord/puppetmaster/agentic.py` — OpenRouter via `puppetmaster agentic`
- `src/agent_discord/puppetmaster/backend.py` — shared CLI helpers
- `src/agent_discord/keys/` — connect + vault
