# Third-Party Notices

**Discord OS** is a GitHub-first, open-source Discord harness. Discord I/O is official Discord REST through a product-owned facade. There is no MCP bus inside Discord and no Discord MCP server source is vendored here.

## Puppetmaster

- Puppetmaster is an external local harness/CLI used as the **default** backend for agent runs.
- This project invokes the public Cursor worker CLI: `puppetmaster cursor --model grok-4.5 …`.
- Receipts and audit keep the canonical pin `cursor/grok-4-5` (adapter name `grok-4.5`) with an allowlist containing only that model. There is **no silent model fallback**.
- Do not edit Puppetmaster or Marionette from this repository.

## Marionette (optional)

- Marionette is an optional external HTTP worker API. This repository ships a thin adapter only (`AGENT_DISCORD_BACKEND=marionette`).
- Endpoint paths are configurable (`MARIONETTE_BASE_URL`, `MARIONETTE_SESSIONS_PATH`, `MARIONETTE_JOBS_PATH`). The adapter documents an expected contract; it does not vendor Marionette and does not claim an unverified upstream shape is guaranteed.
- When selected without a base URL, or when the transport fails, the bridge fails closed. There is **no silent fallback** to Puppetmaster.
- The model field on Marionette dispatches still carries the canonical pin `cursor/grok-4-5` / adapter `grok-4.5`.

## Other

- Python standard library and optional `pytest` for development tests.
- No Discord Gateway library is vendored here; Discord I/O goes through the REST provider.
