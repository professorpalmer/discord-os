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
