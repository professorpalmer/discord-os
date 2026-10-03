# Brain lake

```bash
discord-os add brain --channel-id CHANNEL \
  --strategy-docs ~/Projects/strategy \
  --transcripts-channel TRANSCRIPTS_CHANNEL_ID
```

Binds onto the channel:

- strategy docs path (dir or file)
- meeting transcripts channel id
- journal inject (`preferences` kind `journal`)

Worker prompts get a `[brain-lake]` block (repos still via realm / Associated).

Code: `src/agent_discord/host/memory.py`. The brain lake is the recall half of
the same durable store as memory channels — not a separate module.

## Meat-proxy cut

`handoff` / `peer` JobPool tasks prepend lake context + ROE escalate hint so
agent lakes talk through cards — humans Pair/gate, they are not the copy-paste
proxy. Code: `orchestration/handoff_envelope.py` `format_handoff_preamble`.

## Honest limit

**Single-host SQLite.** Not a multi-host Durable Objects brain lake. CU/docker
and external mailbox stay parked.

## Compact recall pack

`build_compact_recall_pack` / `discord-os brain show --channel-id ID` emit a
budgeted pack: top strategy filenames, ≤5 journal notes, ≤3 Done summaries,
optional `[plan-gallery]` hits. Hard byte clip (~1800).

## ARC-lite citations

Compact recall pack + `discord-os brain show` list **Cites:** `DOS-*` / artifact
`sha8` / journal ids. Done cards may echo the same under **Cites**. No agent
`_recall` tool loop — SQLite ObsStore only.

## Removed 2026-10-02

The DRI binding metadata is gone: `--dri`, the `--role` SOP label
(`implementer|reviewer|planner`), the `DRI:` / `Role SOP:` pack lines, and the
cross-DRI `Lanes:` footer on the HOST Jobs card. Production had zero brain
bindings using them. A handoff can still carry a free-text `brain_dri=` field
in its envelope.
