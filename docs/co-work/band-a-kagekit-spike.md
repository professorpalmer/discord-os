# Band A — discord-kagekit spike (FAIL → thin HOST Page)

**Verdict:** **Do not adopt** `discord-kagekit` for Discord OS JobPool/HOST paint.

## Spike notes (discord-kagekit)

| Check | Result |
|---|---|
| Declarative `Page` / `Card` / `TabBar` | Works for Interaction UX |
| Stable `discord-os:*` custom IDs | **Fail** — Tab buttons get random hashes |
| REST / FakeDiscord / gateway | **Fail** — API centers on `LayoutView` + Interaction `send`/`edit` |
| Buttons without `on_click` | Render **disabled** even with `custom_id` |
| Would force rewrite | Half of `cards.py` paint + listen routing |

## Thin fallback (shipped)

In-tree `agent_discord.discord.host_page`: steal kagekit’s **layout contract** only — status **Container** + **action bar outside**. Same custom IDs / JobPool wiring via existing `layout.py`.

Flag: `DISCORD_OS_HOST_PAGE=1` (default). Set `0` to restore pre-Band-A monolith HOST container.

Optional extras: `pip install discord-os[kagekit]` for local experiments — **not** used by the host paint path.

## Next (not Band A)

Band B pypresence shipped in 0.5.82. Band C webhook shipped in 0.5.84. Band D jishaku shipped in 0.5.85 — Discord-native prioritized loop closed.
