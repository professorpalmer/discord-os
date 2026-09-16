# Brain lake (per-DRI, Wave 4)

```bash
discord-os add brain --channel-id CHANNEL --dri alex \
  --strategy-docs ~/Projects/strategy \
  --transcripts-channel TRANSCRIPTS_CHANNEL_ID
```

Binds onto the channel:

- `dri` label
- strategy docs path (dir or file)
- meeting transcripts channel id
- journal inject (`preferences` kind `journal`)

Worker prompts get a `[brain-lake]` block (repos still via realm / Associated).

## Meat-proxy cut

`handoff` / `peer` JobPool tasks prepend lake context + ROE escalate hint so
agent lakes talk through cards — humans Pair/gate, they are not the copy-paste
proxy.

## Honest limit

**Single-host SQLite.** Not a multi-host Durable Objects brain lake. CU/docker
and external mailbox stay parked.


## Compact recall pack (Wave 5 P1a)

`format_brain_prompt_block` / `discord-os brain show --channel-id ID` emit a
budgeted pack: DRI, top strategy filenames, ≤5 journal notes, ≤3 Done summaries,
optional `[plan-gallery]` hits. Hard byte clip (~1800).

## DRI role SOP (Wave 5 P2b)

Optional `--role implementer|reviewer|planner` on `add brain`. Stored as `brain_role` and injected into the compact recall pack only (MetaGPT-lite). Not a multi-agent runtime.

## ARC-lite citations (Wave 6 P1e)

Compact recall pack + `discord-os brain show` list **Cites:** `DOS-*` / artifact
`sha8` / journal ids. Done cards may echo the same under **Cites**. No agent
`_recall` tool loop — SQLite ObsStore only.

