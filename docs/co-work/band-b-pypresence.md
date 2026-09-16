# Band B — Mac Discord Rich Presence (pypresence)

**Ship:** Discord OS **0.5.82**. Independent of the bot gateway presence payloads.

Mac Discord desktop can show HOST as an activity: current Job / idle, plus On / Off / Halt. This is IPC Rich Presence on the listen machine — not guild bot status.

## Install / disable

```bash
pip install "discord-os[presence]"   # optional extra; CI does not need Discord desktop
```

| Knob | Meaning |
|---|---|
| Default | ON when `pypresence` is importable and `DISCORD_APPLICATION_ID` is set |
| `DISCORD_OS_PRESENCE=0` | Disable. Host keeps running; no IPC |
| `DISCORD_APPLICATION_ID` | Existing application id (invite / slash). Required to connect |

Fail soft if the extra is missing, Discord desktop is not running, or the IPC pipe is gone. Never crash `host run`.

## Mapping

| RPC field | Source |
|---|---|
| `details` | Live Job `DOS-*` + intake clip, or `idle` |
| `state` | HOST power: `On` / `Off` / `Halt` |

Gateway `presence_status` / `presence_name` on the bot stay as they are.

## Wire-in

`host run` / `listen` ticks presence on the same poll as liveness / status digest. HOST panel On / Off / Halt also ticks immediately. Session closes when listen exits.

Code: `src/agent_discord/host/presence.py`. Tests mock IPC — no Discord desktop.

## Parks

Board + brain lakes (never Graham). Band C (webhooks) not opened. HARD parks unchanged: CU/docker, mailbox, multi-host DO lakes, second JobPool, multi-gateway, auto forum tags, silent ssh cook, phone companion Tailscale/ttyd/filebrowser.
